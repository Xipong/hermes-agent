"""Process completion admission must not deadlock the live session lock."""
import threading

import pytest


@pytest.mark.parametrize(
    ("changes", "requests", "expected"),
    [
        ({}, [], True),
        ({"running": False}, [], False),
        ({"_turn_cancel_requested": True}, [], False),
        ({"_finalized": True}, [], False),
        ({"queued_prompt": "next"}, [], False),
        ({}, [{"id": "srq-1"}], False),
        ({"_compute_host_open_request": {"id": "srq-2"}}, [], False),
    ],
)
def test_boundary_handles_live_session_lock(monkeypatch, changes, requests, expected):
    from tui_gateway import server, server_requests

    sid = "boundary-lock-test"
    session = {"history_lock": threading.Lock(), "running": True, **changes}
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server_requests, "open_requests", lambda actual_sid: requests)
    result = []
    errors = []

    def check():
        try:
            result.append(server._notif_process_boundary_allowed(sid, session))
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=check, daemon=True)
    worker.start()
    worker.join(timeout=2)
    deadlocked = worker.is_alive()
    if deadlocked:
        # Release the test-owned lock so a defective worker cannot strand teardown.
        session["history_lock"].release()
        worker.join(timeout=2)
    assert not deadlocked, "boundary check deadlocked on the session history lock"
    assert not errors
    assert result == [expected]
