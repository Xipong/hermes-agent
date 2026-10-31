"""A durable typed input is delivered even when its receiving model turn fails."""

import queue
import threading
from types import SimpleNamespace

import pytest
from httpx import Request, Response
from openai import BadRequestError

from tests.agent.test_notification_empty_recovery import (
    loop as loop,  # noqa: PLC0414 -- pytest fixture import must survive parameter shadowing (F811)
    response,
)
from tests.agent.test_process_completion_inject import _complete
from tests.hermes_cli.test_process_delivery_receipt import _CLI


@pytest.fixture(params=["cli", "tui"])
def receiver(loop, monkeypatch, request):
    from tools.process_registry import ProcessRegistry
    from tools.process_registry_notifications import format_process_notification
    from tui_gateway import server

    registry = ProcessRegistry()
    registry._completions_restored = True
    monkeypatch.setattr("tools.process_registry.process_registry", registry)
    agent = loop.agent
    history, results, payloads = [], [], []
    session = {"history_lock": threading.RLock(), "running": False, "agent": agent}
    cli = _CLI()
    cli._pending_input = queue.Queue()
    cli.session_id = "owner-a"
    monkeypatch.setattr("hermes_cli.gateway_tools_notify.gateway_store", lambda _: None)

    monkeypatch.setattr(server, "_get_usage", lambda _: {})
    monkeypatch.setattr(server, "render_message", lambda *a: None)

    def run(text):
        nonlocal history
        result = agent.run_conversation(
            str(text), conversation_history=history, persist_user_display_kind="process_complete")
        history = result["messages"]
        results.append(result)
        cli._last_turn_result = result
        return result

    def submit(_rid, _sid, session, text, **kwargs):
        # Only the thread boundary is synchronous: project the real result through the
        # production outcome/retained-failure/terminal-callback path, not a fake receipt.
        result = run(text)
        st = server._TurnRun(agent, None, kwargs["terminal_callback"], False)
        st.result, st.prompt_text = result, str(text)
        payload, _, _ = server._complete_turn_payload(session, st, None, 80)
        payloads.append(payload)
        session["running"] = False
        return True

    monkeypatch.setattr(server, "_run_prompt_submit", submit)

    def drain():
        if request.param == "cli":
            cli._drain_process_notifications("integration")
            while not cli._pending_input.empty():
                notice, _, _ = cli._tui_unwrap_input(cli._pending_input.get_nowait())
                if notice is not None:
                    cli._run_process_notification(notice, run)
        elif not registry.completion_queue.empty():
            events = [registry.completion_queue.get_nowait()
                      for _ in range(registry.completion_queue.qsize())]
            server._notif_dispatch_completions(
                "sid", session, [(e, format_process_notification(e)) for e in events], registry, None)

    return SimpleNamespace(agent=agent, db=loop.db, registry=registry, drain=drain, run=run, surface=request.param,
                           results=results, payloads=payloads, cli=cli, session=session)


def test_permanent_receiver_error_is_delivered_once_and_retained(receiver):
    from tools.process_completion_delivery import delivered

    r = receiver
    _complete(r.registry, "proc_rejected")
    event = r.registry.completion_queue.queue[0]
    r.agent.client.chat.completions.create.side_effect = BadRequestError(
        "permission denied", response=Response(400, request=Request("POST", "http://127.0.0.1:9/v1")), body=None)
    for _ in range(3):
        r.drain()
    assert r.agent.client.chat.completions.create.call_count == 1
    assert len(r.results) == 1
    result = r.results[0]
    assert result["failed"] is True and result["completed"] is False
    assert "permission denied" in result["error"]
    saved = r.db.get_messages_as_conversation(r.agent.session_id)
    assert sum(row["role"] == "user" and "OUTPUT proc_rejected" in row["content"] for row in saved) == 1
    assert saved[-1]["role"] == "assistant"
    assert "permission denied" in str(saved[-1].get("display_metadata"))
    assert delivered(r.registry, event)
    assert r.registry.completion_queue.empty()
    if r.payloads:
        assert r.payloads[0]["status"] == "error"
        assert "permission denied" in r.payloads[0]["error"]

    # Delivery failure is not a session-wide poison latch or suppression of later evidence.
    _complete(r.registry, "proc_later", code=7)
    r.agent.client.chat.completions.create.side_effect = [response("Correction: the later build failed.")]
    r.drain()
    assert r.results[-1]["final_response"] == "Correction: the later build failed."
    assert r.results[-1]["completed"] is True
    r.agent.client.chat.completions.create.side_effect = [response(), response("The failed input is retained.")]
    human = r.agent.run_conversation("Inspect the retained errors", conversation_history=r.results[-1]["messages"])
    assert human["final_response"] == "The failed input is retained."
    assert human["completed"] is True


@pytest.mark.parametrize("reasoning", [None, "Private thought, not an answer."])
def test_typed_empty_is_failed_summary_without_redelivery(receiver, reasoning):
    from tools.process_completion_delivery import delivered

    r = receiver
    _complete(r.registry, "proc_empty")
    event = r.registry.completion_queue.queue[0]
    r.agent.client.chat.completions.create.side_effect = lambda **kw: response(reasoning=reasoning)
    for _ in range(3):
        r.drain()
    assert len(r.results) == 1
    assert r.agent.client.chat.completions.create.call_count == 1
    result = r.results[0]
    assert result["failed"] is True
    assert result["completed"] is False
    assert result["failure_reason"] == "empty_response"
    assert "background notification" in result["error"].lower()
    assert delivered(r.registry, event) and r.registry.completion_queue.empty()
    saved = r.db.get_messages_as_conversation(r.agent.session_id)
    assert saved[-2]["display_kind"] == "process_complete"
    assert "OUTPUT proc_empty" in saved[-2]["content"]
    assert saved[-1]["content"] == result["error"]
    assert not reasoning or reasoning not in result["final_response"]
    if r.payloads:
        assert r.payloads[0]["status"] == "error"
        assert r.payloads[0]["error"] == result["error"]
        assert r.session["inflight_turn"]["status"] == "error"

    _complete(r.registry, "proc_correction", code=7)
    r.agent.client.chat.completions.create.side_effect = [response("Correction: the build failed.")]
    r.drain()
    assert r.results[-1]["completed"] is True
    assert r.results[-1]["final_response"] == "Correction: the build failed."
    r.agent.client.chat.completions.create.side_effect = [response(), response("Retained results inspected.")]
    human = r.agent.run_conversation("Inspect the results", conversation_history=r.results[-1]["messages"])
    assert human["final_response"] == "Retained results inspected."
    assert human["completed"] is True


@pytest.mark.parametrize("persistence", ["failed", "noop"])
def test_input_without_durable_persistence_keeps_delivery_pending(receiver, monkeypatch, persistence):
    from tools.process_completion_delivery import delivered

    r = receiver
    _complete(r.registry, "proc_uncommitted")
    event = r.registry.completion_queue.queue[0]
    real_flush = r.agent._flush_messages_to_session_db
    monkeypatch.setattr(r.agent, "_flush_messages_to_session_db",
                        lambda *a, **k: False if persistence == "failed" else None)
    r.agent.client.chat.completions.create.side_effect = lambda **kw: response("NO_REPLY")
    r.drain()
    assert not delivered(r.registry, event)
    assert list(r.registry.completion_queue.queue) == [event]
    assert not r.db.get_messages_as_conversation(r.agent.session_id)
    assert "input_delivery" not in r.results[-1]
    monkeypatch.setattr(r.agent, "_flush_messages_to_session_db", real_flush)
    r.drain()
    assert delivered(r.registry, event) and r.registry.completion_queue.empty()
    assert r.results[-1]["completed"] is True
    assert r.results[-1]["final_response"] == "NO_REPLY"


def test_identical_historical_input_cannot_receipt_a_rolled_back_turn(receiver, monkeypatch):
    from agent import conversation_loop
    from tools.process_registry_notifications import format_process_notification
    from tools.process_completion_delivery import delivered

    r = receiver
    _complete(r.registry, "proc_rolled_back")
    event = r.registry.completion_queue.queue[0]
    text = format_process_notification(event)
    r.agent.client.chat.completions.create.side_effect = lambda **kw: response("NO_REPLY")
    prior = r.run(text)
    assert prior["input_delivery"]["content"] == text
    assert not delivered(r.registry, event)
    real_turn = conversation_loop._run_conversation_turn
    prefix_length = len(prior["messages"])

    def rollback(*args, **kwargs):
        result = real_turn(*args, **kwargs)
        # Receiver rollback discards the new input from its canonical projection.
        # The retained prefix deliberately contains an identical typed durable row.
        result["messages"] = result["messages"][:prefix_length]
        return result

    monkeypatch.setattr(conversation_loop, "_run_conversation_turn", rollback)
    r.drain()
    assert r.results[-1]["completed"] is True  # generic summary success is not input proof
    assert "input_delivery" not in r.results[-1]
    assert not delivered(r.registry, event)
    assert list(r.registry.completion_queue.queue) == [event]


def test_stop_during_receiving_turn_requeues_and_holds_delivery(receiver):
    from tools.process_completion_delivery import delivered

    r = receiver
    _complete(r.registry, "proc_stopped")
    event = r.registry.completion_queue.queue[0]

    def stop(**kwargs):
        r.agent.interrupt()
        r.cli._last_turn_interrupted = True
        r.session["_turn_cancel_requested"] = True
        return response("NO_REPLY")

    r.agent.client.chat.completions.create.side_effect = stop
    r.drain()
    assert r.results[-1]["interrupted"] is True
    assert not delivered(r.registry, event)
    assert list(r.registry.completion_queue.queue) == [event]
    r.drain()
    assert len(r.results) == 1
    assert list(r.registry.completion_queue.queue) == [event]
    r.cli._last_turn_interrupted = False
    r.session["_turn_cancel_requested"] = False
    r.agent.client.chat.completions.create.side_effect = [response("NO_REPLY")]
    r.drain()
    assert delivered(r.registry, event) and r.registry.completion_queue.empty()
    assert r.results[-1]["completed"] is True


def test_exception_before_input_delivery_keeps_fallback(receiver, monkeypatch):
    from agent import conversation_loop
    from tools.process_completion_delivery import delivered

    r = receiver
    _complete(r.registry, "proc_not_admitted")
    event = r.registry.completion_queue.queue[0]

    def refuse(*args, **kwargs):
        raise RuntimeError("receiver failed before staging input")

    monkeypatch.setattr(conversation_loop, "_run_conversation_turn", refuse)
    if r.surface == "cli":
        with pytest.raises(RuntimeError, match="before staging input"):
            r.drain()
    else:
        r.drain()
    assert not delivered(r.registry, event)
    assert list(r.registry.completion_queue.queue) == [event]
    assert not r.db.get_messages_as_conversation(r.agent.session_id)
    assert not r.results


def test_receipt_requires_the_exact_current_typed_input(loop):
    from agent.notification_delivery import notification_input_committed

    loop.agent.client.chat.completions.create.side_effect = [response("NO_REPLY")]
    result = loop.agent.run_conversation("Retained completion", persist_user_display_kind="process_complete")
    assert notification_input_committed(result, "Retained completion", "process_complete")
    assert not notification_input_committed(result, "Another completion", "process_complete")
    assert not notification_input_committed(result, "Retained completion", "internal_notification")
    assert not notification_input_committed(dict(result, turn_id="another-turn"), "Retained completion", "process_complete")
    assert not notification_input_committed(dict(result, interrupted=True), "Retained completion", "process_complete")
    assert not notification_input_committed(dict(result, status="cancelled"), "Retained completion", "process_complete")
    assert not notification_input_committed({"completed": True}, "Retained completion", "process_complete")
