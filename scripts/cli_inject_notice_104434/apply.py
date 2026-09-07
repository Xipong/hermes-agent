"""Restore CLI-visible completion notice for same-turn inject delivery in PR #104434."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(sys.argv[1])


def replace_once(path: str, old: str, new: str, label: str) -> None:
    p = ROOT / path
    text = p.read_text()
    count = text.count(old)
    assert count == 1, f"{label}: expected one match, found {count}"
    p.write_text(text.replace(old, new, 1))


# 1) Emit a display-only callback only after the durable inject acknowledgement succeeds.
replace_once(
    "agent/delegation_inject.py",
    '''def _claim_status(entry: dict[str, Any]) -> tuple[str | None, bool]:
    """Return durable state and whether this exact local token still owns it."""
    from tools.async_delegation import get_event_delivery_claim_status

    return get_event_delivery_claim_status(entry["event"], entry["claim_id"])


def _stop_claim_heartbeat_if_idle(agent: Any) -> None:
''',
    '''def _claim_status(entry: dict[str, Any]) -> tuple[str | None, bool]:
    """Return durable state and whether this exact local token still owns it."""
    from tools.async_delegation import get_event_delivery_claim_status

    return get_event_delivery_claim_status(entry["event"], entry["claim_id"])


def _emit_injected_delivery_notice(agent: Any, entries: list[dict[str, Any]]) -> None:
    """Tell interactive surfaces that durable same-turn delivery completed.

    The completion payload is already inside an ordinary tool result.  This is
    display-only: it must never add another conversation message or trigger a
    model turn.  Unknown progress-event consumers simply ignore the event.
    """
    callback = getattr(agent, "tool_progress_callback", None)
    if not callable(callback) or not entries:
        return
    events = [entry.get("event") for entry in entries if isinstance(entry.get("event"), dict)]
    if not events:
        return
    task_count = 0
    delegation_ids: list[str] = []
    for event in events:
        results = event.get("results")
        task_count += len(results) if isinstance(results, list) and results else 1
        delegation_id = str(event.get("delegation_id") or "")
        if delegation_id and delegation_id not in delegation_ids:
            delegation_ids.append(delegation_id)
    try:
        callback(
            "delegation.injected",
            "_delegation",
            None,
            None,
            task_count=max(1, task_count),
            unit_count=len(events),
            delegation_ids=delegation_ids,
        )
    except Exception:
        # Delivery is already durable; display failure must never roll it back.
        logger.debug("Failed to render same-turn delegation delivery notice", exc_info=True)


def _stop_claim_heartbeat_if_idle(agent: Any) -> None:
''',
    "inject display helper",
)

replace_once(
    "agent/delegation_inject.py",
    '''    keep: list[dict[str, Any]] = []
    settled_messages: list[dict[str, Any]] = []
    acknowledged = 0
''',
    '''    keep: list[dict[str, Any]] = []
    settled_messages: list[dict[str, Any]] = []
    acknowledged_entries: list[dict[str, Any]] = []
    acknowledged = 0
''',
    "acknowledged entries",
)
replace_once(
    "agent/delegation_inject.py",
    '''        if committed:
            acknowledged += 1
            settled_messages.append(message)
            continue
''',
    '''        if committed:
            acknowledged += 1
            acknowledged_entries.append(entry)
            settled_messages.append(message)
            continue
''',
    "ack success display capture",
)
replace_once(
    "agent/delegation_inject.py",
    '''    for message in settled_messages:
        if not (_message_event_ids(message) & still_pending_ids):
            _clear_carrier_metadata(message)
    _stop_claim_heartbeat_if_idle(agent)
    return acknowledged
''',
    '''    for message in settled_messages:
        if not (_message_event_ids(message) & still_pending_ids):
            _clear_carrier_metadata(message)
    _stop_claim_heartbeat_if_idle(agent)
    _emit_injected_delivery_notice(agent, acknowledged_entries)
    return acknowledged
''',
    "post-ack display emission",
)

# 2) Render the out-of-band event in the interactive CLI.  Keep this before
# tool-progress mode gates: a completion notice should remain visible even with
# /verbose tool history disabled, matching ordinary after_turn visibility.
replace_once(
    "hermes_cli/cli_stream_mixin.py",
    '''        from cli import CLI_CONFIG, _DIM, _RST, _cprint, _hermes_home
        # MoA reference outputs (display-only events from the MoA facade): render each answer
''',
    '''        from cli import CLI_CONFIG, _DIM, _RST, _cprint, _hermes_home
        if event_type == "delegation.injected":
            try:
                count = max(1, int(kwargs.get("task_count") or 1))
            except (TypeError, ValueError):
                count = 1
            if count == 1:
                text = "↪ Background agent finished — result injected into current turn."
            else:
                text = f"↪ {count} background agents finished — results injected into current turn."
            _cprint(f"  {_DIM}{text}{_RST}")
            self._invalidate()
            return
        # MoA reference outputs (display-only events from the MoA facade): render each answer
''',
    "CLI inject display branch",
)

# 3) Fold coverage into the already-retained contract tests: no new carrier cases.
replace_once(
    "tests/agent/test_delegation_delivery.py",
    '''    agent = _tool_boundary_agent()
    agent._incremental_persistence_failed = False
    agent._flush_messages_to_session_db = lambda _messages: False
''',
    '''    agent = _tool_boundary_agent()
    display_events = []
    agent.tool_progress_callback = lambda *args, **kwargs: display_events.append((args, kwargs))
    agent._incremental_persistence_failed = False
    agent._flush_messages_to_session_db = lambda _messages: False
''',
    "flush failure display capture",
)
replace_once(
    "tests/agent/test_delegation_delivery.py",
    '''    assert any(
        event.get("delegation_id") == delegation_id for event in _queue_contents()
    )


def test_owner_loss_retires_local_latch_and_next_turn_can_inject(monkeypatch):
''',
    '''    assert any(
        event.get("delegation_id") == delegation_id for event in _queue_contents()
    )
    assert not any(args and args[0] == "delegation.injected" for args, _ in display_events)


def test_owner_loss_retires_local_latch_and_next_turn_can_inject(monkeypatch):
''',
    "failed flush must not announce inject",
)
replace_once(
    "tests/agent/test_delegation_delivery.py",
    '''def test_run_conversation_inject_transport_normalize_and_ack(monkeypatch, tmp_path):
    agent = _make_loop_agent(tmp_path)
    cached_system_prompt = deepcopy(getattr(agent, "_cached_system_prompt"))
    requests = []
''',
    '''def test_run_conversation_inject_transport_normalize_and_ack(monkeypatch, tmp_path):
    agent = _make_loop_agent(tmp_path)
    cached_system_prompt = deepcopy(getattr(agent, "_cached_system_prompt"))
    requests = []
    display_events = []
    agent.tool_progress_callback = lambda *args, **kwargs: display_events.append((args, kwargs))
''',
    "loop display capture",
)
replace_once(
    "tests/agent/test_delegation_delivery.py",
    '''    assert _event_state(delegation_id) == ("delivered", 1)
    assert not agent._pending_delegation_inject_claims
    heartbeat = agent._delegation_inject_claim_heartbeat
''',
    '''    assert _event_state(delegation_id) == ("delivered", 1)
    assert not agent._pending_delegation_inject_claims
    injected = [item for item in display_events if item[0] and item[0][0] == "delegation.injected"]
    assert len(injected) == 1
    assert injected[0][1]["task_count"] == 1
    assert injected[0][1]["unit_count"] == 1
    assert injected[0][1]["delegation_ids"] == [delegation_id]
    heartbeat = agent._delegation_inject_claim_heartbeat
''',
    "loop durable inject display assertion",
)

# Extend the existing CLI delivery test instead of adding another pytest case.
replace_once(
    "tests/cli/test_cli_async_delegation_delivery.py",
    '''    assert claimed == [(event, "cli-idle")]
    assert completed == [(event, "claim-token")]


def test_cli_completion_ownership_rejects_foreign_session():
''',
    '''    assert claimed == [(event, "cli-idle")]
    assert completed == [(event, "claim-token")]

    # Same-turn inject uses a display-only progress event instead of putting a
    # second synthetic completion message into _pending_input.
    rendered = []
    monkeypatch.setattr("cli._cprint", rendered.append)
    cli._invalidate = lambda *args, **kwargs: None
    cli._on_tool_progress("delegation.injected", task_count=1, unit_count=1)
    cli._on_tool_progress("delegation.injected", task_count=3, unit_count=2)
    assert any("Background agent finished" in line and "injected into current turn" in line for line in rendered)
    assert any("3 background agents finished" in line and "injected into current turn" in line for line in rendered)
    assert cli._pending_input.empty()


def test_cli_completion_ownership_rejects_foreign_session():
''',
    "CLI display assertion",
)

print("Applied CLI same-turn inject delivery notice without adding conversation messages.")
