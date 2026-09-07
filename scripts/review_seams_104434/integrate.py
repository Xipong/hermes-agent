from pathlib import Path
import subprocess,re
import sys
r=Path(sys.argv[1])
def src(ref,path):return subprocess.check_output(['git','show',f'{ref}:{path}'],cwd=r,text=True)
def replace(s,old,new):
 assert s.count(old)==1,(old[:80],s.count(old))
 return s.replace(old,new,1)
# Iteration warnings must be present before measuring/inserting/persisting the carrier.
p=r/'agent/tool_executor.py'; s=p.read_text(encoding="utf-8")
s=re.sub(r'<<<<<<< (?:HEAD|ours)\n.*?=======\n(.*?)>>>>>>> (?:snapshot-head|theirs)\n',lambda m:m[1],s,flags=re.S)
needle='    # A known no-op persistence path cannot accept a durable carrier.'
s=replace(s,needle,'''    from agent.turn_iteration_prep import _maybe_inject_iteration_budget_warning

    # Preserve main's checkpoint warning before sizing or stamping the tool result.
    _maybe_inject_iteration_budget_warning(agent, messages)

'''+needle)
p.write_text(s, encoding="utf-8")
# Main's post-turn consumer now uses the same batch owner as its poller.
p=r/'tui_gateway/prompt_turn.py'; s=p.read_text(encoding="utf-8")
s=re.sub(r'<<<<<<< (?:HEAD|ours)\n(.*?)=======\n.*?>>>>>>> (?:snapshot-head|theirs)\n',lambda m:m[1],s,flags=re.S)
s=replace(s,'        for event in deferred:\n            process_registry.completion_queue.put(event)',
'''        with process_registry.completion_routing_lock:
            for event in deferred:
                process_registry.completion_queue.put(event)''')
p.write_text(s, encoding="utf-8")
# Compose the feature's short queue reservation with main's completion batching.
path='tui_gateway/session_notifications.py'; main=src('snapshot-main',path); feat=src('snapshot-head',path)
start=main.index('def _notif_dispatch_event('); end=main.index('def _async_delegation_display_metadata(')
helpers=feat[feat.index('def _notif_requeue_if_pending('):feat.index('def _notification_poller_loop(')]
# reservation can also classify a raw snapshot supplied by an already-owning caller;
# the poller always calls it WHILE dequeuing under the shared lock.
helpers=replace(helpers,'def _notif_reserve_event(sid: str, session: dict, registry, *, shutdown: bool = False):',
'''def _notif_reserve_event(sid: str, session: dict, registry, *, shutdown: bool = False,
                         event=None, owned: bool = False):''')
helpers=replace(helpers,'''    try:
        evt = queue.get_nowait()
    except Exception:
        return None, "empty"
''','''    if event is None:
        try:
            evt = queue.get_nowait()
        except Exception:
            return None, "empty"
    else:
        evt = event
''')
helpers=replace(helpers,'    if _notification_event_belongs_elsewhere(sid, session, evt):','    if not owned and _notification_event_belongs_elsewhere(sid, session, evt):')
helpers=replace(helpers,'    if _notification_event_requires_owner(evt) and not _session_owns_notification_event(sid, session, evt):','    if not owned and _notification_event_requires_owner(evt) and not _session_owns_notification_event(sid, session, evt):')
helpers=replace(helpers,'def _notif_handle_event(sid, session, evt, emitted, registry, fmt, action) -> None:',
 'def _notif_handle_event(sid, session, evt, emitted, registry, fmt, action, completions) -> None:')
helpers=replace(helpers,'        _emit("status.update", sid, {"kind": "process", "text": text})',
'''        from tools.process_registry_notifications import async_delegation_display_text
        display_text = async_delegation_display_text(evt) if evt.get("type") == "async_delegation" else text
        _emit("status.update", sid, {"kind": "process", "text": display_text})''')
helpers=replace(helpers,'''    if action != "reserved":
        return

    from tools.async_delegation import claim_event_delivery''',
'''    if action != "reserved":
        return
    if evt.get("type", "completion") == "completion":
        completions.append((evt, text))
        return

    from tools.async_delegation import claim_event_delivery''')
# Don't silently lose a raw event if a claim read itself raises.
helpers=replace(helpers,'''    with session["history_lock"]:
        if session.get("running") or session.get("_finalized"):
            claim = None
            raced_busy = True
        else:
            raced_busy = False
            claim = claim_event_delivery(evt, "tui-poller")
            if claim is not None:
                session["running"] = True
''', '''    try:
        with session["history_lock"]:
            if session.get("running") or session.get("_finalized"):
                claim = None
                raced_busy = True
            else:
                raced_busy = False
                claim = claim_event_delivery(evt, "tui-poller")
                if claim is not None:
                    session["running"] = True
    except Exception:
        _notif_requeue_if_pending(registry, evt)
        logger.exception("Could not claim notification; kept for retry")
        return
''')
batch=main[main.index('def _notif_dispatch_completions('):main.index('def _notif_handle_ready(')]
# Batch here contains only process notifications, whose claim is the empty token.
# Retain main's ProcessNotificationBatch render and claim behavior; lock requeues.
batch=replace(batch,'''        for event, _text in notifications:
            (deferred.append if deferred is not None else registry.completion_queue.put)(event)''',
'''        with registry.completion_routing_lock:
            for event, _text in notifications:
                (deferred.append if deferred is not None else registry.completion_queue.put)(event)''')
ready='''def _notif_handle_ready(sid, session, events, emitted, registry, fmt, deferred, *, owned=False, reservations=None):
    """Preserve main's ordered completion runs and its ownership-once post-turn path.

    The poller supplies reservations classified under the shared routing lock.
    Post-turn events have already passed ProcessRegistry's ownership filter.
    Rendering, durable claims and agent turns are all outside that lock.
    """
    completions = []
    for index, event in enumerate(events):
        if event.get("type", "completion") != "completion":
            _notif_dispatch_completions(sid, session, completions, registry, deferred)
            completions = []
        if reservations is None:
            with registry.completion_routing_lock:
                event, action = _notif_reserve_event(
                    sid, session, registry, event=event, owned=owned,
                    shutdown=deferred is not None)
        else:
            action = reservations[index]
        if event is not None:
            _notif_handle_event(sid, session, event, emitted, registry, fmt, action, completions)
    _notif_dispatch_completions(sid, session, completions, registry, deferred)


def _notif_drain_ready(sid, session, registry, *, shutdown=False):
    """One bounded routing snapshot; busy/foreign events are requeued before unlock."""
    ready, actions = [], []
    with registry.completion_routing_lock:
        for _ in range(registry.completion_queue.qsize()):
            event, action = _notif_reserve_event(sid, session, registry, shutdown=shutdown)
            if event is not None:
                ready.append(event)
                actions.append(action)
    return ready, actions


'''
poller=feat[feat.index('def _notification_poller_loop('):feat.index('def _async_delegation_display_metadata(')]
poller=replace(poller,'    emitted: set = set()','    emitted = session.setdefault("_notification_emitted", set())')
pos=poller.index('        with process_registry.completion_routing_lock:')
poller=poller[:pos]+'''        ready, actions = _notif_drain_ready(sid, session, process_registry)
        _notif_handle_ready(sid, session, ready, emitted, process_registry,
                            format_process_notification, None, reservations=actions)
        if not ready or "busy" in actions:
            time.sleep(0.25 if ready else 0.5)

    ready, actions = _notif_drain_ready(sid, session, process_registry, shutdown=True)
    deferred = []
    _notif_handle_ready(sid, session, ready, emitted, process_registry,
                        format_process_notification, deferred, reservations=actions)
    with process_registry.completion_routing_lock:
        for event in deferred:
            process_registry.completion_queue.put(event)


'''
(r/path).write_text(main[:start]+helpers+batch+ready+poller+main[end:], encoding="utf-8")
# Model-facing note describes actual result units, not the now-opt-in partition.
p=r/'tools/delegate_tool_dispatch.py'; s=p.read_text(encoding="utf-8")
s=replace(s,'            "Subagents run asynchronously; each ungrouped task reports alone and grouped tasks finish together. "',
'''            f"{n} subagent(s) run asynchronously as {len(units)} completion unit(s); "
            "each unit reports once after all of its tasks finish. "''')
p.write_text(s, encoding="utf-8")
