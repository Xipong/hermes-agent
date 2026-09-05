from pathlib import Path

p = Path('agent/anthropic_endpoints.py')
s = p.read_text()
marker = '\ndef _is_deepseek_anthropic_endpoint('
assert s.count(marker) == 1
extra = '''
_DEEPSEEK_THINKING_MODEL_PREFIXES = (
    "deepseek-r", "deepseek-v4", "deepseek_v4", "deepseek-pro",
    "deepseek_pro", "deepseek-flash", "deepseek_flash",
)


def _model_name_is_deepseek_thinking(model: str | None) -> bool:
    """Known DeepSeek thinking families behind an Anthropic-compatible relay.

    Strip vendor namespaces, but do not treat arbitrary DeepSeek chat/distill
    names as evidence of the thinking replay contract.
    """
    if not isinstance(model, str):
        return False
    name = model.strip().lower().rsplit("/", 1)[-1]
    return bool(name) and name.startswith(_DEEPSEEK_THINKING_MODEL_PREFIXES)

'''
s = s.replace(marker, '\n' + extra + marker, 1)
p.write_text(s)
p = Path('agent/anthropic_message_convert.py')
s = p.read_text()
s = s.replace('    _is_third_party_anthropic_endpoint,\n', '    _is_third_party_anthropic_endpoint, _model_name_is_deepseek_thinking,\n', 1)
old = '    is_deepseek = _is_deepseek_anthropic_endpoint(base_url)\n'
assert s.count(old) == 1
s = s.replace(old, '''    is_deepseek = _is_deepseek_anthropic_endpoint(base_url) or (
        is_third_party and _model_name_is_deepseek_thinking(model)
    )
''', 1)
p.write_text(s)
p = Path('tests/agent/test_deepseek_anthropic_thinking.py')
s = p.read_text().rstrip() + '''


@pytest.mark.parametrize("model", [
    "deepseek-r1", "deepseek-v4", "vendor/deepseek-v4-pro",
    "gateway/deepseek-ai/deepseek_flash", " DeepSeek-Pro ", "deepseek_v4_flash",
])
def test_thinking_family_name_detection(model):
    from agent.anthropic_endpoints import _model_name_is_deepseek_thinking
    assert _model_name_is_deepseek_thinking(model)


@pytest.mark.parametrize("model", [None, "", " ", 42, "deepseek-chat", "deepseek-v3", "vendor/", "not-deepseek-v4", "qwen-thinking"])
def test_thinking_family_name_detection_rejects_unknown_models(model):
    from agent.anthropic_endpoints import _model_name_is_deepseek_thinking
    assert not _model_name_is_deepseek_thinking(model)


@pytest.mark.parametrize("url", [None, "https://api.anthropic.com", "https://inference-api.nousresearch.com/anthropic"])
def test_deepseek_model_name_does_not_override_native_signature_contract(url):
    from agent.anthropic_message_convert import _manage_thinking_signatures
    block = {"type": "thinking", "thinking": "signed native reasoning", "signature": "sig"}
    messages = [{"role": "assistant", "content": [dict(block), {"type": "text", "text": "answer"}]}]
    _manage_thinking_signatures(messages, url, "deepseek-v4")
    assert messages[0]["content"][0] == block


def test_deepseek_proxy_keeps_unsigned_thinking_in_older_tool_turns_only():
    import copy
    from agent.anthropic_message_convert import convert_messages_to_anthropic
    history = [
        {"role": "user", "content": "inspect"},
        {"role": "assistant", "content": "checking", "reasoning_details": [
            {"type": "thinking", "thinking": "unsigned", "cache_control": {"type": "ephemeral"}},
            {"type": "thinking", "thinking": "foreign signed", "signature": "sig"},
            {"type": "redacted_thinking", "data": "redacted-signature"},
        ], "tool_calls": [{"id": "call_1", "type": "function", "function": {"name": "inspect", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "content": "ok"},
        {"role": "assistant", "content": "done"},
    ]
    snapshot = copy.deepcopy(history)
    _, result = convert_messages_to_anthropic(history, base_url="https://proxy.example/anthropic", model="vendor/deepseek-v4")
    assistant = next(m for m in result if m["role"] == "assistant")
    assert [b for b in assistant["content"] if b.get("type") in {"thinking", "redacted_thinking"}] == [
        {"type": "thinking", "thinking": "unsigned"},
    ]
    assert history == snapshot
'''
p.write_text(s + '\n')
