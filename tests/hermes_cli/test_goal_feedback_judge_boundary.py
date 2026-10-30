"""Exercise the actual judge failure/parse boundary before feedback admission (#137546)."""

import builtins
import json
from types import SimpleNamespace

import pytest

from hermes_cli.goals import GoalManager


@pytest.mark.parametrize("raw, actionable", [
    ('{"verdict":"continue","reason":"Show command output.\\nInclude its exit status."}', True),
    ('{"done":false,"reason":"Show the verification result."}', True),
    ('{"verdict":"continue"}', False),
    ('{"verdict":"continue","reason":""}', False),
    ('{"verdict":"continue","reason":"no reason provided"}', False),
    ('{"verdict":"wait","reason":"Wait for CI."}', False),
    ('{"verdict":"done","reason":"All verified."}', False),
    ('{"verdict":"blocked","reason":"Need credentials."}', False),
    ('{"verdict":"unknown","reason":"Not a valid judgment."}', False),
    ('{"reason":"Missing verdict is not a judgment."}', False),
    ('not JSON', False),
    ('', False),
])
def test_only_successful_continue_becomes_feedback(monkeypatch, raw, actionable):
    from agent import auxiliary_client

    monkeypatch.setattr(auxiliary_client, "call_llm", lambda **kwargs: SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=raw))]))
    mgr = GoalManager("feedback-real-judge")
    mgr.set("finish the task")
    prefix = mgr.next_continuation_prompt()
    decision = mgr.evaluate_after_turn("Done.")
    mgr.pause()
    reloaded = GoalManager(mgr.session_id)
    reloaded.resume()
    prompt = reloaded.next_continuation_prompt()
    assert prompt.startswith(prefix)
    assert ("previous completion claim was rejected" in prompt) is actionable
    if actionable:
        assert json.loads(raw)["reason"] in prompt
        assert decision["continuation_prompt"] == prompt
    else:
        assert prompt == prefix


@pytest.mark.parametrize("failure", ["transport", "import"])
def test_failed_judge_is_diagnostic_not_objection(monkeypatch, failure):
    from agent import auxiliary_client

    def unavailable(**kwargs):
        raise RuntimeError("offline transport")

    if failure == "transport":
        monkeypatch.setattr(auxiliary_client, "call_llm", unavailable)
    else:
        original_import = builtins.__import__

        def failed_import(name, *args, **kwargs):
            if name == "agent.auxiliary_client":
                raise ImportError("unavailable in this test")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", failed_import)

    mgr = GoalManager(f"feedback-real-{failure}")
    mgr.set("finish the task")
    prefix = mgr.next_continuation_prompt()
    decision = mgr.evaluate_after_turn("Done.")
    assert decision["should_continue"]
    assert decision["reason"] in decision["message"]
    assert decision["continuation_prompt"] == prefix
    assert GoalManager(mgr.session_id).next_continuation_prompt() == prefix
