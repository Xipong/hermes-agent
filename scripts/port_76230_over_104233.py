"""Build the opt-in layer only. BASE and REFERENCE are exact archived trees."""
from pathlib import Path
import ast
import re
import shutil
import sys

root = Path(sys.argv[1]); ref = Path(sys.argv[2])

def edit(path, old, new, count=1):
    p = root / path; s = p.read_text()
    assert s.count(old) == count, (path, s.count(old), old[:100])
    p.write_text(s.replace(old, new))

# These four files are unchanged between the merge base and #104233. Preserve
# the reference's already-reviewed insertion points, not its old delivery rail.
for name in ('agent/conversation_loop.py', 'agent/tool_executor.py',
             'agent/turn_finalizer.py', 'run_agent.py'):
    shutil.copyfile(ref / name, root / name)

# Keep the bounded carrier / transactional rollback oracle. Its only durable
# identity is now #104233's delegation_id; no event keys or routing manager.
s = (ref / 'agent/delegation_inject.py').read_text()
s = re.sub(r'def _event_identity\(.*?\n\n\ndef _message_event_ids',
    'def _event_identity(event: dict[str, Any]) -> str:\n'
    '    return str(event.get("delegation_id") or "")\n\n\ndef _message_event_ids', s, flags=re.S)
start = s.index('    def requeue(event):')
end = s.index('    # Formatting / sandbox I/O', start)
s = s[:start] + '''    def requeue(event):
        completion_queue.put(event)

    candidates = []
    # Queue.get_nowait is already atomic. Take only a bounded snapshot; an idle
    # consumer winning a race is a missed opportunity, not another delivery rail.
    for _ in range(completion_queue.qsize()):
        try:
            event = completion_queue.get_nowait()
        except queue.Empty:
            break
        delivery = str(event.get("result_delivery") or "after_turn").strip().lower()
        if (
            event.get("type") != "async_delegation"
            or delivery != "inject"
            or str(event.get("parent_turn_id") or "") != active_turn_id
            or str(event.get("parent_session_id") or "") != str(getattr(agent, "session_id", "") or "")
            or not event.get("parent_session_id")
        ):
            requeue(event)
            continue
        candidates.append(event)

''' + s[end:]
s = s.replace('    # Formatting / sandbox I/O must never hold the shared routing reservation.\n',
              '    # Formatting / sandbox I/O holds neither a queue nor a database lock.\n')
s = s.replace('            process_registry.defer_unclaimed_delivery(event)\n',
              '            if get_event_delivery_state(event) == "pending":\n                requeue(event)\n')
(root / 'agent/delegation_inject.py').write_text(s)

# Public/model-facing policy remains opt-in with the same default.
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
                    "'inject': for dependent reviews/audits; an already-ready result may ride the "
                    "last new tool result of a complete batch in this parent turn, before the next "
                    "model request. Never waits or adds a request; missed boundaries fall back to "
                    "ordinary after-turn delivery. 'after_turn' (default): independent background work."
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
edit(p, '    overall_start: float\n', '    overall_start: float\n    result_delivery: str = "after_turn"\n')
edit(p, 'def _dispatched_payload(dispatch: dict, goals: List[str], child_agents: List[Any], live_paths: List[str]) -> dict:',
        'def _dispatched_payload(dispatch: dict, goals: List[str], child_agents: List[Any], live_paths: List[str],\n'
        '                        result_delivery: str = "after_turn") -> dict:')
edit(p, '    sids = [getattr(c, "_subagent_id", None) for c in child_agents]\n', '''    payload["result_delivery"] = result_delivery
    if result_delivery == "inject":
        payload["note"] = (
            "Subagents run asynchronously. Keep working: ready results may ride a new tool-result "
            "boundary in this turn. Missed boundaries use normal after-turn delivery. Never wait or poll."
        )
    sids = [getattr(c, "_subagent_id", None) for c in child_agents]
''')
edit(p, '        parent_session_id=getattr(parent_agent, "session_id", None),\n',
        '        parent_session_id=getattr(parent_agent, "session_id", None),\n'
        '        result_delivery=batch.result_delivery,\n'
        '        parent_turn_id=str(getattr(parent_agent, "_active_turn_id", "") or ""),\n')
edit(p, '_dispatched_payload(dispatch, goals, child_agents, batch.live_paths)',
        '_dispatched_payload(dispatch, goals, child_agents, batch.live_paths, batch.result_delivery)')

# Two JSON metadata fields; no schema migration, new queue, or second ledger.
p = 'tools/async_delegation.py'
edit(p, 'while idle, so results surface as a NEW turn (never mid-turn) and inherit its de-dup and\n',
        'while idle. Opted-in results may instead ride a new tool result in their parent turn,\nwith the same de-dup and\n')
edit(p, '"model", "is_batch", *_ROUTING_KEYS)',
        '"model", "is_batch", "result_delivery", "parent_turn_id", *_ROUTING_KEYS)')
edit(p, '        "goal": goals[task_index] if 0 <= task_index < len(goals) else record.get("goal", ""), "goals": goals,\n',
        '        "result_delivery": record.get("result_delivery", "after_turn"),\n'
        '        "parent_turn_id": record.get("parent_turn_id", ""),\n'
        '        "goal": goals[task_index] if 0 <= task_index < len(goals) else record.get("goal", ""), "goals": goals,\n')
edit(p, '                "model": task.get("model"), "is_batch": bool(task.get("is_batch")),\n',
        '                "model": task.get("model"), "is_batch": bool(task.get("is_batch")),\n'
        '                "result_delivery": task.get("result_delivery", "after_turn"),\n'
        '                "parent_turn_id": task.get("parent_turn_id", ""),\n')
edit(p, '    progress_fn: Optional[Callable[[], tuple]], capacity_error: str,\n',
        '    progress_fn: Optional[Callable[[], tuple]], capacity_error: str,\n'
        '    result_delivery: Optional[str] = None, parent_turn_id: str = "",\n')
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
edit(p, '    progress_fn: Optional[Callable[[], tuple]] = None,\n',
        '    progress_fn: Optional[Callable[[], tuple]] = None,\n'
        '    result_delivery: Optional[str] = None, parent_turn_id: str = "",\n')
edit(p, '        parent_session_id=parent_session_id, runner=runner,\n',
        '        parent_session_id=parent_session_id, runner=runner,\n'
        '        result_delivery=result_delivery, parent_turn_id=parent_turn_id,\n', count=2)
edit(p, '        "parent_session_id": record.get("parent_session_id"),\n',
        '        "parent_session_id": record.get("parent_session_id"),\n'
        '        "parent_turn_id": record.get("parent_turn_id", ""),\n'
        '        "result_delivery": record.get("result_delivery", "after_turn"),\n')

# Reconciliation is in the EXISTING common claim function, not just the event
# wrapper: gateway's direct claim must honor the same transcript receipt.
edit(p, '            "SELECT delivery_state FROM async_delegations WHERE delegation_id=?", (delegation_id,)).fetchone()\n',
        '            "SELECT delivery_state, event_json FROM async_delegations WHERE delegation_id=?", (delegation_id,)).fetchone()\n')
edit(p, '            return True  # legacy event created before durable dispatch\n',
        '            return True  # legacy event created before durable dispatch\n'
        '        if row[0] == "pending" and _reconcile_tool_carrier(conn, delegation_id, row[1]):\n'
        '            return False\n')
edit(p, 'def complete_event_delivery(evt: Dict[str, Any], claim_id: str) -> None:\n    _event_delivery(complete_completion_delivery, evt, claim_id)\n',
        'def complete_event_delivery(evt: Dict[str, Any], claim_id: str) -> bool:\n'
        '    return (_event_delivery(complete_completion_delivery, evt, claim_id)\n'
        '            or get_event_delivery_state(evt) == "delivered")\n')
edit(p, 'def release_event_delivery(evt: Dict[str, Any], claim_id: str) -> None:\n    _event_delivery(release_completion_delivery, evt, claim_id)\n',
        'def release_event_delivery(evt: Dict[str, Any], claim_id: str) -> bool:\n'
        '    return _event_delivery(release_completion_delivery, evt, claim_id)\n')
edit(p, 'def _event_delivery(fn, evt: Dict[str, Any], claim_id: str) -> None:\n    if claim_id and evt.get("type") == "async_delegation":\n        fn(str(evt.get("delegation_id") or ""), claim_id)\n',
        'def _event_delivery(fn, evt: Dict[str, Any], claim_id: str) -> bool:\n'
        '    return bool(claim_id and evt.get("type") == "async_delegation"\n'
        '                and fn(str(evt.get("delegation_id") or ""), claim_id))\n')
helpers = '''def _reconcile_tool_carrier(conn, delegation_id: str, payload: str | None) -> bool:
    """An exact transcript receipt closes the commit-before-ack crash window.

    Runs inside the existing claim transaction, including gateway direct claims.
    The receipt is scoped to the parent session, role and row id; no second ledger.
    """
    event = json.loads(payload or "{}")
    if event.get("result_delivery") != "inject" or not event.get("parent_session_id"):
        return False
    try:
        rows = conn.execute(
            "SELECT display_metadata FROM messages WHERE session_id=? AND role='tool' "
            "AND display_metadata IS NOT NULL AND instr(display_metadata, ?) > 0",
            (event["parent_session_id"], delegation_id),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc) or "no such column" in str(exc):
            return False
        raise
    for (raw,) in rows:
        try:
            metadata = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(metadata, dict) or metadata.get("delegation_delivery") != "tool_boundary":
            continue
        identities = metadata.get("delegation_event_ids")
        if isinstance(identities, list) and delegation_id in identities:
            now = time.time()
            conn.execute(
                "UPDATE async_delegations SET delivery_state='delivered', delivered_at=?, updated_at=?, "
                "delivery_claim=NULL, delivery_claimed_at=NULL WHERE delegation_id=? AND delivery_state='pending'",
                (now, now, delegation_id),
            )
            return True
    return False


def get_event_delivery_state(evt: Dict[str, Any]) -> Optional[str]:
    if evt.get("type") != "async_delegation":
        return None
    with _DB_LOCK, _transaction() as conn:
        row = conn.execute("SELECT delivery_state FROM async_delegations WHERE delegation_id=?",
                           (str(evt.get("delegation_id") or ""),)).fetchone()
    return row[0] if row else None


def renew_event_delivery(evt: Dict[str, Any], claim_id: str) -> bool:
    """Keep the existing single-row lease live until the transcript flush settles."""
    if not claim_id or evt.get("type") != "async_delegation":
        return False
    now = time.time()
    return _update_delivery(
        "UPDATE async_delegations SET delivery_claimed_at=?, updated_at=? "
        "WHERE delegation_id=? AND delivery_state='pending' AND delivery_claim=?",
        (now, now, str(evt.get("delegation_id") or ""), claim_id),
    )


'''
edit(p, 'def claim_completion_delivery(delegation_id: str, claim_id: str) -> bool:\n',
        helpers + 'def claim_completion_delivery(delegation_id: str, claim_id: str) -> bool:\n')

# Keep semantic oracle tests, not assertions about the superseded ledger or
# coalescing envelopes. Those remain documented and unchanged in old #76230.
s = (ref / 'tests/agent/test_delegation_delivery.py').read_text()
omit = {
    '_durable_event_keys', '_parent_state',
    'test_inject_batch_publishes_first_child_without_waiting_for_sibling',
    'test_after_turn_remains_default_and_coalesces_all_ready_children',
    'test_batch_finalization_enqueues_ready_set_under_routing_lock',
    'test_requeued_after_turn_envelope_absorbs_newly_ready_sibling',
    'test_same_turn_claim_conflict_defers_pending_event',
    'test_quick_restart_requeues_after_live_delivery_lease_expires',
    'test_live_lease_retry_prunes_terminal_group_sibling',
    'test_formatter_runs_outside_shared_routing_reservation',
}
lines = s.splitlines(keepends=True)
for node in reversed(ast.parse(s).body):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in omit:
        start = min([node.lineno, *[d.lineno for d in node.decorator_list]]) - 1
        del lines[start:node.end_lineno]
s = ''.join(lines)
s = s.replace('ad.publish_batch_child_completion', 'ad.publish_batch_child')
s = s.replace('"SELECT delivery_state, delivery_attempts FROM async_delegation_events "\n            "WHERE delegation_id=? AND event_key=?",\n            (delegation_id, event_key),',
              '"SELECT delivery_state, delivery_attempts FROM async_delegations "\n            "WHERE delegation_id=?",\n            (f"{delegation_id}.{event_key.split(\':\')[1]}",),')
s = s.replace('event.get("delegation_id") == delegation_id', 'event.get("batch_id") == delegation_id')
s = s.replace('[event["delivery_event_key"] for event in _queue_contents()] == ["task:0"]',
              '[event["delegation_id"] for event in _queue_contents()] == [f"{delegation_id}.0"]')
s = s.replace('f"{delegation_id}:task:0"', 'f"{delegation_id}.0"').replace('f"{delegation_id}:task:1"', 'f"{delegation_id}.1"')
s = s.replace('    assert process_registry.defer_unclaimed_delivery(event) is False\n',
              '    assert not ad.claim_completion_delivery(event["delegation_id"], "direct-gateway-claim")\n')
s = re.sub(r'\n{4,}', '\n\n\n', s)
s = s.replace('"""Contracts for durable async delegation delivery and tool-boundary evidence."""',
    '"""Semantic oracle from #76230, adapted to #104233 single-row identities.\n\n'
    'Old after-turn coalescer/second-ledger tests intentionally remain on the reference PR;\n'
    '#104233 ready-child/restart tests cover the unchanged base rail.\n"""')
(root / 'tests/agent/test_delegation_delivery.py').write_text(s)

p = root / 'website/docs/user-guide/features/delegation.md'
p.write_text(p.read_text() + '''

### Time-sensitive results in the current turn

`delegate_task(result_delivery="inject", tasks=[...])` opts a review or dependency into
best-effort delivery at the next existing complete tool-result boundary of the originating
parent turn. The ready report is clearly marked as background evidence on the last **new,
unsent** tool result before its first transcript commit. It is not a new user request.

The default (including unknown or missing values) remains `after_turn`. An `inject` result
that misses a boundary, cannot fit the ordinary tool-result budget or cannot be durably
persisted stays on the same after-turn delivery rail. No waiting, polling, extra model
request, new queue or extra iteration is added. Large reports use the ordinary persisted
output mechanism; failed storage defers the full result rather than silently truncating it.
''')

for path in ('agent/delegation_inject.py', 'tests/agent/test_delegation_delivery.py'):
    ast.parse((root/path).read_text())
print('Port built on #104233 using #76230 as semantic oracle.')
