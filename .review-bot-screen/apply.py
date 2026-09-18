from pathlib import Path

root = Path.cwd()
p = root / 'tools/computer_use/tool.py'
s = p.read_text(encoding='utf-8')
s = s.replace('from typing import Any, Callable, Dict, List, Optional, Tuple',
              'from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple', 1)
helper = '''@contextlib.contextmanager
def _backend_for_call(session_id: str = "") -> Iterator[ComputerUseBackend]:
    """Hold a live backend through dispatch, retrying admission but never an action.

    A display/mode change or release can retire a backend before lock lookup or
    while a caller waits. Revalidate AFTER acquiring its profile-scoped call
    lock; teardown needs that same lock. Never wait under the global cache lock.
    """
    from tools.computer_use.cua_backend import backend_display_stale, desktop_identity

    sid = _scoped_sid(session_id)
    while True:
        backend = _get_backend(session_id=session_id)
        with _backend_lock:
            if _backends.get(sid) is not backend:
                continue
            call_lock = _backend_call_locks[sid]
        with call_lock:
            with _backend_lock:
                if (_backends.get(sid) is not backend
                        or _backend_call_locks.get(sid) is not call_lock):
                    continue
                # A queued call can outlive a display/config change even when
                # no other caller has replaced the cached backend yet.
                if (_backend_permission_modes.get(sid) != _cua_permission_mode(str(session_id or ""))
                        or backend_display_stale(_backend_displays.get(sid, ""), desktop_identity())):
                    continue
            yield backend
            return


'''
assert s.count('def release_computer_use_session(') == 1
s = s.replace('def release_computer_use_session(', helper + 'def release_computer_use_session(', 1)
old='''    try:
        backend = _get_backend(session_id=session_id)
    except Exception as e:
'''
new='''    # Acquire separately so startup errors retain the install hint; the stack
    # releases the admitted call lock on every dispatch return or exception.
    call = contextlib.ExitStack()
    try:
        backend = call.enter_context(_backend_for_call(session_id))
    except Exception as e:
'''
assert s.count(old) == 1
s=s.replace(old,new,1)
old='''        with _backend_lock:
            call_lock = _backend_call_locks.setdefault(session_id, threading.RLock())
        with call_lock:
'''
assert s.count(old) == 1
s=s.replace(old, '        with call:\n', 1)
p.write_text(s, encoding='utf-8')

p=root/'tests/tools/test_computer_use.py'
s=p.read_text(encoding='utf-8')
assert s.count('patch.object(cu_tool, "_get_backend", return_value=') == 4
s=s.replace('patch.object(cu_tool, "_get_backend", return_value=',
            'patch.object(cu_tool, "_new_backend", return_value=')
p.write_text(s, encoding='utf-8')
p=root/'tests/tools/test_bot_desktop_lease.py'
s=p.read_text(encoding='utf-8')
s=s.replace('    lease._reset_for_tests()\n    yield\n    lease._reset_for_tests()',
'''    from tools.computer_use import tool

    tool.reset_backend_for_tests()
    lease._reset_for_tests()
    yield
    tool.reset_backend_for_tests()
    lease._reset_for_tests()''',1)
s=s.replace('monkeypatch.setattr(tool, "_get_backend", lambda session_id="": object())',
            'monkeypatch.setattr(tool, "_new_backend", lambda mode: tool._NoopBackend())',1)
s=s.replace('    class Rec:', '    class Rec(tool._NoopBackend):',1)
s=s.replace('monkeypatch.setattr(tool, "_get_backend", lambda session_id="": rec)',
            'monkeypatch.setattr(tool, "_new_backend", lambda mode: rec)',1)
p.write_text(s, encoding='utf-8')
p=root/'tests/tools/test_computer_use_capture_fence.py'
s=p.read_text(encoding='utf-8')
s=s.replace('from tools.bot_desktop import lease',
            'from tools.bot_desktop import lease\nfrom tools.computer_use import tool',1)
s=s.replace('    lease._reset_for_tests()\n    yield\n    lease._reset_for_tests()',
'''    tool.reset_backend_for_tests()
    lease._reset_for_tests()
    yield
    tool.reset_backend_for_tests()
    lease._reset_for_tests()''',1)
s=s.replace('class _TakeoverBackend:', 'class _TakeoverBackend(tool._NoopBackend):',1)
s=s.replace('    from tools.computer_use import tool\n\n    monkeypatch.setattr(tool, "_get_backend", lambda session_id="": _TakeoverBackend())',
            '    monkeypatch.setattr(tool, "_new_backend", lambda mode: _TakeoverBackend())',1)
p.write_text(s, encoding='utf-8')
