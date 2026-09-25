"""Disposable fork-only validation/publishing harness; never included in product PRs."""
from pathlib import Path
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = "8623cd4a8403f020090c9c3e8feae943b4dac55e"
ROOT = Path(__file__).resolve().parents[1]
LOGS = Path(os.environ["RUNNER_TEMP"]) / "phase-followup-results"
LOGS.mkdir(exist_ok=True)
ADAPTER = "agent/codex_responses_adapter.py"
RUNTIME = "agent/codex_runtime.py"


def replace(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError(f"Expected one patch anchor, got {text.count(before)}: {before[:120]!r}")
    return text.replace(before, after, 1)


def patch_replay(text):
    anchor = "def _message_item(\n"
    helper = '''def _role_message_with_phase(role: str, content: Any, phase: Any = None) -> Dict[str, Any]:
    """Preserve an explicitly supplied assistant phase without inventing output status or IDs.

    Ordinary role messages and exact output-item replay must agree on phase; user inputs
    never inherit assistant-only metadata. Keep absent/invalid phase absent.
    """
    item = {"role": role, "content": content}
    if role == "assistant" and _nonblank(phase):
        item["phase"] = phase.strip()
    return item


'''
    text = replace(text, anchor, helper + anchor)
    text = replace(text,
        '            emit([{"role": "assistant", "content": wire_content(follower)}], msg)',
        '            emit([_role_message_with_phase("assistant", wire_content(follower), msg.get("phase"))], msg)')
    text = replace(text,
        '        return {"role": role, "content": ctx.sanitize_text(_str_or_empty(content))}',
        '        return _role_message_with_phase(role, ctx.sanitize_text(_str_or_empty(content)), item.get("phase"))')
    return replace(text,
        '    return {"role": role, "content": validated}',
        '    return _role_message_with_phase(role, validated, item.get("phase"))')


def patch_completion(text):
    text = replace(text,
        '        self.saw_final_answer_phase = self.saw_final_answer_phase or normalized_phase in {"final_answer", "final"}\n        message_text = _extract_responses_message_text(item)\n        if not message_text:\n            return',
        '        message_text = _extract_responses_message_text(item)\n        if not message_text:\n            return\n        # An empty final marker cannot authorize promoting aggregated commentary to a final.\n        self.saw_final_answer_phase = self.saw_final_answer_phase or normalized_phase in {"final_answer", "final"}')
    text = replace(text,
        '    response_incomplete_content_filter = response_status == "incomplete" and incomplete_reason == "content_filter"',
        '    response_incomplete_content_filter = response_status == "incomplete" and incomplete_reason == "content_filter"\n    # Keep the completed-final override for Azure\'s soft incomplete envelope (#27988),\n    # but explicit output exhaustion is real truncation, even when one message completed.\n    response_output_exhausted = (\n        response_status == "incomplete" and incomplete_reason in {"max_output_tokens", "length"}\n    )')
    return replace(text,
        '        leaked_tool_call_text\n        or scan.saw_streaming_or_item_incomplete',
        '        leaked_tool_call_text\n        or response_output_exhausted\n        or scan.saw_streaming_or_item_incomplete')


def patch_stream(text):
    text = replace(text, 'from contextlib import suppress\n', 'from contextlib import suppress\nfrom copy import copy\n')
    text = replace(text,
        '# response from ``output_item.done``, so the terminal ``output`` may be null / [] / a string / absent.',
        '# response from item events. Valid terminal messages fill gaps; null / [] / a string / absent\n# terminal ``output`` still leaves the collected items intact.')
    text = replace(text,
        '    Only ``usage`` / ``status`` / ``id`` are read from the terminal frame — never ``response.output``. Output\n    items come from ``output_item.done``, or are synthesized from text deltas, or settled from function calls\n    announced via ``output_item.added`` but never confirmed (some backends omit per-item done events on success).',
        '    Item events own the accumulated output. Valid terminal message items may supply missing\n    messages/metadata, never erase collected output. Message phases and deltas are scoped to\n    item identity. Announced function calls settle only after an observed response.completed.')
    text = replace(text, '    terminal_status: str = "completed"', '    terminal_status: str = "in_progress"')
    text = replace(text,
        '    # terminal_status defaults to "completed", so settlement needs an explicitly observed response.completed frame.',
        '    # A missing terminal frame is not success; only an observed completion can settle pending calls.')
    text = replace(text,
        '        self.announced_output_order: Dict[str, tuple] = {}',
        '''        self.announced_output_order: Dict[str, tuple] = {}
        self.message_keys_by_index: Dict[Any, Any] = {}
        self.message_phases: Dict[Any, Any] = {}
        self.message_deltas: Dict[Any, list] = {}
        self.message_announcements: Dict[Any, tuple] = {}
        self.message_done_positions: Dict[Any, int] = {}
        self.delivered_commentary: set = set()
        self.active_message_key = None''')
    anchor = '    def _on_item_added(self, event: Any, event_type: str) -> None:\n'
    helpers = '''    def _message_key(self, event: Any, item: Any = None, *, use_active: bool = True) -> Any:
        item_id = _event_field(item, "id") if item is not None else _event_field(event, "item_id")
        index = _event_field(event, "output_index")
        if isinstance(item_id, str) and item_id:
            key = ("id", item_id)
            if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
                self.message_keys_by_index[index] = key
            return key
        if isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            return self.message_keys_by_index.get(index, ("index", index))
        return self.active_message_key if use_active else None

    @staticmethod
    def _copy_message(item: Any, **updates: Any) -> Any:
        # Never annotate/mutate the provider's SDK object or raw JSON frame in place.
        result = SimpleNamespace(**item) if isinstance(item, dict) else copy(item)
        for name, value in updates.items():
            setattr(result, name, value)
        return result

'''
    text = replace(text, anchor, helpers + anchor)
    text = replace(text,
        '        if "function_call" in str(item_type):\n            self.has_tool_calls = True',
        '''        self.active_message_key = None
        if item_type == "message":
            key = self._message_key(event, item, use_active=False)
            if key is None:
                key = ("anonymous", self.next_output_sequence)
            sequence, index = self.announced_output_order.get(item_id, (None, _event_field(event, "output_index")))
            if sequence is None:
                sequence, self.next_output_sequence = self.next_output_sequence, self.next_output_sequence + 1
            self.active_message_key = key
            self.message_phases[key] = _message_phase(item)
            self.message_deltas.setdefault(key, [])
            self.message_announcements[key] = (item, index, sequence)
        if "function_call" in str(item_type):
            self.has_tool_calls = True''')
    text = replace(text,
        '''        # Harmony commentary/analysis text is mid-turn narration, never the final answer: route to the
        # reasoning callback, keep only the item for replay.
        if self.active_message_phase == "commentary":
            self.commentary_text_deltas.append(delta_text)''',
        '''        key = self._message_key(event)
        # Explicit item identity must not inherit another item's active phase.
        phase = self.message_phases.get(key) if key is not None else self.active_message_phase
        if key is not None:
            self.message_deltas.setdefault(key, []).append(delta_text)
        if phase == "commentary":
            if key is None:
                self.commentary_text_deltas.append(delta_text)''')
    text = replace(text,
        '        elif self.active_message_phase == "analysis":',
        '        elif phase == "analysis":')
    start = text.index('    def _on_item_done(self, event: Any, event_type: str) -> None:\n')
    end = text.index('    def _on_terminal(', start)
    text = text[:start] + '''    def _on_item_done(self, event: Any, event_type: str, *, message_key: Any = None) -> None:
        done_item = _event_field(event, "item")
        if done_item is None:
            return
        is_message = _event_field(done_item, "type") == "message"
        key = (message_key or self._message_key(event, done_item)) if is_message else None
        if is_message:
            phase = _message_phase(done_item) or self.message_phases.get(key)
            done_item = self._copy_message(done_item, **({"phase": phase} if phase else {}))
            if key is not None:
                self.message_phases[key] = phase
        position = self.message_done_positions.get(key) if key is not None else None
        if position is not None:
            # A terminal snapshot only fills absent data. It cannot overwrite a completed
            # item or produce a second copy of a message already delivered from .done.
            prior = self.output_items[position]
            updates = {}
            if not _message_phase(prior) and _message_phase(done_item):
                updates["phase"] = _message_phase(done_item)
            if not _event_field(prior, "content") and isinstance(_event_field(done_item, "content"), list):
                updates["content"] = _event_field(done_item, "content")
            done_item = self._copy_message(prior, **updates)
            self.output_items[position] = done_item
        else:
            position = len(self.output_items)
            self.output_items.append(done_item)
            done_id = str(_event_field(done_item, "id", ""))
            sequence, index = self.announced_output_order.get(done_id, (None, None))
            if key in self.message_announcements:
                _, index, sequence = self.message_announcements[key]
            if sequence is None:
                sequence, self.next_output_sequence = self.next_output_sequence, self.next_output_sequence + 1
            self.output_indexes.append(_event_field(event, "output_index", index))
            self.output_sequences.append(sequence)
            if key is not None:
                self.message_done_positions[key] = position
            self.pending_function_calls.pop(done_id, None)
        if _message_phase(done_item) == "commentary" and self.on_commentary_message is not None:
            delivery_key = key if key is not None else ("position", position)
            if delivery_key not in self.delivered_commentary:
                deltas = self.message_deltas.get(key, []) if key is not None else self.commentary_text_deltas
                commentary = _output_text_of(done_item) or "".join(deltas).strip()
                if commentary:
                    self._safe(self.on_commentary_message, "on_commentary_message", commentary)
                    self.delivered_commentary.add(delivery_key)
            if key is None:
                self.commentary_text_deltas = []

''' + text[end:]
    text = replace(text,
        '        self.saw_terminal = True\n        resp_obj = _event_field(event, "response")',
        '        self.saw_terminal = True\n        self.terminal_status = event_type.removeprefix("response.")\n        resp_obj = _event_field(event, "response")')
    text = replace(text,
        '            if isinstance(rstatus, str):\n                self.terminal_status = rstatus',
        '            if isinstance(rstatus, str) and rstatus.strip():\n                self.terminal_status = rstatus.strip().lower()')
    text = replace(text,
        '        self.terminal_status = self.terminal_status or event_type.removeprefix("response.")\n        return True',
        '''        # Some relays omit .done but supply a valid final snapshot. Only message
        # items are backfilled here; pending function-call settlement remains separately gated.
        terminal_output = _event_field(resp_obj, "output")
        if isinstance(terminal_output, list):
            for index, item in enumerate(terminal_output):
                if _event_field(item, "type") == "message" and isinstance(_event_field(item, "content"), list):
                    self._on_item_done({"item": item, "output_index": index}, "response.output_item.done")
        return True''')
    text = replace(text,
        '    def _settled_output(self) -> List[Any]:',
        '    def _settled_output(self, *, settle_pending: bool = True) -> List[Any]:')
    text = replace(text,
        '        for pending in self.pending_function_calls.values():',
        '        for pending in self.pending_function_calls.values() if settle_pending else ():')
    text = replace(text,
        '''        # With only plain text deltas (no tool calls), synthesize one message item.
        output: List[Any] = list(self.output_items)''',
        '''        # Preserve item-scoped partial text and phase even when .done was omitted.
        for key, (item, index, _) in list(self.message_announcements.items()):
            deltas = self.message_deltas.get(key, [])
            if key not in self.message_done_positions and deltas:
                recovered = self._copy_message(
                    item, status=self.terminal_status,
                    content=[SimpleNamespace(type="output_text", text="".join(deltas))],
                )
                self._on_item_done({"item": recovered, "output_index": index}, "response.output_item.done", message_key=key)
        output: List[Any] = self._settled_output(settle_pending=self.saw_response_completed)
        # Legacy streams with no item identity still retain their collected text.''')
    text = replace(text,
        '            output = [SimpleNamespace(type="message", role="assistant", status="completed", content=content)]',
        '            output = [SimpleNamespace(type="message", role="assistant", status=self.terminal_status, content=content)]')
    text = replace(text,
        '''        # Done items stay authoritative; settlement only fills the gap left by backends that omit
        # per-item done events on a successful completion.
        if self.pending_function_calls and self.saw_response_completed:
            output = self._settled_output()
''', '')
    return replace(text,
        '''    :class:`_CodexResponseAssembler`; ``status`` is ``completed`` when the stream ended with content but no
    terminal frame; ``model`` comes from kwargs).''',
        '''    :class:`_CodexResponseAssembler`; a stream ending without a terminal frame retains
    ``status=in_progress`` rather than inventing completion; ``model`` comes from kwargs).''')


SPECS = {
    "replay": (ADAPTER, patch_replay, "fix/responses-role-phase-replay", "fix(responses): preserve explicit assistant phase in role-message replay"),
    "completion": (ADAPTER, patch_completion, "fix/responses-final-completion-evidence", "fix(responses): require substantive final evidence and honor output exhaustion"),
    "stream": (RUNTIME, patch_stream, "fix/codex-stream-message-phase-state", "fix(codex): retain message phase and terminal evidence during stream assembly"),
}


def command(args, cwd, log=None, check=True):
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if log:
        (LOGS / log).write_text(result.stdout)
    print(result.stdout[-16000:], flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args}")
    return result


def run_lane(lane):
    path, patch, branch, title = SPECS[lane]
    candidate = Path(os.environ["RUNNER_TEMP"]) / ("phase-candidate-" + lane)
    command(["git", "worktree", "add", "--detach", str(candidate), BASE], ROOT)
    test_path = f"tests/agent/test_responses_{lane}_phase_regression.py"
    (candidate / test_path).write_text((ROOT / "workbench" / f"phase_{lane}_test.py").read_text())
    xml = LOGS / (lane + "-red.xml")
    red = command(["bash", "scripts/run_tests.sh", test_path, "--file-retries", "0", "-q", "--tb=short", f"--junitxml={xml}"], candidate, lane + "-red.log", check=False)
    if not xml.exists():
        raise RuntimeError("No baseline JUnit receipt; refusing to label a harness failure a reproduction")
    root = ET.parse(xml).getroot()
    failures = root.findall(".//failure")
    errors = root.findall(".//error")
    if not red.returncode or not failures or errors:
        raise RuntimeError(f"Expected assertion failures, no collection errors: rc={red.returncode}, failures={len(failures)}, errors={len(errors)}")
    (candidate / path).write_text(patch((candidate / path).read_text()))
    greenxml = LOGS / (lane + "-green.xml")
    command(["bash", "scripts/run_tests.sh", test_path, "--file-retries", "0", "-q", "--tb=short", f"--junitxml={greenxml}"], candidate, lane + "-green.log")
    neighbors = ["tests/agent/test_codex_responses_adapter.py", "tests/agent/test_run_agent_codex_responses.py", "tests/agent/transports/test_codex_transport.py"]
    neighbors = [p for p in neighbors if (candidate / p).exists()]
    command(["bash", "scripts/run_tests.sh", *neighbors, "--file-retries", "0", "-q", "--tb=short"], candidate, lane + "-neighbors.log")
    command([sys.executable, "-m", "py_compile", path, test_path], candidate, lane + "-compile.log")
    command([sys.executable, "-m", "ruff", "check", "--select", "F821,F822,F823", path, test_path], candidate, lane + "-lint.log")
    command(["git", "diff", "--check"], candidate, lane + "-diffcheck.log")
    command(["git", "config", "user.name", "Xipong"], candidate)
    command(["git", "config", "user.email", "217837358+Xipong@users.noreply.github.com"], candidate)
    command(["git", "add", path, test_path], candidate)
    command(["git", "commit", "-m", title], candidate)
    head = command(["git", "rev-parse", "HEAD"], candidate).stdout.strip()
    command(["git", "diff", BASE, "HEAD"], candidate, lane + "-final.diff")
    # Never force-update an existing product branch; fail on a concurrent edit.
    command(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], candidate, lane + "-publish.log")
    receipt = f"lane={lane}\nbase={BASE}\nhead={head}\nbranch={branch}\nred_assertion_failures={len(failures)}\ngreen_tests={len(ET.parse(greenxml).getroot().findall('.//testcase'))}\n"
    (LOGS / (lane + "-receipt.txt")).write_text(receipt)
    print("PUBLISHED\n" + receipt, flush=True)


if __name__ == "__main__":
    failures = []
    for lane in SPECS:
        try:
            run_lane(lane)
        except Exception as exc:
            failures.append(f"{lane}: {type(exc).__name__}: {exc}")
            print("LANE FAILED", failures[-1], flush=True)
    if failures:
        raise SystemExit("\n".join(failures))
