from pathlib import Path


# 1) Current centralized classifier: add a dedicated, narrow reason and
# classify the exact ChatGPT Codex invalid_prompt envelope before HTTP 400
# falls into generic format_error.
p = Path("agent/error_classifier.py")
text = p.read_text()
enum_old = '    invalid_encrypted_content = "invalid_encrypted_content"  # Responses replay blob rejected — strip replay state and retry\n'
enum_new = enum_old + '    codex_reasoning_replay_rejected = "codex_reasoning_replay_rejected"  # ChatGPT Codex masked a replay rejection as invalid_prompt\n'
if enum_old not in text:
    raise SystemExit("FailoverReason replay enum insertion point changed")
text = text.replace(enum_old, enum_new, 1)

marker = "    # Anthropic thinking-block 400s (signature mismatch after transcript\n"
if marker not in text:
    raise SystemExit("provider-special-case insertion point changed")
codex_case = '''    # ChatGPT Codex OAuth can mask a rejected encrypted-reasoning replay behind
    # ``invalid_prompt: Request blocked.``. Keep this signature intentionally narrow:
    # provider + structured code + exact body shape + status None/400. Recovery is
    # still gated on cached codex_reasoning_items in turn_recovery.py.
    if c.provider_slug == "openai-codex" and c.code == "invalid_prompt":
        err_obj = _error_obj(c.body)
        if not err_obj and isinstance(c.body, dict):
            err_obj = c.body
        codex_message = str(err_obj.get("message") or "").strip().lower()
        matches_masked_replay = (
            c.status_code in {None, 400}
            and codex_message == "request blocked."
            and err_obj.get("type") == "invalid_request_error"
            and "param" in err_obj
            and err_obj.get("param") is None
        )
        if matches_masked_replay:
            return _v(_R.codex_reasoning_replay_rejected, retryable=False, should_fallback=False)
        logger.debug(
            "OpenAI Codex invalid_prompt did not match the masked replay signature: "
            "status=%r message=%r type=%r param_present=%s param_is_null=%s",
            c.status_code, codex_message[:160], err_obj.get("type"),
            "param" in err_obj, err_obj.get("param") is None,
        )
'''
text = text.replace(marker, codex_case + marker, 1)
p.write_text(text)


# 2) Recovery moved from conversation_loop.py to turn_recovery.py. Extend
# the existing one-shot replay-strip branch rather than duplicating it.
p = Path("agent/turn_recovery.py")
text = p.read_text()
old_reason = "        classified.reason == FailoverReason.invalid_encrypted_content\n"
new_reason = '''        classified.reason in {
            FailoverReason.invalid_encrypted_content,
            FailoverReason.codex_reasoning_replay_rejected,
        }
'''
if old_reason not in text:
    raise SystemExit("encrypted replay recovery condition changed")
text = text.replace(old_reason, new_reason, 1)
replay_return = '''        return True

    # Structured 400 naming ``context_management``: disable native compaction for the
'''
replay_noop = '''        return True

    if (
        classified.reason == FailoverReason.codex_reasoning_replay_rejected
        and not _retry.invalid_encrypted_content_retry_attempted
        and agent.api_mode == "codex_responses"
        and bool(getattr(agent, "_codex_reasoning_replay_enabled", True))
    ):
        logger.debug(
            "%sCodex masked replay rejection matched, but no cached "
            "codex_reasoning_items were present; replay-strip recovery is a no-op",
            agent.log_prefix,
        )

    # Structured 400 naming ``context_management``: disable native compaction for the
'''
if replay_return not in text:
    raise SystemExit("encrypted replay recovery tail changed")
p.write_text(text.replace(replay_return, replay_noop, 1))


# 3) Port classifier regression coverage to the current test file.
p = Path("tests/agent/test_error_classifier.py")
text = p.read_text()
expected_old = '            "invalid_encrypted_content",\n            "multimodal_tool_content_unsupported",\n'
expected_new = '            "invalid_encrypted_content",\n            "codex_reasoning_replay_rejected",\n            "multimodal_tool_content_unsupported",\n'
if expected_old not in text:
    raise SystemExit("enum expected-set shape changed")
text = text.replace(expected_old, expected_new, 1)
classifier_tests = r'''


def test_openai_codex_masked_invalid_prompt_is_replay_rejection_candidate():
    e = MockAPIError(
        "Error code: 400 - Request blocked.",
        status_code=400,
        body={"error": {
            "message": "Request blocked.",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_prompt",
        }},
    )
    result = classify_api_error(e, provider="openai-codex", model="gpt-5.6-terra")
    assert result.reason == FailoverReason.codex_reasoning_replay_rejected
    assert result.retryable is False
    assert result.should_fallback is False


def test_openai_codex_direct_statusless_invalid_prompt_is_replay_rejection_candidate():
    e = MockAPIError(
        "Request blocked.",
        body={
            "message": "Request blocked.",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_prompt",
        },
    )
    result = classify_api_error(e, provider="openai-codex", model="gpt-5.6-terra")
    assert result.reason == FailoverReason.codex_reasoning_replay_rejected


def test_openai_codex_masked_invalid_prompt_near_miss_stays_format_error(caplog):
    e = MockAPIError(
        "Error code: 400 - Request blocked",
        status_code=400,
        body={"error": {
            "message": "Request blocked",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_prompt",
        }},
    )
    with caplog.at_level("DEBUG", logger="agent.error_classifier"):
        result = classify_api_error(e, provider="openai-codex", model="gpt-5.6-terra")
    assert result.reason == FailoverReason.format_error
    assert "did not match the masked replay signature" in caplog.text


def test_masked_invalid_prompt_other_provider_stays_format_error():
    e = MockAPIError(
        "Error code: 400 - Request blocked.",
        status_code=400,
        body={"error": {
            "message": "Request blocked.",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_prompt",
        }},
    )
    result = classify_api_error(e, provider="openai", model="gpt-5.6-terra")
    assert result.reason == FailoverReason.format_error
'''
p.write_text(text + classifier_tests)


# 4) Preserve one end-to-end Codex regression using the live SDK error shape.
p = Path("tests/run_agent/test_run_agent_codex_responses.py")
text = p.read_text()
import_old = "from types import SimpleNamespace\n\nimport pytest\n"
import_new = "from types import SimpleNamespace\n\nimport httpx\nimport pytest\nfrom openai import APIError as OpenAIAPIError\n"
if import_old not in text:
    raise SystemExit("Codex test import block changed")
text = text.replace(import_old, import_new, 1)
integration = r'''


def test_openai_codex_masked_replay_rejection_strips_reasoning_and_retries(monkeypatch):
    agent = _build_agent(monkeypatch)
    agent.provider = "openai-codex"
    agent.base_url = "https://chatgpt.com/backend-api/codex"
    request_payloads = []

    live_error = OpenAIAPIError(
        message="Request blocked.",
        request=httpx.Request("POST", "https://chatgpt.com/backend-api/codex/responses"),
        body={
            "message": "Request blocked.",
            "type": "invalid_request_error",
            "param": None,
            "code": "invalid_prompt",
        },
    )
    assert not hasattr(live_error, "status_code")
    responses = [live_error, _codex_message_response("Recovered without replay.")]

    def _fake_api_call(api_kwargs):
        request_payloads.append(api_kwargs)
        current = responses.pop(0)
        if isinstance(current, Exception):
            raise current
        return current

    monkeypatch.setattr(agent, "_interruptible_api_call", _fake_api_call)
    history = [{
        "role": "assistant",
        "content": "",
        "finish_reason": "incomplete",
        "codex_reasoning_items": [
            {"type": "reasoning", "id": "rs_001", "encrypted_content": "enc_bad", "summary": []},
        ],
    }]

    result = agent.run_conversation("continue", conversation_history=history)

    assert result["completed"] is True
    assert result["final_response"] == "Recovered without replay."
    assert len(request_payloads) == 2
    assert any(item.get("type") == "reasoning" for item in request_payloads[0]["input"])
    assert not any(item.get("type") == "reasoning" for item in request_payloads[1]["input"])
    assert request_payloads[0].get("include") == ["reasoning.encrypted_content"]
    assert request_payloads[1].get("include") == []
    assert result["messages"][0].get("codex_reasoning_items") is None
    assert agent._codex_reasoning_replay_enabled is False
'''
p.write_text(text + integration)
