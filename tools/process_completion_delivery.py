"""Process completion claims shared by tool-boundary and ordinary turn delivery.

Unlike delegation's durable ledger, process notifications are an in-process queue.
Keep the terminal identity after dequeue: observing output is not acknowledgement.
"""
from __future__ import annotations

import threading
import uuid

from hermes_constants import get_hermes_home

# Also covers lightweight registries constructed with __new__ by embedders/tests.
_LOCK = threading.RLock()


def identity(event: dict) -> tuple:
    return (str(event.get("profile_home") or get_hermes_home()),
            str(event.get("session_id") or ""), event.get("started_at", 0))


def _states(registry):
    states = getattr(registry, "_completion_delivery_states", None)
    if states is None:
        states = registry._completion_delivery_states = {}
    return states


def claim(registry, event: dict, consumer: str) -> str | None:
    with _LOCK:
        key = identity(event)
        states = _states(registry)
        if key in states or registry.is_completion_consumed(event.get("session_id", "")):
            return None
        token = f"{consumer}:{uuid.uuid4().hex}"
        states[key] = token
        return token


def acknowledge(registry, event: dict, token: str) -> bool:
    with _LOCK:
        states = _states(registry)
        key = identity(event)
        if states.get(key) != token:
            return False
        states[key] = "delivered"
        return True


def release(registry, event: dict, token: str) -> bool:
    with _LOCK:
        states = _states(registry)
        key = identity(event)
        if states.get(key) != token:
            return False
        del states[key]
        return True


def delivered(registry, event: dict) -> bool:
    with _LOCK:
        return _states(registry).get(identity(event)) == "delivered"


def routing_lock(registry):
    """Use the reservation shared with delegation injection when installed."""
    return getattr(registry, "completion_routing_lock", _LOCK)


def requeue_front(registry, events) -> None:
    """Restore a failed snapshot ahead of newer events, in original order."""
    events = list(events)
    if not events:
        return
    with routing_lock(registry), registry.completion_queue.not_empty:
        for event in reversed(events):
            registry.completion_queue.queue.appendleft(event)
        registry.completion_queue.not_empty.notify_all()
