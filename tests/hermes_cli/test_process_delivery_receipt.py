"""A queued CLI batch is not a delivery receipt (#134198, #104671)."""
import queue
from types import SimpleNamespace

import pytest

from hermes_cli.cli_process_notifications import CLIProcessNotificationsMixin
from tests.agent.test_process_completion_inject import _rig, _complete


class _CLI(CLIProcessNotificationsMixin):
    def _owns_process_notification(self, event):
        return event.get("session_key") == "owner-a"

    def _background_notifications_suppressed(self):
        return False


def test_cli_enqueued_batch_can_still_be_delivered_in_active_turn(tmp_path, monkeypatch):
    from tools.process_completion_delivery import delivered
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from tests.agent.test_process_completion_inject import _complete_messages
    cli = _CLI()
    cli._pending_input = queue.Queue()
    cli.session_id = "owner-a"
    monkeypatch.setattr("hermes_cli.gateway_tools_notify.gateway_store", lambda _: None)
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_queued")
        event = registry.completion_queue.queue[0]
        cli._drain_process_notifications("cli-idle")
        assert not delivered(registry, event)
        pending = cli._pending_input.get_nowait()
        # The queue entry retains identities, and is filtered if already delivered elsewhere.
        registry.completion_queue.put(event)
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="racing active turn")
        assert delivered(registry, event)
        text, _, _ = cli._tui_unwrap_input(pending)
        assert text is None
    finally:
        agent._session_db.close()


@pytest.mark.parametrize("accepted", [True, False])
def test_cli_batch_settles_only_after_actual_canonical_turn(tmp_path, monkeypatch, accepted):
    from tools.process_completion_delivery import delivered
    from tools.process_registry_notifications import TimelineNotification
    cli = _CLI()
    cli._pending_input = queue.Queue()
    cli.session_id = "owner-a"
    monkeypatch.setattr("hermes_cli.gateway_tools_notify.gateway_store", lambda _: None)
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        for ident in ["proc_cli_a", "proc_cli_b"]:
            _complete(registry, ident)
        events = list(registry.completion_queue.queue)
        cli._drain_process_notifications("cli-idle")
        notice, _, _ = cli._tui_unwrap_input(cli._pending_input.get_nowait())
        assert isinstance(notice, TimelineNotification)
        calls = []
        def run(text):
            calls.append(text)
            assert all(not delivered(registry, e) for e in events)
            cli._last_turn_result = ({"turn_id": "current", "input_delivery": {"turn_id": "current",
                                         "content": str(text), "display_kind": "process_complete"}}
                                     if accepted else {"messages": [], "failed": True})
        cli._run_process_notification(notice, run)
        assert len(calls) == 1
        assert all(delivered(registry, e) is accepted for e in events)
        if not accepted:
            assert list(registry.completion_queue.queue) == events
    finally:
        agent._session_db.close()


def test_stop_holds_queued_cli_completion_until_next_human_turn(tmp_path, monkeypatch):
    cli = _CLI()
    cli._pending_input = queue.Queue()
    cli.session_id = "owner-a"
    monkeypatch.setattr("hermes_cli.gateway_tools_notify.gateway_store", lambda _: None)
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_after_stop")
        event = registry.completion_queue.queue[0]
        cli._drain_process_notifications("cli-idle")
        notice, _, _ = cli._tui_unwrap_input(cli._pending_input.get_nowait())
        cli._last_turn_interrupted = True
        called = []
        cli._run_process_notification(notice, lambda text: called.append(text))
        assert not called
        assert list(registry.completion_queue.queue) == [event]
        cli._drain_process_notifications("cli-post-turn")
        assert cli._pending_input.empty()
        assert list(registry.completion_queue.queue) == [event]
        cli._last_turn_interrupted = False  # a genuine user turn clears the existing CLI latch
        cli._drain_process_notifications("cli-idle")
        assert cli._pending_input.qsize() == 1
    finally:
        agent._session_db.close()


def test_readonly_poll_does_not_discard_cli_fallback(tmp_path, monkeypatch):
    cli = _CLI()
    cli._pending_input = queue.Queue()
    cli.session_id = "owner-a"
    monkeypatch.setattr("hermes_cli.gateway_tools_notify.gateway_store", lambda _: None)
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_polled")
        assert registry.poll("proc_polled")["status"] == "exited"
        cli._drain_process_notifications("cli-post-turn")
        assert cli._pending_input.qsize() == 1
        assert "OUTPUT proc_polled" in cli._pending_input.get_nowait().render(registry)
    finally:
        agent._session_db.close()
