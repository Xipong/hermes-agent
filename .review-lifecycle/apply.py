"""Apply only the backend-lifetime fix to the exact Bot Screen review head."""
from pathlib import Path

p = Path('tools/computer_use/tool.py')
s = p.read_text(encoding='utf-8')
s = s.replace('from typing import Any, Callable, Dict, List, Optional, Tuple',
              'from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple', 1)
manager = '''@contextlib.contextmanager
def _backend_for_call(session_id: str = "") -> Iterator[ComputerUseBackend]:
    """Admit a live backend for one call; retry acquisition, never the action.

    A display/mode change or release can retire the backend before lock lookup
    or while waiting for its lock. Revalidate after acquiring the SAME lock
    teardown uses. Never wait for that lock while holding the global cache lock.
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
                # Config/display can change while queued even without another
                # caller replacing the cache. Reuse the existing rebind policy.
                if (_backend_permission_modes.get(sid) != _cua_permission_mode(str(session_id or ""))
                        or backend_display_stale(_backend_displays.get(sid, ""), desktop_identity())):
                    continue
            yield backend
            return


'''
needle = 'def release_computer_use_session(session_id: str) -> bool:'
assert s.count(needle) == 1
s = s.replace(needle, manager + needle, 1)
start = s.index('    try:\n        backend = _get_backend(session_id=session_id)', s.index('def handle_computer_use('))
end = s.index('\ndef _request_approval(', start)
old = s[start:end]
unavailable = old[old.index('    except Exception as e:'):old.index('    try:\n        with _backend_lock:')]
body_start = old.index('            # Re-check under the dispatch lock:')
body_end = old.index('\n    except _bd_lease.HumanHasControl as e:') + 1
body = old[body_start:body_end]
# Keep the human-control recheck and both epoch fences byte-for-byte,
# changing only their indentation within the admitted backend context.
body = ''.join('    ' + line if line.strip() else line for line in body.splitlines(keepends=True))
errors = old[body_end:]
errors = ''.join('        ' + line if line.strip() else line for line in errors.splitlines(keepends=True))
s = s[:start] + ('    try:\n        with _backend_for_call(session_id) as backend:\n            try:\n'
                + body + errors.rstrip() + '\n' + unavailable) + s[end:]
p.write_text(s, encoding='utf-8')

# Inject fake backends at construction so existing dispatch tests still exercise
# the real cache and admission path instead of returning unregistered objects.
p = Path('tests/tools/test_computer_use.py')
s = p.read_text(encoding='utf-8')
assert s.count('patch.object(cu_tool, "_get_backend", return_value=') == 4
s = s.replace('patch.object(cu_tool, "_get_backend", return_value=',
              'patch.object(cu_tool, "_new_backend", return_value=')
p.write_text(s, encoding='utf-8')
p = Path('tests/tools/test_bot_desktop_lease.py')
s = p.read_text(encoding='utf-8')
s = s.replace('def _fresh_lease():\n    lease._reset_for_tests()\n    yield\n    lease._reset_for_tests()',
'''def _fresh_lease():
    from tools.computer_use import tool

    tool.reset_backend_for_tests()
    lease._reset_for_tests()
    yield
    tool.reset_backend_for_tests()
    lease._reset_for_tests()''', 1)
s = s.replace('monkeypatch.setattr(tool, "_get_backend", lambda session_id="": object())',
              'monkeypatch.setattr(tool, "_new_backend", lambda mode: tool._NoopBackend())', 1)
s = s.replace('    class Rec:\n', '    class Rec(tool._NoopBackend):\n', 1)
s = s.replace('monkeypatch.setattr(tool, "_get_backend", lambda session_id="": rec)',
              'monkeypatch.setattr(tool, "_new_backend", lambda mode: rec)', 1)
p.write_text(s, encoding='utf-8')
