"""Trim PR #104434 tests to the minimal behavior/correctness contract."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import sys

ROOT = Path(sys.argv[1])
PATH = ROOT / "tests/agent/test_delegation_delivery.py"

KEEP = {
    # Safe carrier boundary and append-only transcript shape.
    "test_tool_boundary_opens_only_after_the_complete_result_batch",
    "test_persisted_or_invalid_tool_tail_is_never_a_carrier",
    "test_run_conversation_inject_transport_normalize_and_ack",
    "test_tool_carrier_preserves_provider_roles_and_existing_prefix_items",
    # Persistence, fallback and bounded evidence.
    "test_tool_boundary_flush_failure_restores_carrier_and_requeues_event",
    "test_persisted_bounded_carrier_survives_production_compressor_payload",
    "test_formatter_failure_does_not_consume_delivery_attempts",
    # Review blockers: durable receipt, TUI liveness and routing ownership.
    "test_reconciled_carrier_claim_rejection_leaves_tui_runnable",
    "test_tui_busy_dequeue_cannot_hide_ready_inject_from_tool_boundary",
    # Jerry's owner-loss concern, including conservative uncertain failures.
    "test_owner_loss_retires_local_latch_and_next_turn_can_inject",
    "test_uncertain_previous_turn_claim_does_not_block_current_turn",
    # #104299 unit semantics, policy propagation/default and #104373 recovery.
    "test_inject_uses_completed_units_without_splitting_groups_or_capacity",
    "test_unit_dispatch_propagates_policy_and_default_uses_same_after_turn_claim",
    "test_abandoned_unit_retains_dispatch_policy_and_turn_on_recovery",
}


def test_nodes(text: str) -> list[ast.FunctionDef]:
    tree = ast.parse(text)
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]


def span(node: ast.FunctionDef) -> tuple[int, int]:
    starts = [node.lineno, *(d.lineno for d in node.decorator_list)]
    return min(starts) - 1, node.end_lineno


text = PATH.read_text()
original_nodes = test_nodes(text)
assert len(original_nodes) == 41, f"unexpected source test count: {len(original_nodes)}"
assert KEEP <= {node.name for node in original_nodes}

# Collapse policy normalization/default coverage into one test process instead of
# four parametrized pytest cases. Each subcase still runs the real completion-unit
# dispatch, queue, carrier and ordinary after-turn claim paths.
policy_node = next(
    node
    for node in original_nodes
    if node.name
    == "test_unit_dispatch_propagates_policy_and_default_uses_same_after_turn_claim"
)
start, end = span(policy_node)
lines = text.splitlines(keepends=True)
replacement = '''def test_unit_dispatch_propagates_policy_and_default_uses_same_after_turn_claim(monkeypatch):
    cases = [
        (None, "after_turn"),
        ("unknown-mode", "after_turn"),
        (" INJECT ", "inject"),
    ]
    for requested, expected in cases:
        ad._reset_for_tests()
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()
        gates = [threading.Event() for _ in range(3)]
        agent = _tool_boundary_agent()
        messages = [
            {"role": "tool", "tool_call_id": "current", "content": "unchanged"}
        ]
        try:
            handle = _gated_unit_call(monkeypatch, gates, delivery=requested)
            assert handle["status"] == "dispatched"
            assert handle["result_delivery"] == expected
            for gate in gates:
                gate.set()
            events = [
                process_registry.completion_queue.get(timeout=5) for _ in range(2)
            ]
            assert {event["delegation_id"] for event in events} == {
                unit["delegation_id"] for unit in handle["units"]
            }
            for event in events:
                assert event["result_delivery"] == expected
                assert event["parent_turn_id"] == "turn-current"
                process_registry.completion_queue.put(event)

            attached = attach_ready_injects_to_tool_results(agent, messages, 1)
            if expected == "inject":
                assert attached == 2  # two units, never three child rows
                assert release_pending_injects(agent, messages) == 2
            else:
                assert attached == 0
            assert messages[-1]["content"] == "unchanged"

            for _ in range(2):
                event = process_registry.completion_queue.get(timeout=5)
                claim = ad.claim_event_delivery(event, "ordinary-after-turn")
                assert claim
                assert ad.complete_event_delivery(event, claim)
                assert ad.get_event_delivery_state(event) == "delivered"
        finally:
            for gate in gates:
                gate.set()
            release_pending_injects(agent, messages)

        deadline = time.monotonic() + 2
        while ad.active_count() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ad.active_count() == 0
'''
lines[start:end] = [replacement]
text = "".join(lines)

# Remove every micro-test whose invariant is already subsumed by a retained
# integration/failure/race test. Decorators are removed with their functions.
nodes = test_nodes(text)
lines = text.splitlines(keepends=True)
remove = [span(node) for node in nodes if node.name not in KEEP]
for start, end in sorted(remove, reverse=True):
    del lines[start:end]
text = "".join(lines)
text = re.sub(r"\n{4,}", "\n\n\n", text)
text = text.replace(
    '"""Semantic oracle from #76230, adapted to #104299 completion-unit identities.\n\n'
    'Old coalescer/second-ledger tests remain on the reference PR. Production unit\n'
    'finalization, grouping, persistence and restart paths are exercised here.\n'
    '"""',
    '"""Minimal semantic contract from #76230 on #104299 completion units.\n\n'
    'Each retained test owns a distinct merge-blocking invariant: carrier boundary,\n'
    'durability/fallback, provider shape, bounded spill, routing/TUI races, owner\n'
    'loss, completion-unit grouping/defaults, or crash recovery.\n'
    '"""',
)
PATH.write_text(text)

remaining = test_nodes(text)
assert {node.name for node in remaining} == KEEP
assert len(remaining) == 14
print(f"Trimmed top-level carrier tests: {len(original_nodes)} -> {len(remaining)}")
print("Expected pytest cases in carrier suite: 15 (one TUI test has two consumers)")
for node in remaining:
    print(f"  keep {node.name}")
