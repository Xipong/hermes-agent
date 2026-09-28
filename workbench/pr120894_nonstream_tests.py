

@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("groups", [
    (("Only",),),
    (("A", "B"),),
    (("A",), ("B",)),
    (("A", "B"), ("C",), ("D",)),
], ids=["single-part", "same-item", "different-items", "mixed"])
def test_nonstream_reemit_preserves_flat_text_and_native_identity(monkeypatch, native, groups):
    from copy import deepcopy
    from agent.chat_completion_helpers import _assistant_reasoning_text

    agent, wire, observers, _ = _recording_agent(monkeypatch, native)
    expected = "\n\n".join("\n".join(group) for group in groups)
    items = [{"type": "reasoning", "id": f"rs_{i}", "summary": [
        {"type": "summary_text", "text": text} for text in group
    ]} for i, group in enumerate(groups)]
    items.insert(0, {"type": "compaction", "encrypted_content": "opaque"})
    message = NS(reasoning=expected, codex_reasoning_items=items)
    original = deepcopy(items)
    agent._extract_reasoning = lambda message: message.reasoning
    agent.verbose_logging = False
    agent.stream_delta_callback = agent._stream_callback = None
    # Re-emitting another response must not inherit separators from the previous call.
    for _ in range(2):
        wire.clear()
        observers.clear()
        assert _assistant_reasoning_text(agent, message) == expected
        assert _flat(wire) == expected
        deltas = [payload for event, _, payload in wire if event == "reasoning.delta"]
        if native:
            assert _observed(observers) == expected
            ids = [f"rs_{i}:summary:{j}" for i, group in enumerate(groups) for j in range(len(group))]
            assert [payload["reasoning_id"] for payload in deltas] == ids
            for phase in ("reasoning.start", "reasoning.end"):
                assert [payload["reasoning_id"] for event, _, payload in wire if event == phase] == ids
        else:
            assert all("reasoning_id" not in payload for payload in deltas)
        assert items == original


@pytest.mark.parametrize("invalid", ["mismatched-text", "malformed-summary"])
def test_nonstream_reemit_keeps_flat_fallback_for_untrusted_identity(monkeypatch, invalid):
    from agent.chat_completion_helpers import _assistant_reasoning_text

    agent, wire, observers, _ = _recording_agent(monkeypatch, True)
    expected = "A\nB" if invalid == "malformed-summary" else "Already selected visible text"
    message = NS(reasoning=expected, codex_reasoning_items=[{
        "type": "reasoning", "id": "rs_untrusted", "summary": [
            {"type": "summary_text", "text": "A"},
            {"type": "summary_text", "text": None if invalid == "malformed-summary" else "B"},
        ],
    }])
    agent._extract_reasoning = lambda message: message.reasoning
    agent.verbose_logging = False
    agent.stream_delta_callback = agent._stream_callback = None
    assert _assistant_reasoning_text(agent, message) == expected
    assert _flat(wire) == expected
    assert all("reasoning_id" not in payload for event, _, payload in wire if event == "reasoning.delta")
    assert not any(event in {"reasoning.start", "reasoning.end"} for event, _, _ in wire)
    assert not _observed(observers)


def test_native_reasoning_obeys_current_session_display_policy(monkeypatch):
    from agent.chat_completion_helpers import _assistant_reasoning_text

    agent, wire, observers, _ = _recording_agent(monkeypatch, True)
    message = NS(reasoning="Inspect", codex_reasoning_items=[{
        "type": "reasoning", "id": "rs_visible",
        "summary": [{"type": "summary_text", "text": "Inspect"}],
    }])
    agent._extract_reasoning = lambda message: message.reasoning
    agent.verbose_logging = False
    agent.stream_delta_callback = agent._stream_callback = None
    # The callbacks live across setting changes; the current session owns display policy.
    for visible in (True, False, True):
        monkeypatch.setitem(server._sessions[agent.session_id], "show_reasoning", visible)
        wire.clear()
        observers.clear()
        assert _assistant_reasoning_text(agent, message) == message.reasoning
        if visible:
            assert [event for event, _, _ in wire] == ["reasoning.start", "reasoning.delta", "reasoning.end"]
            assert _flat(wire) == message.reasoning
        else:
            assert wire == []
        # Display policy is not transcript mutation or plugin-observer authorization.
        assert _observed(observers) == message.reasoning
