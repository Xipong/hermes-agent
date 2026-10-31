"""Process completion fallback keeps identity across refusal and failed dispatch."""
import threading
from types import SimpleNamespace

import pytest

from tests.agent.test_process_completion_inject import _rig, _complete


@pytest.mark.parametrize("failure", ["refuse", "raise", "claim"])
def test_batch_retry_keeps_order_and_only_acknowledges_accepted_turn(tmp_path, monkeypatch, failure):
    from tui_gateway import server
    from tools import async_delegation
    from tools.process_registry_notifications import format_process_notification
    from tools.process_completion_delivery import delivered
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_first")
        _complete(registry, "proc_second")
        events = [registry.completion_queue.get_nowait() for _ in range(2)]
        session = {"history_lock": threading.RLock(), "running": False}
        monkeypatch.setattr(server, "_notif_claim_turn", lambda s: s.update(running=True) or True)
        monkeypatch.setattr(server, "_notif_refusal_backoff", lambda s: None)
        real_claim = async_delegation.claim_event_delivery
        count = 0
        def claim(event, consumer):
            nonlocal count
            count += 1
            if failure == "claim" and count == 2:
                raise OSError("claim temporarily unavailable")
            return real_claim(event, consumer)
        monkeypatch.setattr(async_delegation, "claim_event_delivery", claim)
        def submit(*args, **kwargs):
            if failure == "raise":
                raise RuntimeError("dispatch failed before admission")
            return False
        monkeypatch.setattr(server, "_run_prompt_submit", submit)
        server._notif_dispatch_completions("sid", session, [(e, format_process_notification(e)) for e in events], registry, None)
        assert all(not delivered(registry, e) for e in events)
        assert [e["session_id"] for e in registry.completion_queue.queue] == ["proc_first", "proc_second"]
        assert not session["running"]
        monkeypatch.setattr(async_delegation, "claim_event_delivery", real_claim)
        accepted = []
        def accept(*args, **kwargs):
            accepted.append(args[3])
            kwargs["terminal_callback"]({"status": "settled", "text": "handled"})
            return True
        monkeypatch.setattr(server, "_notif_submit", accept)
        retry = [registry.completion_queue.get_nowait() for _ in range(2)]
        server._notif_dispatch_completions("sid", session, [(e, format_process_notification(e)) for e in retry], registry, None)
        assert len(accepted) == 1
        assert all(delivered(registry, e) for e in events)
    finally:
        agent._session_db.close()


def test_async_admission_is_not_a_delivery_receipt(tmp_path, monkeypatch):
    from tui_gateway import server
    from tools.process_registry_notifications import format_process_notification
    from tools.process_completion_delivery import delivered
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_async_receipt")
        event = registry.completion_queue.get_nowait()
        session = {"history_lock": threading.RLock(), "running": False}
        monkeypatch.setattr(server, "_notif_claim_turn", lambda s: s.update(running=True) or True)
        callbacks = []
        def admitted(*args, **kwargs):
            callbacks.append(kwargs.get("terminal_callback"))
            return True  # real _run_prompt_submit starts a thread and returns before delivery
        monkeypatch.setattr(server, "_run_prompt_submit", admitted)
        notifications = [(event, format_process_notification(event))]
        server._notif_dispatch_completions("sid", session, notifications, registry, None)
        assert not delivered(registry, event)
        assert callable(callbacks[-1])
        callbacks[-1]({"status": "failed", "text": "", "error": "receiver rolled back"})
        assert not delivered(registry, event)
        assert registry.completion_queue.get_nowait() == event
        session["running"] = False
        server._notif_dispatch_completions("sid", session, notifications, registry, None)
        assert not delivered(registry, event)
        callbacks[-1]({"status": "settled", "text": "handled"})
        assert delivered(registry, event)
        assert registry.completion_queue.empty()
    finally:
        agent._session_db.close()
