"""Safe-boundary scheduling does not steal human input or another owner's evidence."""
from copy import deepcopy
from types import SimpleNamespace
import threading

import pytest

from tests.agent.test_process_completion_inject import _rig, _complete, _complete_messages


@pytest.mark.parametrize("blocked", ["stop", "steer", "human", "budget", "off", "disabled", "gateway"])
def test_control_priority_keeps_process_result_for_fallback(tmp_path, monkeypatch, blocked):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_pending")
        attr, value = {
            "stop": ("_interrupt_requested", True),
            "steer": ("_pending_steer", "user steering"),
            "human": ("_process_completion_boundary_allowed", lambda: False),
            "budget": ("iteration_budget", SimpleNamespace(remaining=0)),
            "off": ("_notification_config", {"display": {"background_process_notifications": "off"}}),
            "disabled": ("_persist_disabled", True),
            "gateway": ("platform", "telegram"),
        }[blocked]
        setattr(agent, attr, value)
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage=blocked)
        assert messages[-1]["content"] == "second"
        assert registry.completion_queue.qsize() == 1
    finally:
        agent._session_db.close()


@pytest.mark.parametrize("barrier_identity", ["owner_task_id", "session_key"])
def test_foreign_profile_and_event_barrier_preserve_order(tmp_path, monkeypatch, barrier_identity):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_before")
        registry.completion_queue.put({"type": "async_delegation", barrier_identity: "owner-a", "delegation_id": "barrier"})
        _complete(registry, "proc_after")
        _complete(registry, "proc_foreign", owner="other-owner")
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="ordered")
        assert "OUTPUT proc_before" in messages[-1]["content"]
        assert "proc_after" not in messages[-1]["content"]
        assert [e.get("session_id", e.get("delegation_id")) for e in registry.completion_queue.queue] == ["barrier", "proc_after", "proc_foreign"]
        assert messages[-1]["display_metadata"]["process_delivery"] == "tool_boundary"
    finally:
        agent._session_db.close()


def test_producer_profile_identity_cannot_be_injected_by_same_owner_in_other_home(tmp_path, monkeypatch):
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    other = tmp_path / "other-profile"
    other.mkdir()
    token = set_hermes_home_override(other)
    try:
        _complete(registry, "proc_other_home")
    finally:
        reset_hermes_home_override(token)
    try:
        from tui_gateway import server
        from hermes_constants import get_hermes_home
        event = registry.completion_queue.queue[0]
        session = {"session_key": "owner-a", "profile_home": str(get_hermes_home())}
        assert not server._session_owns_notification_event("sid", session, event)
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="foreign profile")
        assert "proc_other_home" not in str(messages)
        assert registry.completion_queue.qsize() == 1
    finally:
        agent._session_db.close()


@pytest.mark.parametrize("control", ["queued_prompt", "clarify", "_turn_cancel_requested", "_finalized"])
def test_surface_control_latch_blocks_carrier_before_poller_start(tmp_path, monkeypatch, control):
    from tui_gateway import server
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    session = {"agent": agent, "running": True, "session_key": "owner-a", "history_lock": threading.RLock()}
    if control != "clarify":
        session[control] = "human input" if control == "queued_prompt" else True
    requests = [{"id": "pending-clarify", "method": "clarify"}] if control == "clarify" else []
    monkeypatch.setattr(server, "_sessions", {"sid": session})
    monkeypatch.setattr(server, "_open_requests", lambda sid: requests)
    agent._process_completion_boundary_allowed = lambda: server._notif_bound_process_boundary_allowed("sid")
    try:
        _complete(registry, "proc_human_priority")
        before = deepcopy(requests)
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="pending human control")
        assert messages[-1]["content"] == "second"
        assert registry.completion_queue.qsize() == 1
        assert requests == before
        if control == "queued_prompt":
            assert session[control] == "human input"
    finally:
        agent._session_db.close()


@pytest.mark.parametrize("with_barrier", [False, True])
def test_poller_snapshot_does_not_hide_busy_owners_ready_batch(tmp_path, monkeypatch, with_barrier):
    from tui_gateway import server
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    session = {"agent": agent, "running": True, "session_key": "owner-a", "history_lock": threading.RLock()}
    monkeypatch.setattr(server, "_sessions", {"sid": session})
    try:
        _complete(registry, "proc_poller_a")
        if with_barrier:
            registry.completion_queue.put({"type": "watch_match", "owner_task_id": "owner-a", "session_id": "proc_watch"})
        _complete(registry, "proc_poller_b")
        # This is the same dequeue seam the real poller uses, held before routing/UI callbacks.
        _ready, actions = server._notif_drain_ready("sid", session, registry)
        assert actions == ["busy"] * (3 if with_barrier else 2)
        assert registry.completion_queue.qsize() == (3 if with_barrier else 2)
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="during poller")
        assert "OUTPUT proc_poller_a" in messages[-1]["content"]
        assert ("OUTPUT proc_poller_b" in messages[-1]["content"]) is not with_barrier
    finally:
        agent._session_db.close()
