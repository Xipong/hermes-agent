"""Typed completion tails must not multiply empty-reply recovery calls (#135816)."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from hermes_state import SessionDB
from run_agent import AIAgent


@pytest.fixture
def loop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent.title_generator.maybe_auto_title", lambda *a, **k: None)
    monkeypatch.setattr("agent.title_generator.start_title_upgrade", lambda *a, **k: None)
    monkeypatch.setattr("agent.retry_utils.jittered_backoff", lambda *a, **k: 0)
    db = SessionDB(db_path=tmp_path / "state.db")
    with patch("agent.process_bootstrap.OpenAI"), patch("agent.model_metadata.fetch_model_metadata", return_value={}):
        agent = AIAgent(
            api_key="test-key", base_url="http://127.0.0.1:9/v1", model="test/model",
            quiet_mode=True, skip_context_files=True, skip_memory=True,
            enabled_toolsets=[], session_db=db, session_id="notification-tail",
        )
    agent._cached_system_prompt = "Stable system prompt."
    agent._use_prompt_caching = False
    agent.compression_enabled = False
    agent.save_trajectories = False
    agent.client = MagicMock()
    yield SimpleNamespace(agent=agent, db=db)
    db.close()


def response(content="", reasoning=None):
    return SimpleNamespace(
        id="scripted", model="test/model", usage=None,
        choices=[SimpleNamespace(index=0, finish_reason="stop", message=SimpleNamespace(
            content=content, reasoning=reasoning, tool_calls=None,
        ))],
    )


@pytest.mark.parametrize("kind", ["internal_notification", "process_complete", "async_delegation_complete"])
@pytest.mark.parametrize("reasoning", [None, "The notification needs examination."])
def test_notification_empty_is_failure_without_paid_recovery(loop, kind, reasoning):
    agent = loop.agent
    agent.client.chat.completions.create.side_effect = lambda **kw: response(reasoning=reasoning)
    agent._fallback_chain = [{"provider": "test", "model": "unused"}]
    agent._try_activate_fallback = MagicMock(return_value=False)
    result = agent.run_conversation("Important result to retain", persist_user_display_kind=kind)

    assert agent.client.chat.completions.create.call_count == 1
    assert result["turn_exit_reason"] == "notification_empty_response"
    assert result["final_response"] and result["final_response"] != "NO_REPLY"
    assert result["failed"] is True and result["completed"] is False
    assert result["error"] == result["final_response"]
    assert result["failure_reason"] == "empty_response"
    agent._try_activate_fallback.assert_not_called()
    assert agent._empty_content_retries == 0
    assert agent._thinking_prefill_retries == 0
    saved = loop.db.get_messages_as_conversation(agent.session_id)
    assert saved[-2]["content"] == "Important result to retain"
    assert saved[-2]["display_kind"] == kind
    assert saved[-1]["content"] == result["final_response"]
    assert "background notification" in saved[-1]["content"].lower()
    assert "The notification needs examination." not in result["final_response"]
    assert not any(m.get("_empty_recovery_synthetic") for m in result["messages"])
    assert agent._cached_system_prompt == "Stable system prompt."


def test_transport_retry_is_not_an_empty_reply_retry(loop):
    from httpx import Request
    from openai import APIConnectionError

    agent = loop.agent
    agent.client.chat.completions.create.side_effect = [
        APIConnectionError(request=Request("POST", "http://127.0.0.1:9/v1")), response(),
    ]
    result = agent.run_conversation("Retain after transient network failure", persist_user_display_kind="internal_notification")
    assert agent.client.chat.completions.create.call_count == 2
    assert result["turn_exit_reason"] == "notification_empty_response"
    assert agent._empty_content_retries == 0
    assert any(m.get("content") == "Retain after transient network failure" for m in result["messages"])


@pytest.mark.parametrize("prompt", ["Human instruction", "[INTERNAL NOTIFICATION] This is still human input"])
def test_notification_looking_human_text_keeps_recovery_and_has_no_policy_note(loop, prompt):
    agent = loop.agent
    agent.client.chat.completions.create.side_effect = [response(), response("Recovered answer.")]
    result = agent.run_conversation(prompt)
    assert agent.client.chat.completions.create.call_count == 2
    assert result["final_response"] == "Recovered answer."
    wire = agent.client.chat.completions.create.call_args.kwargs["messages"]
    assert "INTERNAL NOTIFICATION REPLY POLICY" not in wire[-1]["content"]


def test_mixed_tail_budget_is_cumulative_but_later_results_and_human_recovery_survive(loop):
    agent = loop.agent
    history = []
    agent.client.chat.completions.create.side_effect = lambda **kw: response()
    for index, kind in enumerate([
        "process_complete", "async_delegation_complete", "internal_notification",
        "process_complete", "async_delegation_complete", "internal_notification",
    ]):
        result = agent.run_conversation(
            f"Deferred result {index}", conversation_history=history, persist_user_display_kind=kind,
        )
        history = result["messages"]
    assert agent.client.chat.completions.create.call_count == 6
    assert all(any(m.get("content") == f"Deferred result {i}" for m in history) for i in range(6))

    agent.client.chat.completions.create.side_effect = [response("Correction: deployment failed.")]
    changed = agent.run_conversation(
        "A later useful result", conversation_history=history, persist_user_display_kind="process_complete",
    )
    assert changed["final_response"] == "Correction: deployment failed."

    agent.client.chat.completions.create.side_effect = [response(), response("Recovered for the human.")]
    human = agent.run_conversation("Inspect the retained results", conversation_history=changed["messages"])
    assert human["final_response"] == "Recovered for the human."
    wire = agent.client.chat.completions.create.call_args.kwargs["messages"]
    assert wire[-1]["content"] == "Inspect the retained results"
    assert wire[-1].get("display_kind") is None
