"""Process/delegation no-news policy through real recovery, persistence and gateway egress."""

import time
from types import SimpleNamespace

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.run import GatewayRunner
from gateway.run_notifications import _mark_internal_notification
from gateway.session import SessionSource
from tests.agent.test_notification_empty_recovery import (
    loop as loop,  # noqa: PLC0414 -- pytest fixture import must survive parameter shadowing (F811)
    response,
)
from tools.process_registry_notifications import format_process_notification


def envelope(family, batch):
    if family == "process":
        if batch:
            return GatewayRunner._format_coalesced_process_completions([
                ("one", {"session_id": "one", "command": "build", "output": "build result", "exit_code": 0}, None),
                ("two", {"session_id": "two", "command": "test", "output": "test result", "exit_code": 0}, None),
            ])
        return format_process_notification({
            "session_id": "one", "command": "build", "output": "build result", "exit_code": 0,
        })
    event = {
        "type": "async_delegation", "delegation_id": "delegation-one", "is_batch": batch,
        "goal": "Review deployment", "summary": "review result", "status": "completed",
    }
    if batch:
        event.update(results=[{"task_index": 0, "status": "completed", "summary": "review result"}],
                     goals=["Review deployment"])
    return format_process_notification(event)


@pytest.mark.asyncio
@pytest.mark.parametrize("family", ["process", "delegation"])
@pytest.mark.parametrize("batch", [False, True])
async def test_completion_no_news_and_failure_outcomes_reach_egress(loop, family, batch):
    payload = _mark_internal_notification(envelope(family, batch))
    assert _mark_internal_notification(payload) == payload
    runner = GatewayRunner(GatewayConfig())
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm")
    agent = loop.agent
    for reply in [response("NO_REPLY"), response(), response(reasoning="Private deliberation"),
                  response("Correction: deployment needs approval."), response("Build failed: permission denied.")]:
        agent.client.chat.completions.create.side_effect = lambda **kw: reply
        agent.client.chat.completions.create.reset_mock()
        result = agent.run_conversation(payload, persist_user_display_kind="internal_notification")
        wire = agent.client.chat.completions.create.call_args.kwargs["messages"]
        assert "NO_REPLY" in wire[-1]["content"]
        assert "failure" in wire[-1]["content"].lower()
        assert "NO_REPLY" not in wire[0]["content"]
        shaped, silent, messages = await runner._hmwa_shape_agent_response(
            result, source, [], SimpleNamespace(session_id=agent.session_id), None,
            None, 1, agent.session_id, "telegram", time.time(), "internal_notification",
        )
        assert agent.client.chat.completions.create.call_count == 1
        assert any(m.get("content") == payload for m in messages)
        if reply.choices[0].message.content == "NO_REPLY":
            assert silent
        else:
            assert not silent and shaped
        if not reply.choices[0].message.content:
            assert result["turn_exit_reason"] == "empty_response_exhausted"
            assert "background notification" in shaped.lower()
            assert "retained" in shaped.lower()
            assert "Send `continue`" not in shaped
        if reply.choices[0].message.content.startswith(("Correction", "Build failed")):
            assert shaped == reply.choices[0].message.content


@pytest.mark.asyncio
async def test_human_after_notification_cannot_inherit_silence_permission(loop):
    runner = GatewayRunner(GatewayConfig())
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm")
    agent = loop.agent
    agent.client.chat.completions.create.side_effect = [response("NO_REPLY")]
    notice = agent.run_conversation("Internal result", persist_user_display_kind="internal_notification")
    agent.client.chat.completions.create.side_effect = [response("NO_REPLY")]
    human = agent.run_conversation("Explain the result", conversation_history=notice["messages"])
    wire = agent.client.chat.completions.create.call_args.kwargs["messages"]
    assert "INTERNAL NOTIFICATION REPLY POLICY" not in wire[-1]["content"]
    shaped, silent, _ = await runner._hmwa_shape_agent_response(
        human, source, notice["messages"], SimpleNamespace(session_id=agent.session_id), None,
        None, 1, agent.session_id, "telegram", time.time(), None,
    )
    assert not silent and shaped and shaped != "NO_REPLY"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", [None, "internal_notification"])
async def test_actual_provider_error_is_never_notification_silence(loop, kind):
    from httpx import Request, Response
    from openai import BadRequestError

    agent = loop.agent
    error = BadRequestError(
        "permission denied", response=Response(400, request=Request("POST", "http://127.0.0.1:9/v1")), body=None,
    )
    agent.client.chat.completions.create.side_effect = error
    result = agent.run_conversation("Inspect result", persist_user_display_kind=kind)
    runner = GatewayRunner(GatewayConfig())
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="123", chat_type="dm")
    shaped, silent, _ = await runner._hmwa_shape_agent_response(
        result, source, [], SimpleNamespace(session_id=agent.session_id), None,
        None, 1, agent.session_id, "telegram", time.time(), kind,
    )
    assert not silent and "permission denied" in shaped.lower()
    assert result["failed"] is True
    assert agent._empty_content_retries == 0
