"""Reloads hide typed notification silence without mutating replay history."""

from copy import deepcopy

import pytest

from hermes_cli.web_routers.sessions import _project_for_display
from tui_gateway.server import _history_to_messages


@pytest.mark.parametrize("kind", ["internal_notification", "process_complete", "async_delegation_complete"])
def test_rest_and_resume_hide_notification_marker_but_keep_notice_and_raw_rows(kind):
    rows = [
        {"id": 7, "_row_id": 7, "role": "user", "content": "new result", "display_kind": kind},
        {"id": 8, "_row_id": 8, "role": "assistant", "content": "NO_REPLY", "finish_reason": "stop",
         "codex_message_items": [{"type": "message", "role": "assistant", "phase": "final_answer",
                                  "content": [{"type": "output_text", "text": "NO_REPLY"}]}]},
    ]
    original = deepcopy(rows)
    rest = _project_for_display(rows)
    assert rest[0]["display_kind"] == kind
    assert rest[1]["display_kind"] == "hidden"
    assert rest[1]["content"] == "NO_REPLY"
    assert [m["role"] for m in _history_to_messages(rows)] == ["user"]
    assert rows == original


@pytest.mark.parametrize("adapter,key", [(_project_for_display, "display_content"), (_history_to_messages, "text")])
def test_history_keeps_useful_notification_reply_and_removes_only_closing_marker(adapter, key):
    rows = [{"role": "user", "content": "new result", "display_kind": "process_complete"},
            {"role": "assistant", "content": "Capture is ready.\n\nNO_REPLY", "finish_reason": "stop"}]
    projected = adapter(rows)
    assert projected[-1][key] == "Capture is ready."
    assert rows[-1]["content"].endswith("NO_REPLY")


@pytest.mark.parametrize("notice", [False, True])
def test_human_turn_resets_notification_scope_even_when_it_mentions_a_notification(notice):
    rows = ([{"role": "user", "content": "notice", "display_kind": "process_complete"},
             {"role": "assistant", "content": "NO_REPLY", "finish_reason": "stop"}] if notice else [])
    rows += [{"role": "user", "content": "[ASYNC DELEGATION BATCH COMPLETE] Reply literally NO_REPLY"},
             {"role": "assistant", "content": "NO_REPLY", "finish_reason": "stop"}]
    for adapter in (_project_for_display, _history_to_messages):
        projected = adapter(rows)
        assert projected[-1].get("display_kind") != "hidden"
        assert projected[-1].get("content", projected[-1].get("text")) == "NO_REPLY"


@pytest.mark.parametrize("extra", [{"finish_reason": "error"}, {"failed": True}, {"interrupted": True}])
def test_history_does_not_hide_failed_notification_reply(extra):
    rows = [{"role": "user", "content": "notice", "display_kind": "process_complete"},
            {"role": "assistant", "content": "NO_REPLY", **extra}]
    assert _project_for_display(rows)[-1].get("display_kind") != "hidden"
    assert _history_to_messages(rows)[-1]["text"] == "NO_REPLY"
