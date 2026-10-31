"""Process evidence reaches the next complete tool batch without a new user turn (#134198)."""
from copy import deepcopy

import threading
from types import SimpleNamespace

import pytest


def _rig(tmp_path, monkeypatch):
    from hermes_state import SessionDB
    from run_agent import AIAgent
    from tools.process_registry import ProcessRegistry

    registry = ProcessRegistry()
    registry._completions_restored = True
    monkeypatch.setattr("tools.process_registry.process_registry", registry)
    agent = AIAgent(session_db=SessionDB(db_path=tmp_path / "state.db"),
                    model="test-model", provider="openai-compat", api_key="test",
                    base_url="http://127.0.0.1:1/v1", max_iterations=4,
                    quiet_mode=True, skip_context_files=True, skip_memory=True)
    agent._active_turn_id = "turn-a"
    agent._process_owner_task_ids = {"owner-a"}
    return agent, registry


def _complete(registry, ident, *, code=0, owner="owner-a"):
    from tools.process_registry import ProcessSession
    session = ProcessSession(id=ident, command=f"run {ident}", owner_task_id=owner,
                             session_key="owner-a", started_at=123,
                             notify_on_complete=True, output_buffer=f"OUTPUT {ident}")
    registry._running[ident] = session
    registry._finish_exited(session, code)
    return session


def _messages():
    return [{"role": "user", "content": "continue foreground work"},
            {"role": "assistant", "tool_calls": [
                {"id": ident, "type": "function", "function": {"name": "read_file", "arguments": "{}"}}
                for ident in ("call_a", "call_b")]},
            {"role": "tool", "name": "read_file", "tool_call_id": "call_a", "content": "first"}]


@pytest.mark.parametrize("poll_before_boundary", [False, True])
def test_two_ready_processes_share_last_new_tool_result_and_do_not_replay(tmp_path, monkeypatch, poll_before_boundary):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from tools.process_registry_notifications import format_process_notification
    from tui_gateway import server

    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_success")
        _complete(registry, "proc_failure", code=7)
        if poll_before_boundary:
            assert registry.poll("proc_success")["exit_code"] == 0
            assert registry.poll("proc_failure")["exit_code"] == 7
        messages = _messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="partial batch")
        prefix = deepcopy(messages)
        assert "OUTPUT" not in str(messages)
        messages.append({"role": "tool", "name": "read_file", "tool_call_id": "call_b", "content": "second"})
        assert _flush_session_db_after_tool_progress(agent, messages, stage="complete batch")
        assert messages[:-1] == prefix
        assert messages[-1]["content"].count("OUTPUT proc_success") == 1
        assert messages[-1]["content"].count("OUTPUT proc_failure") == 1
        assert "exit code 7" in messages[-1]["content"]
        assert len(messages) == 4
        assert registry.completion_queue.empty()
        stored = agent._session_db.get_messages(agent.session_id)
        assert stored[-1]["content"] == messages[-1]["content"]
        # A stale poller snapshot must not replay either completion after the carrier commits.
        dispatched = []
        monkeypatch.setattr(server, "_notif_claim_turn", lambda session: True)
        monkeypatch.setattr(server, "_notif_submit", lambda *a, **kw: dispatched.append(a) or True)
        session = {"running": False, "history_lock": threading.RLock()}
        events = [{"type": "completion", "session_id": ident, "session_key": "owner-a",
                   "owner_task_id": "owner-a", "started_at": 123, "exit_code": code,
                   "output": f"OUTPUT {ident}"} for ident, code in [("proc_success", 0), ("proc_failure", 7)]]
        server._notif_dispatch_completions("sid", session, [(e, format_process_notification(e)) for e in events], registry, [])
        assert not dispatched
    finally:
        agent._session_db.close()


@pytest.mark.parametrize("ready_phase", ["tools", "final_race", "no_boundary"])
def test_real_turn_next_provider_request_sees_one_process_batch(tmp_path, monkeypatch, ready_phase):
    from tests.agent.test_run_agent import _mock_assistant_msg
    agent, registry = _rig(tmp_path, monkeypatch)
    del agent._active_turn_id  # Normal main uses _current_turn_id; no fixture-only activation.
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent._cached_system_prompt = "FIXED SYSTEM PREFIX"
    requests = []
    calls = [SimpleNamespace(id=f"read_{i}", type="function",
        function=SimpleNamespace(name="read_file", arguments=f'{{"path":"file_{i}"}}')) for i in range(2)]
    def response(message, reason):
        return SimpleNamespace(id="response", model="test-model", usage=None,
            choices=[SimpleNamespace(index=0, message=message, finish_reason=reason)])
    final = response(_mock_assistant_msg(content="Handled both process results."), "stop")
    responses = iter([final] if ready_phase == "no_boundary" else
                     [response(_mock_assistant_msg(content="", tool_calls=calls), "tool_calls"), final])
    def finish_processes():
        _complete(registry, "proc_live_a", owner="live-task")
        _complete(registry, "proc_live_b", code=2, owner="live-task")
    def create(**kwargs):
        requests.append(deepcopy(kwargs))
        if ready_phase == "no_boundary" or (ready_phase == "final_race" and len(requests) == 2):
            finish_processes()
        return next(responses)
    agent.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: None)
    monkeypatch.setattr(agent, "_create_request_openai_client", lambda **kw: agent.client)
    monkeypatch.setattr("agent.title_generator.maybe_auto_title", lambda *a, **kw: None)
    monkeypatch.setattr("agent.title_generator.start_title_upgrade", lambda *a, **kw: None)
    def foreground(*args, **kwargs):
        if ready_phase == "tools" and not registry._finished:
            finish_processes()
        return "foreground output"
    monkeypatch.setattr("model_tools.handle_function_call", foreground)
    try:
        result = agent.run_conversation("continue work", task_id="live-task")
        assert result["completed"], result
        assert len(requests) == (1 if ready_phase == "no_boundary" else 2)
        model_messages = requests[-1]["messages"]
        for ident in ["proc_live_a", "proc_live_b"]:
            assert str(model_messages).count(f"OUTPUT {ident}") == (1 if ready_phase == "tools" else 0)
        assert [m for m in model_messages if m["role"] == "user"] == [{"role": "user", "content": "continue work"}]
        assert model_messages[0] == requests[0]["messages"][0]
        if ready_phase == "tools":
            assert registry.completion_queue.empty()
        else:
            events = [registry.completion_queue.get_nowait() for _ in range(2)]
            dispatched = []
            _fallback(monkeypatch, registry, events, lambda *a, **kw: dispatched.append(a[3]) or True)
            assert len(dispatched) == 1
            assert "OUTPUT proc_live_a" in dispatched[0] and "OUTPUT proc_live_b" in dispatched[0]
    finally:
        agent._session_db.close()


def _complete_messages():
    messages = _messages()
    messages.append({"role": "tool", "name": "read_file", "tool_call_id": "call_b", "content": "second"})
    return messages


def _fallback(monkeypatch, registry, events, submit):
    from tui_gateway import server
    from tools.process_registry_notifications import format_process_notification
    monkeypatch.setattr(server, "_notif_claim_turn", lambda session: True)
    def deliver(*args, **kwargs):
        accepted = submit(*args, **kwargs)
        if accepted and kwargs.get("terminal_callback"):
            kwargs["terminal_callback"]({"status": "settled", "text": "handled"})
        return accepted
    monkeypatch.setattr(server, "_notif_submit", deliver)
    session = {"history_lock": threading.RLock()}
    server._notif_dispatch_completions("sid", session,
        [(e, format_process_notification(e)) for e in events], registry, [])


@pytest.mark.parametrize("failure", [False, None, "raise"])
def test_failed_or_noop_carrier_rolls_back_then_fallback_delivers_once(tmp_path, monkeypatch, failure):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    from tools.process_completion_delivery import delivered
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_retry")
        _complete(registry, "proc_retry_b", code=3)
        messages = _complete_messages()
        original = deepcopy(messages)
        def fail(*a):
            if failure == "raise":
                raise OSError("disk full")
            return failure
        monkeypatch.setattr(agent, "_flush_messages_to_session_db", fail)
        assert _flush_session_db_after_tool_progress(agent, messages, stage="failed carrier") is (failure is None)
        assert [{k: v for k, v in row.items() if k != "_external_input_boundary_checked"}
                for row in messages] == original
        events = list(registry.completion_queue.queue)
        assert [e["session_id"] for e in events] == ["proc_retry", "proc_retry_b"]
        assert all(not delivered(registry, e) for e in events)
        registry.completion_queue.queue.clear()
        submitted = []
        _fallback(monkeypatch, registry, events, lambda *a, **kw: submitted.append(a[3]) or True)
        assert len(submitted) == 1
        assert all(delivered(registry, e) for e in events)
        _fallback(monkeypatch, registry, events, lambda *a, **kw: submitted.append(a[3]) or True)
        assert len(submitted) == 1
    finally:
        agent._session_db.close()


def test_formatter_failure_defers_notification_not_foreground_tool_result(tmp_path, monkeypatch):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_format_retry")
        def fail(event):
            raise ValueError("formatter failed")
        monkeypatch.setattr("tools.process_registry_notifications.format_process_notification", fail)
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="formatter failure")
        assert messages[-1]["content"] == "second"
        assert messages[-1]["_db_persisted"]
        assert registry.completion_queue.qsize() == 1
    finally:
        agent._session_db.close()


def test_carrier_over_budget_retains_whole_ready_batch_for_fallback(tmp_path, monkeypatch):
    from agent.tool_executor import _flush_session_db_after_tool_progress
    agent, registry = _rig(tmp_path, monkeypatch)
    try:
        _complete(registry, "proc_large")
        monkeypatch.setattr("agent.tool_executor._budget_for_agent", lambda _: SimpleNamespace(default_result_size=32, turn_budget=64))
        messages = _complete_messages()
        assert _flush_session_db_after_tool_progress(agent, messages, stage="small context")
        assert messages[-1]["content"] == "second"
        assert registry.completion_queue.qsize() == 1
    finally:
        agent._session_db.close()
