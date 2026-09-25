"""Fork-only second-pass validation for the stream lane; excluded from product branches."""
from pathlib import Path
import os

import phase_followups as p

LEGACY = "tests/agent/test_run_agent_codex_responses.py"
_original_patch = p.patch_stream
_original_command = p.command


def reviewed_patch(text):
    text = _original_patch(text)
    text = p.replace(text, '''        if isinstance(terminal_output, list):
            for index, item in enumerate(terminal_output):
                if _event_field(item, "type") == "message" and isinstance(_event_field(item, "content"), list):
                    self._on_item_done({"item": item, "output_index": index}, "response.output_item.done")''', '''        if isinstance(terminal_output, list):
            # With neither an item ID nor an index on earlier messages, a terminal
            # snapshot cannot prove which message is new. Never dedupe by matching prose.
            ambiguous_messages = any(
                _event_field(item, "type") == "message"
                and not (isinstance(_event_field(item, "id"), str) and _event_field(item, "id"))
                and index is None
                for item, index in zip(self.output_items, self.output_indexes)
            )
            for index, item in enumerate(terminal_output):
                if (
                    _event_field(item, "type") != "message"
                    or _event_field(item, "role", "assistant") not in {None, "assistant"}
                    or not isinstance(_event_field(item, "content"), list)
                ):
                    continue
                frame = {"item": item, "output_index": index}
                key = self._message_key(frame, item, use_active=False)
                if ambiguous_messages and key not in self.message_done_positions:
                    continue
                self._on_item_done(frame, "response.output_item.done")''')

    candidate = Path(os.environ["RUNNER_TEMP"]) / "phase-candidate-stream"
    legacy = candidate / LEGACY
    original = legacy.read_text()
    start = original.index("def test_run_codex_stream_returns_collected_items_when_stream_ends_without_terminal(")
    end = original.index("\ndef test_", start + 5)
    block = original[start:end]
    doc_start = block.index('    """')
    doc_end = block.index('    """', doc_start + 7) + len('    """')
    block = block[:doc_start] + '''    """Retain collected text on silent EOF without inventing response completion.

    Stream collection still makes one request and returns usable partial data. The
    normalizer must signal incomplete so the conversation loop can continue it.
    """''' + block[doc_end:]
    block = p.replace(block, '    assert response.status == "completed"', '    assert response.status == "in_progress"')
    block = p.replace(block, '    assert response.output == [output_item]', '''    assert response.output == [output_item]
    from agent.codex_responses_adapter import _normalize_codex_response
    normalized, finish_reason = _normalize_codex_response(response, issuer_kind="codex_backend")
    assert normalized.content == "no terminal frame"
    assert finish_reason == "incomplete"''')
    legacy.write_text(original[:start] + block + original[end:])
    return text


def reviewed_command(args, cwd, log=None, check=True):
    args = list(args)
    if args[:2] == ["git", "add"]:
        args.append(LEGACY)
    if "py_compile" in args or ("ruff" in args and "check" in args):
        args.append(LEGACY)
    return _original_command(args, cwd, log=log, check=check)


def main():
    payload = p.ROOT / "workbench/phase_stream_test.py"
    tests = payload.read_text()
    tests = p.replace(tests,
        'terminal(kind="completed", output=None)',
        'terminal(kind="completed", output=None, status="incomplete")')
    tests += '''


def test_legacy_unidentified_done_is_not_duplicated_by_terminal_snapshot():
    item = msg(text="Complete answer", phase="final_answer")
    item.pop("id")
    response, _, _, _ = consume([
        {"type": "response.output_item.done", "item": item}, terminal([item]),
    ])
    result, finish = _normalize_codex_response(response)
    assert finish == "stop"
    assert result.content == "Complete answer"
    assert len(result.codex_message_items) == 1


def test_index_only_message_identity_merges_terminal_snapshot_once():
    item = msg()
    item.pop("id")
    response, _, commentary, _ = consume([added(item), done(item), terminal([item])])
    result, finish = _normalize_codex_response(response, issuer_kind="codex_backend")
    assert finish == "incomplete"
    assert len(result.codex_message_items) == 1
    assert commentary == ["Checking."]


def test_terminal_only_unidentified_final_can_be_recovered():
    item = msg(text="42", phase="final_answer")
    item.pop("id")
    response, _, _, _ = consume([terminal([item])])
    result, finish = _normalize_codex_response(response)
    assert finish == "stop"
    assert result.content == "42"
    assert len(result.codex_message_items) == 1


def test_terminal_backfill_does_not_promote_a_user_message():
    answer = msg(text="42", phase="final_answer")
    alien = msg("msg_user", "Not an assistant answer", "final_answer")
    alien["role"] = "user"
    response, _, _, _ = consume([done(answer), terminal([answer, alien])])
    result, finish = _normalize_codex_response(response)
    assert finish == "stop"
    assert result.content == "42"
    assert len(result.codex_message_items) == 1


def test_real_sdk_message_objects_keep_phase_without_mutation():
    from openai.types.responses import ResponseOutputMessage, ResponseOutputText

    part = ResponseOutputText.model_construct(type="output_text", text="Checking.", annotations=[])
    announced = ResponseOutputMessage.model_construct(type="message", role="assistant", id="msg_sdk", status="in_progress", content=[], phase="commentary")
    completed = ResponseOutputMessage.model_construct(type="message", role="assistant", id="msg_sdk", status="completed", content=[part])
    before = completed.model_dump()
    commentary = []
    response = _consume_codex_event_stream(iter([
        NS(type="response.output_item.added", output_index=0, item=announced),
        NS(type="response.output_text.delta", item_id="msg_sdk", output_index=0, delta="Checking."),
        NS(type="response.output_item.done", output_index=0, item=completed),
        NS(type="response.completed", response=NS(status="completed")),
    ]), model="test-model", on_commentary_message=commentary.append)
    result, finish = _normalize_codex_response(response, issuer_kind="codex_backend")
    assert finish == "incomplete"
    assert result.codex_message_items[0]["phase"] == "commentary"
    assert commentary == ["Checking."]
    assert completed.model_dump() == before
'''
    payload.write_text(tests)
    path, _, branch, title = p.SPECS["stream"]
    p.SPECS["stream"] = (path, reviewed_patch, branch, title)
    p.command = reviewed_command
    p.run_lane("stream")


if __name__ == "__main__":
    main()
