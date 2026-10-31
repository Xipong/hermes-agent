"""Typed background notices may stay silent in ordinary Desktop/TUI chats."""

import contextlib
from types import SimpleNamespace

import pytest

import tui_gateway.server as srv


@pytest.fixture
def delivery(monkeypatch):
    events = []
    monkeypatch.setattr(srv, "_emit", lambda event, _sid, payload=None: events.append((event, payload)))
    monkeypatch.setattr(srv, "_get_usage", lambda _agent: {})
    monkeypatch.setattr(srv, "render_message", lambda _text, _cols: None)
    monkeypatch.setattr(srv, "_clear_inflight_turn", lambda _session: None)
    monkeypatch.setattr(srv, "_session_live_title", lambda _session, _key: "Ordinary chat")
    monkeypatch.setattr(srv, "_load_interim_assistant_messages", lambda: True)
    monkeypatch.setattr(srv, "_start_usage_ticker", lambda _sid, _agent: (
        SimpleNamespace(set=lambda: None), SimpleNamespace(join=lambda: None)))

    def run(chunks, *, kind="async_delegation_complete", interim=None, outcome=None, commentary=None):
        events.clear()
        spoken = []

        def conversation(_message, **kwargs):
            if commentary is not None:
                kwargs["stream_callback"](commentary)
                agent.interim_assistant_callback(commentary, already_streamed=True)
            for chunk in chunks:
                kwargs["stream_callback"](chunk)
            if interim is not None:
                agent.interim_assistant_callback(interim)
            return {"final_response": "".join(chunks), **(outcome or {})}

        agent = SimpleNamespace(_session_title_hint="Ordinary chat", run_conversation=conversation)
        session = {"agent": agent, "session_key": "k", "history_lock": contextlib.nullcontext()}
        st = srv._TurnRun(agent=agent, one_turn_restore=None, terminal_callback=None, receipt_committed=True)
        st.tts_queue = SimpleNamespace(put=spoken.append)
        srv._invoke_agent("sid", session, st, "notice", "notice", None, [], kind, None)
        payload, _, status = srv._complete_turn_payload(session, st, None, 80)
        return payload, status, list(events), spoken

    return run


@pytest.mark.parametrize("kind", ["internal_notification", "process_complete", "async_delegation_complete"])
def test_notification_marker_never_reaches_live_text_voice_or_interim(delivery, kind):
    payload, status, events, spoken = delivery(["NO", "_RE", "PLY"], kind=kind, interim="NO_REPLY")
    assert (status, payload["text"]) == ("complete", "")
    assert not [payload for event, payload in events if event in {"message.delta", "message.interim"}]
    assert spoken == []


@pytest.mark.parametrize("chunks,expected", [
    (["Ready.", "\n\nNO", "_REPLY"], "Ready."),
    (["NO", " problem, capture is ready."], "NO problem, capture is ready."),
    (["The log says NO_REPLY."], "The log says NO_REPLY."),
])
def test_notification_preserves_useful_text_and_only_removes_closing_marker(delivery, chunks, expected):
    payload, status, events, spoken = delivery(chunks)
    assert status == "complete"
    assert payload["text"] == expected
    assert "".join(p["text"] for event, p in events if event == "message.delta").rstrip() == expected
    assert "".join(spoken).rstrip() == expected


def test_human_turn_can_literally_answer_no_reply(delivery):
    payload, status, events, spoken = delivery(["NO_", "REPLY"], kind=None, interim="NO_REPLY")
    assert (status, payload["text"]) == ("complete", "NO_REPLY")
    assert "".join(p["text"] for event, p in events if event == "message.delta") == "NO_REPLY"
    assert "".join(spoken) == "NO_REPLY"
    assert [p["text"] for event, p in events if event == "message.interim"] == ["NO_REPLY"]


def test_notification_silence_is_scoped_to_the_segment_after_a_tool_round(delivery):
    payload, _, events, spoken = delivery(["NO", "_REPLY"], commentary="Checking the capture.")
    assert payload["text"] == ""
    assert "".join(p["text"] for event, p in events if event == "message.delta") == "Checking the capture."
    assert "".join(spoken) == "Checking the capture."
    assert [p["text"] for event, p in events if event == "message.interim"] == ["Checking the capture."]


@pytest.mark.parametrize("outcome,status", [
    ({"error": "provider failed", "failed": True}, "error"),
    ({"interrupted": True}, "interrupted"),
])
def test_failed_or_interrupted_notification_is_not_silenced(delivery, outcome, status):
    payload, actual, _, _ = delivery(["NO_REPLY"], outcome=outcome)
    assert (actual, payload["text"]) == (status, "NO_REPLY")


def test_silent_notification_receipt_keeps_exact_persisted_row(delivery):
    from agent.context_compressor import _DB_PERSISTED_MARKER

    rows = [
        {"role": "user", "content": "notice", "display_kind": "process_complete",
         "_row_id": 7, _DB_PERSISTED_MARKER: True},
        {"role": "assistant", "content": "NO_REPLY", "_row_id": 8, _DB_PERSISTED_MARKER: True},
    ]
    # Receipt construction uses the agent's authoritative current-row cursor.
    agent = SimpleNamespace(_session_title_hint="Ordinary chat", _persist_user_message_idx=0)
    st = SimpleNamespace(result={"final_response": "NO_REPLY", "messages": rows}, agent=agent,
                         display_kind="process_complete", history=[], compression_count=None,
                         terminal_callback=None, receipt_committed=True, marker_key="")
    session = {"agent": agent, "session_key": "k", "history_lock": contextlib.nullcontext()}
    payload, _, _ = srv._complete_turn_payload(session, st, None, 80)
    assert payload["text"] == ""
    assert payload["persisted_turn"]["final_assistant_row_id"] == 8
    assert rows[-1]["content"] == "NO_REPLY"
