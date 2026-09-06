"""Reapply only #104419's policy/carrier over the merged #104299 surface.

Run in an exact #104299 checkout. PRIOR is the archived old #104419 tree.
The original #76230 and the superseded #104233 child-publication rail are not changed.
"""
from pathlib import Path
import ast
import re
import subprocess
import sys

root, prior, patch_file = map(Path, sys.argv[1:4])


def edit(path, old, new, count=1):
    p = root / path
    text = p.read_text()
    assert text.count(old) == count, (path, text.count(old), old[:100])
    p.write_text(text.replace(old, new))


# These integration hunks apply unchanged; do not copy whole facade/loop files.
subprocess.run([
    'git', 'apply', '--exclude=tools/async_delegation.py',
    '--exclude=tools/delegate_tool.py', '--exclude=tools/delegate_tool_dispatch.py',
    str(patch_file.resolve()),
], cwd=root, check=True)

p = 'tools/delegate_tool.py'
edit(p, '    message: Optional[str] = None, parent_agent=None, credentials_cfg: Optional[Dict[str, Any]] = None,\n',
        '    message: Optional[str] = None, parent_agent=None, credentials_cfg: Optional[Dict[str, Any]] = None,\n'
        '    result_delivery: Optional[str] = None,\n')
edit(p, '    depth = getattr(parent_agent, "_delegate_depth", 0)\n',
        '    _delivery = str(result_delivery or "after_turn").strip().lower()\n'
        '    if _delivery not in {"inject", "after_turn"}:\n'
        '        _delivery = "after_turn"\n\n'
        '    depth = getattr(parent_agent, "_delegate_depth", 0)\n')
edit(p, '        live_deleg_id, live_writers, live_paths, *origin, overall_start,\n',
        '        live_deleg_id, live_writers, live_paths, *origin, overall_start, result_delivery=_delivery,\n')
edit(p, '            "message": _p(\n', '''            "result_delivery": {
                "type": "string", "enum": ["inject", "after_turn"], "default": "after_turn",
                "description": (
                    "'inject': for dependent reviews/audits; an already-ready completion unit may ride "
                    "the last new tool result of a complete batch in this parent turn, before the next "
                    "model request. Grouped tasks still finish together. Never waits or adds a request; "
                    "missed boundaries fall back to ordinary after-turn delivery. "
                    "'after_turn' (default): independent background work."
                ),
            },
            "message": _p(
''')
edit(p, '        action=args.get("action"), subagent_id=args.get("subagent_id"), message=args.get("message"),\n',
        '        action=args.get("action"), subagent_id=args.get("subagent_id"), message=args.get("message"),\n'
        '        result_delivery=args.get("result_delivery"),\n')
edit(p, '    "USE FOR: reasoning-heavy subtasks,',
        '    "Use result_delivery=inject for reviews that can affect this turn; otherwise results arrive after it.\\n\\n"\n'
        '    "USE FOR: reasoning-heavy subtasks,')

p = 'tools/delegate_tool_dispatch.py'
edit(p, '    group: Optional[str] = None\n',
        '    group: Optional[str] = None\n    result_delivery: str = "after_turn"\n')
edit(p, '    sids = [getattr(c, "_subagent_id", None) for (_, _, c) in batch.children]\n', '''    payload["result_delivery"] = batch.result_delivery
    if batch.result_delivery == "inject":
        payload["note"] = (
            "Subagents run asynchronously; each ungrouped task reports alone and grouped tasks finish together. "
            "Keep working: ready units may ride a new tool-result boundary in this turn. "
            "Missed boundaries use normal after-turn delivery. Never wait or poll."
        )
    sids = [getattr(c, "_subagent_id", None) for (_, _, c) in batch.children]
''')
edit(p, '        progress_fn=lambda: _batch_progress_token(child_agents), **routing,\n',
        '        result_delivery=unit.result_delivery,\n'
        '        parent_turn_id=str(getattr(unit.parent_agent, "_active_turn_id", "") or ""),\n'
        '        progress_fn=lambda: _batch_progress_token(child_agents), **routing,\n')

p = 'tools/async_delegation.py'
edit(p, 'while idle, so results surface as a NEW turn (never mid-turn) and inherit its de-dup and\n',
        'while idle. Opted-in completion units may instead ride a new tool result in their parent\n'
        'turn, with the same de-dup and\n')
edit(p, '"model", "is_batch", *_ROUTING_KEYS)',
        '"model", "is_batch", "result_delivery", "parent_turn_id", *_ROUTING_KEYS)')
edit(p, '                "model": task.get("model"), "is_batch": bool(task.get("is_batch")),\n',
        '                "model": task.get("model"), "is_batch": bool(task.get("is_batch")),\n'
        '                "result_delivery": task.get("result_delivery", "after_turn"),\n'
        '                "parent_turn_id": task.get("parent_turn_id", ""),\n')
# Both the shared dispatch core and batch entry point already have #104299's slot/index arguments.
edit(p, '    task_indexes: Optional[List[int]] = None,\n',
        '    task_indexes: Optional[List[int]] = None,\n'
        '    result_delivery: Optional[str] = None, parent_turn_id: str = "",\n', count=2)
edit(p, '    is_batch = goals is not None\n',
        '    result_delivery = str(result_delivery or "after_turn").strip().lower()\n'
        '    if result_delivery not in {"inject", "after_turn"}:\n'
        '        result_delivery = "after_turn"\n'
        '    is_batch = goals is not None\n')
edit(p, '        "origin_session_id": origin_session_id, "parent_session_id": parent_session_id,\n',
        '        "origin_session_id": origin_session_id, "parent_session_id": parent_session_id,\n'
        '        "result_delivery": result_delivery, "parent_turn_id": parent_turn_id,\n')
edit(p, '    max_async_children: int = _DEFAULT_MAX_ASYNC_CHILDREN, progress_fn: Optional[Callable[[], tuple]] = None,\n',
        '    max_async_children: int = _DEFAULT_MAX_ASYNC_CHILDREN, progress_fn: Optional[Callable[[], tuple]] = None,\n'
        '    result_delivery: Optional[str] = None, parent_turn_id: str = "",\n')
edit(p, '        parent_session_id=parent_session_id, runner=runner,\n',
        '        parent_session_id=parent_session_id, runner=runner,\n'
        '        result_delivery=result_delivery, parent_turn_id=parent_turn_id,\n', count=2)
edit(p, '        "parent_session_id": record.get("parent_session_id"),\n',
        '        "parent_session_id": record.get("parent_session_id"),\n'
        '        "parent_turn_id": record.get("parent_turn_id", ""),\n'
        '        "result_delivery": record.get("result_delivery", "after_turn"),\n')

# Keep the existing single-row claims. Receipt reconciliation belongs in their
# common claim path, including gateway's direct claims after a restart.
old = (prior / p).read_text()
functions = {n.name: ast.get_source_segment(old, n) for n in ast.parse(old).body if isinstance(n, ast.FunctionDef)}
helpers = '\n\n\n'.join(functions[n] for n in (
    '_reconcile_tool_carrier', 'get_event_delivery_state', 'renew_event_delivery'))
edit(p, 'def claim_completion_delivery(delegation_id: str, claim_id: str) -> bool:\n',
        helpers + '\n\n\ndef claim_completion_delivery(delegation_id: str, claim_id: str) -> bool:\n')
edit(p, '            "SELECT delivery_state FROM async_delegations WHERE delegation_id=?", (delegation_id,)).fetchone()\n',
        '            "SELECT delivery_state, event_json FROM async_delegations WHERE delegation_id=?", (delegation_id,)).fetchone()\n')
edit(p, '            return True  # legacy event created before durable dispatch\n',
        '            return True  # legacy event created before durable dispatch\n'
        '        if row[0] == "pending" and _reconcile_tool_carrier(conn, delegation_id, row[1]):\n'
        '            return False\n')
for name in ('complete_event_delivery', 'release_event_delivery', '_event_delivery'):
    text = (root / p).read_text()
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
    edit(p, ast.get_source_segment(text, node), functions[name])

# Preserve semantic assertions, replacing only the retired child-publication
# fixture with #104299's real unit finalization/SQLite/queue path.
p = 'tests/agent/test_delegation_delivery.py'
edit(p, '"""Semantic oracle from #76230, adapted to #104233 single-row identities.\n\n'
        'Old after-turn coalescer/second-ledger tests intentionally remain on the reference PR;\n'
        '#104233 ready-child/restart tests cover the unchanged base rail.\n"""',
        '"""Semantic oracle from #76230, adapted to #104299 completion-unit identities.\n\n'
        'Old coalescer/second-ledger tests remain on the reference PR. Production unit\n'
        'finalization, grouping, persistence and restart paths are exercised here.\n"""')
edit(p, 'def _event_state(delegation_id: str, event_key: str):', 'def _event_state(delegation_id: str):')
edit(p, '            (f"{delegation_id}.{event_key.split(\':\')[1]}",),', '            (delegation_id,),')
text = (root / p).read_text().replace(', "task:0"', '').replace('f"{delegation_id}.0"', 'delegation_id')
text = text.replace('f"{delegation_id}.1"', 'f"{delegation_id}-different-unit"')
text, replacements = re.subn(r'ad\.publish_batch_child\(\s*delegation_id, 0, ', '_complete_unit(delegation_id, ', text)
assert replacements == 28, replacements
(root / p).write_text(text)
edit(p, 'def _queue_contents():\n', '''def _complete_unit(delegation_id: str, child: dict) -> bool:
    """Complete an existing unit through the production finalizer, not a child-row shim."""
    result = {"results": [child], "total_duration_seconds": child["duration_seconds"]}
    ad._finalize(delegation_id, result, ad._batch_status(result))
    return _event_state(delegation_id) == ("pending", 0)


def _queue_contents():
''')
edit('website/docs/user-guide/features/delegation.md',
     'unsent** tool result before its first transcript commit. It is not a new user request.\n',
     'unsent** tool result before its first transcript commit. It is not a new user request.\n\n'
     'The timing policy does not change completion grouping: an ungrouped task is eligible\n'
     'when it finishes, while tasks sharing a `group` become eligible together only after\n'
     'the whole group finishes. Each unit keeps its existing delegation identity and claim;\n'
     'all units of one call still share one concurrency slot.\n')
for path in subprocess.check_output(['git', 'diff', '--name-only'], cwd=root, text=True).splitlines():
    if path.endswith('.py'):
        ast.parse((root / path).read_text(), filename=path)
print('Applied opt-in policy over #104299; no old child-publication API or ledger imported.')

# Extra contracts exercise #104299 grouping/defaults via the real dispatch path.
unit_tests = Path(__file__).with_name('unit_tests_104299.txt').read_text()
with (root / 'tests/agent/test_delegation_delivery.py').open('a') as target:
    target.write(unit_tests)
ast.parse((root / 'tests/agent/test_delegation_delivery.py').read_text())
