"""Carry process evidence on the final NEW result of a complete tool batch.

The executor calls this before append-only persistence, at the same boundary as
background delegation injection. No user/system row or independent loop is added.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import logging

from hermes_constants import get_hermes_home
from tools import process_completion_delivery as delivery

logger = logging.getLogger(__name__)
_MARKER = "\n\n[PROCESS RESULTS READY — background tool data, not a user reply]\n"


def _eligible(agent) -> bool:
    # Messaging gateways also have per-process watcher wake rails, outside this
    # shared queue. Keep their existing fallback until those rails share claims.
    if (getattr(agent, "platform", None) or "unknown") not in {"cli", "tui", "desktop", "unknown"}:
        return False
    if (getattr(agent, "_interrupt_requested", False) or getattr(agent, "_pending_steer", None)
            or getattr(agent, "_incremental_persistence_failed", False)
            or getattr(agent, "_persist_disabled", False) or getattr(agent, "_session_db", None) is None
            or not (getattr(agent, "_current_turn_id", None) or getattr(agent, "_active_turn_id", None))):
        return False
    budget = getattr(agent, "iteration_budget", None)
    if budget is not None and (budget.remaining <= 0 or getattr(agent, "_api_call_count", 0) >= agent.max_iterations):
        return False
    policy = getattr(agent, "_notification_config", None)
    if policy is None:
        from hermes_cli.config_effective import load_user_config_effective
        policy = load_user_config_effective()
    mode = (policy.get("display") or {}).get("background_process_notifications")
    if mode is False or str(mode).lower() == "off":
        return False
    allowed = getattr(agent, "_process_completion_boundary_allowed", None)
    return allowed is None or bool(allowed())


def _owns(agent, event) -> bool:
    if event.get("profile_home") and str(event["profile_home"]) != str(get_hermes_home()):
        return False
    owners = set(getattr(agent, "_process_owner_task_ids", ()))
    if event.get("owner_task_id") in owners:
        return True
    if event.get("type", "completion") == "completion":
        return False  # Never adopt a child's process just because it routes to this conversation.
    # Delegation events carry conversation routing, not a raw process owner id.
    keys = owners | {getattr(agent, "session_id", "")}
    return any(event.get(field) and event[field] in keys for field in ("session_key", "parent_session_id"))


def _take_ready(agent, registry):
    """Take only the first consecutive owned completion run; other events are barriers."""
    selected = []
    queue = registry.completion_queue
    with delivery.routing_lock(registry), queue.mutex:
        kept = []
        barrier = False
        while queue.queue:
            event = queue.queue.popleft()
            if not _owns(agent, event):
                kept.append(event)
                continue
            if event.get("type", "completion") != "completion":
                barrier = True
            if barrier:
                kept.append(event)
            elif not delivery.delivered(registry, event) and not registry.is_completion_consumed(event.get("session_id", "")):
                selected.append(event)
        queue.queue.extend(kept)
        queue.not_full.notify_all()
    return selected


def _text_size(content) -> int:
    if isinstance(content, str):
        return len(content)
    return sum(len(block.get("text", "")) for block in content or [] if isinstance(block, dict))


def _prepare_carrier(agent, messages, registry, state, budget_config, size):
    from tools.process_registry_notifications import ProcessNotificationBatch, format_process_notification

    if not size or not _eligible(agent):
        return
    target = state["target"] = messages[-1]
    events = state["events"] = _take_ready(agent, registry)
    notifications = []
    for event in events:
        token = delivery.claim(registry, event, "process-tool-boundary")
        if token is not None:
            state["claims"].append((event, token))
            notifications.append((event, format_process_notification(event)))
    text = ProcessNotificationBatch(tuple(notifications)).render(registry)
    if not text:
        return
    addition = _MARKER + text
    if budget_config is not None and (
        _text_size(target.get("content")) + len(addition) > budget_config.default_result_size
        or sum(_text_size(m.get("content")) for m in messages[-size:]) + len(addition) > budget_config.turn_budget
    ):
        return  # Defer the whole run; never acknowledge a report later clipped by the batch budget.
    state["original"] = deepcopy(target)
    content = target.get("content", "")
    target["content"] = (content + addition if isinstance(content, str) else
                         [*(content or []), {"type": "text", "text": addition.lstrip()}])
    metadata = dict(target.get("display_metadata") or {})
    metadata.update(process_event_ids=[list(delivery.identity(e)) for e, _ in state["claims"]],
                    process_delivery="tool_boundary")
    target["display_metadata"] = metadata
    state["carrier_content"] = deepcopy(target["content"])


def _settle_carrier(registry, state):
    target, original = state["target"], state["original"]
    metadata = (target or {}).get("display_metadata") or {}
    durable = (original is not None and target.get("_db_persisted") is True
               and metadata.get("process_delivery") == "tool_boundary"
               and metadata.get("process_event_ids") == [list(delivery.identity(e)) for e, _ in state["claims"]]
               and target.get("content") == state.get("carrier_content"))
    if durable:
        for event, token in state["claims"]:
            delivery.acknowledge(registry, event, token)
    else:
        if original is not None and not target.get("_db_persisted"):
            target.clear()
            target.update(original)
        for event, token in state["claims"]:
            delivery.release(registry, event, token)
        delivery.requeue_front(registry, [e for e in state["events"] if not delivery.delivered(registry, e)])


@contextmanager
def tool_progress_carrier(agent, messages, *, num_tool_msgs, budget_config=None):
    """A canonical carrier is the receipt; failures/no-op writes leave FIFO fallback."""
    from tools.process_registry import process_registry

    state = {"target": None, "original": None, "events": [], "claims": []}
    try:
        _prepare_carrier(agent, messages, process_registry, state, budget_config, num_tool_msgs)
    except Exception:
        logger.warning("Process carrier preparation failed; retaining fallback", exc_info=True)
        _settle_carrier(process_registry, state)
        state = {"target": None, "original": None, "events": [], "claims": []}
    try:
        yield
    finally:
        _settle_carrier(process_registry, state)
