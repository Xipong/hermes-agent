"""Boundary regressions for the ready-set port onto extracted consumers."""

import threading

from tools import async_delegation as ad
from tools.process_registry import ProcessRegistry


def test_drain_formats_after_releasing_routing_reservation(monkeypatch):
    import tools.process_registry as pr
    registry = ProcessRegistry()
    event = {"type": "completion", "session_id": "sample"}
    registry.completion_queue.put(event)
    states = []

    def formatter(_event):
        def probe():
            acquired = registry.completion_routing_lock.acquire(timeout=0.1)
            states.append(acquired)
            if acquired:
                registry.completion_routing_lock.release()
        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(timeout=1)
        return "formatted"

    monkeypatch.setattr(pr, "format_process_notification", formatter)
    assert registry.drain_notifications() == [(event, "formatted")]
    assert states == [True]


def test_formatter_failure_requeues_without_claim(monkeypatch):
    import tools.process_registry as pr
    registry = ProcessRegistry()
    event = {"type": "async_delegation", "delegation_id": "sample", "session_key": "mine"}
    registry.completion_queue.put(event)
    claims = []
    monkeypatch.setattr(ad, "claim_event_delivery", lambda *_a: claims.append(True))

    def fail(_event):
        raise ValueError("formatter unavailable")

    monkeypatch.setattr(pr, "format_process_notification", fail)
    assert registry.drain_notifications(session_key="mine") == []
    assert registry.completion_queue.get_nowait() == event
    assert claims == []
