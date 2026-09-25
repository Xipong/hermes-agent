"""Fork-only, reproducible review/rebase validation. Product refs change only after green gates."""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

BASE = "59004a62356f3a4697ab0fe8ad5086d2b405e2a6"
OLD = "b0936c3406566fa133c07aed4b7a6e1199f3695c"
COMMON = "32eeacdf7c1eba14a2abc51f4b7545b7e98afa40"
BRANCH = "fix/codex-output-continuity"
ROOT = Path.cwd()
OUT = Path(os.environ["RUNNER_TEMP"]) / "pr120894-evidence"
OUT.mkdir(exist_ok=True)
CANDIDATE = Path(os.environ["RUNNER_TEMP"]) / "pr120894-candidate"
PYTEST = "tests/tui_gateway/test_native_reasoning_segments.py"
TSTEST = "apps/desktop/src/lib/chat-messages.reasoning-boundary.test.ts"


def run(*args, cwd=ROOT, log=None, check=True, timeout=1200):
    print("RUN", str(cwd), args, flush=True)
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=timeout, env={**os.environ, "GIT_EDITOR": ":", "GIT_SEQUENCE_EDITOR": ":"})
    if log:
        (OUT / log).write_text(result.stdout)
    print(result.stdout[-22000:], flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command returned {result.returncode}: {args}")
    return result


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Patch anchor count {text.count(old)}: {old[:110]!r}")
    return text.replace(old, new, 1)


def resolve_rebase():
    paths = run("git", "diff", "--name-only", "--diff-filter=U", cwd=CANDIDATE).stdout.splitlines()
    if not paths:
        raise RuntimeError("Rebase stopped without known content conflicts")
    print("REBASE_CONFLICTS", paths, flush=True)
    pattern = re.compile(r"^<<<<<<< [^\n]*\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n", re.M | re.S)
    for path in paths:
        file = CANDIDATE / path
        if path in {"apps/shared/src/gateway-contract.generated.ts", "apps/shared/src/gateway-contract.openrpc.json"}:
            # Generated files will be regenerated from the combined source declarations.
            run("git", "checkout", "--ours", "--", path, cwd=CANDIDATE)
        else:
            def resolve(match):
                ours, theirs = match.groups()
                if path == "agent/agent_init.py":
                    if '"tool_result_metadata_callback"' in ours and '"reasoning_event_callback"' in theirs:
                        return ours.replace('"reasoning_callback",', '"reasoning_callback", "reasoning_event_callback",')
                    if "tool_result_metadata_callback:" in ours and "reasoning_event_callback:" in theirs:
                        return ours + theirs
                if path == "run_agent.py" and "tool_result_metadata_callback:" in ours and "reasoning_event_callback:" in theirs:
                    return ours + theirs
                if path == "agent/stream_delivery.py" and "inline: bool = False" in ours and "source_id:" in theirs:
                    return ours.replace("inline: bool = False", "inline: bool = False, source_id: str | None = None")
                if path == "agent/codex_runtime.py" and "_CODEX_TEXT_DELTA_METHODS" in ours and '"item/reasoning/summaryDelta"' in theirs:
                    return ours.replace(
                        "method: functools.partial(_fire_delta, attr=attr)",
                        'method: (_fire_reasoning_delta if attr == "_fire_reasoning_delta" else functools.partial(_fire_delta, attr=attr))',
                    )
                if path == "tests/agent/test_codex_app_server_event_bridge.py" and not ours.strip() and "test_reasoning_item_lifecycle" in theirs:
                    return theirs
                raise RuntimeError(f"Unreviewed conflict in {path}:\nOURS\n{ours}\nTHEIRS\n{theirs}")
            text, count = pattern.subn(resolve, file.read_text())
            if not count or any(marker in text for marker in ("<<<<<<< ", "=======\n", ">>>>>>> ")):
                raise RuntimeError(f"Unresolved conflict markers: {path}")
            file.write_text(text)
        run("git", "add", path, cwd=CANDIDATE)


def rebase():
    run("git", "fetch", "--no-tags", "origin", OLD, BASE)
    run("git", "worktree", "add", "--detach", str(CANDIDATE), OLD)
    run("git", "config", "user.name", "Xipong", cwd=CANDIDATE)
    run("git", "config", "user.email", "217837358+Xipong@users.noreply.github.com", cwd=CANDIDATE)
    result = run("git", "rebase", "--reapply-cherry-picks", "--empty=keep", "--onto", BASE, COMMON, cwd=CANDIDATE, check=False)
    for _ in range(20):
        if not result.returncode:
            break
        resolve_rebase()
        result = run("git", "rebase", "--continue", cwd=CANDIDATE, check=False)
    if result.returncode:
        raise RuntimeError("Rebase did not finish")
    before = run("git", "log", "--reverse", "--format=%an <%ae>%n%B", f"{COMMON}..{OLD}").stdout
    after = run("git", "log", "--reverse", "--format=%an <%ae>%n%B", f"{BASE}..HEAD", cwd=CANDIDATE).stdout
    if before != after:
        raise RuntimeError("Rebase changed original contributor names/emails/messages")
    (OUT / "preserved-lineage.txt").write_text(after)
    run("git", "range-diff", f"{COMMON}..{OLD}", f"{BASE}..HEAD", cwd=CANDIDATE, log="rebase-range.diff")
    (OUT / "rebased-head.txt").write_text(run("git", "rev-parse", "HEAD", cwd=CANDIDATE).stdout)


def patch_runtime(text):
    start = text.index("    def _on_reasoning_delta(self, event: Any, event_type: str) -> None:\n")
    end = text.index("    def _on_reasoning_part(", start)
    text = text[:start] + '''    def _on_reasoning_delta(self, event: Any, event_type: str) -> None:
        reasoning_text = _event_field(event, "delta", "")
        if not reasoning_text:
            return
        summary_index = _event_field(event, "summary_index")
        item_id = _event_field(event, "item_id")
        # A native source ID must not remove separators needed by flat gateway/plugin
        # consumers. Coordinates include the item: each new item can restart at index 0.
        if summary_index is not None:
            source = (item_id, summary_index)
            if self.active_summary_index is not None and source != self.active_summary_index:
                reasoning_text = f"\\n\\n{reasoning_text}"
            self.active_summary_index = source
        structured = (
            self.on_reasoning_event is not None and isinstance(item_id, str) and item_id
            and isinstance(summary_index, int) and not isinstance(summary_index, bool) and summary_index >= 0
        )
        if structured:
            self._safe(
                self.on_reasoning_event, "on_reasoning_event",
                "delta", f"{item_id}:summary:{summary_index}", reasoning_text,
            )
        elif self.on_reasoning_delta is not None:
            self._safe(self.on_reasoning_delta, "on_reasoning_delta", reasoning_text)

''' + text[end:]
    text = replace(text, "    active_reasoning_item_id: str | None = None\n", '''    active_reasoning_item_id: str | None = None
    previous_reasoning_source: str | None = None
    reasoning_sources: dict[str, list[str]] = {}
''')
    start = text.index("    def _fire_reasoning_delta(params: dict) -> None:\n")
    end = text.index("    def _fire_agent_message_completed(", start)
    text = text[:start] + '''    def _fire_reasoning_delta(params: dict) -> None:
        nonlocal previous_reasoning_source
        text = _delta_text(params)
        if not text:
            return
        item_id = params.get("itemId") or params.get("item_id") or active_reasoning_item_id
        source_id = item_id if isinstance(item_id, str) and item_id else None
        # Canonical app-server events and their legacy aliases carry the same coordinates.
        for kind, camel, snake in (("summary", "summaryIndex", "summary_index"),
                                   ("content", "contentIndex", "content_index")):
            index = params.get(camel, params.get(snake))
            if source_id and isinstance(index, int) and not isinstance(index, bool) and index >= 0:
                source_id = f"{item_id}:{kind}:{index}"
                break
        if source_id:
            if previous_reasoning_source is not None and source_id != previous_reasoning_source:
                text = "\\n\\n" + text
            previous_reasoning_source = source_id
        callback = getattr(agent, "reasoning_event_callback", None)
        if source_id and callback is not None:
            try:
                delivery = getattr(agent, "_fire_reasoning_event", None) or callback
                if source_id != item_id:
                    sources = reasoning_sources.setdefault(item_id, [])
                    if source_id not in sources:
                        delivery("start", source_id, "")
                        sources.append(source_id)
                delivery("delta", source_id, text)
                return
            except Exception:
                logger.debug("reasoning_event_callback raised", exc_info=True)
        agent_cb("_fire_reasoning_delta", "_fire_reasoning_delta raised", args=(text,))

    def _fire_reasoning_item_event(event: str, item: dict) -> None:
        nonlocal active_reasoning_item_id
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id:
            return
        if event == "start":
            active_reasoning_item_id = item_id
        elif event == "end" and active_reasoning_item_id == item_id:
            active_reasoning_item_id = None
        ended_sources = reasoning_sources.pop(item_id, []) if event == "end" else []
        callback = getattr(agent, "reasoning_event_callback", None)
        if callback is None:
            return
        delivery = getattr(agent, "_fire_reasoning_event", None) or callback
        for source_id in [*ended_sources, item_id]:
            _call_guarded(delivery, "reasoning_event_callback raised", args=(event, source_id, ""))

''' + text[end:]
    return text


def patch_parts(text):
    text = replace(text,
        "  timestamp?: number\n): { index: number; parts: ChatMessagePart[] } {",
        "  timestamp?: number,\n  sourceId?: string\n): { index: number; parts: ChatMessagePart[] } {")
    text = replace(text,
        "  if (tail?.type === type && tail.completedAt === undefined) {",
        "  if (tail?.type === type && tail.completedAt === undefined && (tail.type !== 'reasoning' || tail.sourceId === sourceId)) {")
    text = replace(text,
        "  const STREAM_PART: Record<'reasoning' | 'text', (text: string, timestamp?: number) => ChatMessagePart> = {",
        "  const STREAM_PART: Record<'reasoning' | 'text', (text: string, timestamp?: number, sourceId?: string) => ChatMessagePart> = {")
    text = replace(text, "  next.push(STREAM_PART[type](delta, timestamp))", "  next.push(STREAM_PART[type](delta, timestamp, sourceId))")
    start = text.index("  if (sourceId) {", text.index("export function appendReasoningPart("))
    end = text.index("\n}\n", start)
    return text[:start] + "  return appendStreamPart(parts, 'reasoning', delta, timestamp, sourceId).parts" + text[end:]


def install_tests():
    for target, source in [(PYTEST, "workbench/pr120894_segments_test.py"), (TSTEST, "workbench/pr120894_boundary_test.ts")]:
        (CANDIDATE / target).write_text((ROOT / source).read_text())


def patch_sources():
    for path, patch in [("agent/codex_runtime.py", patch_runtime), ("apps/desktop/src/lib/chat-messages/parts.ts", patch_parts)]:
        file = CANDIDATE / path
        file.write_text(patch(file.read_text()))
    file = CANDIDATE / "tests/agent/test_run_agent_codex_responses.py"
    file.write_text(replace(file.read_text(), '("delta", "rs_first:summary:1", "Checking"),', '("delta", "rs_first:summary:1", "\\n\\nChecking"),'))
    file = CANDIDATE / "apps/desktop/src/lib/chat-messages.reasoning-identity.test.ts"
    text = replace(file.read_text(), "        boundary,\n        reasoningPart('After', 3, 'rs')", "        boundary.type === 'text' ? { ...boundary, completedAt: 3 } : boundary,\n        reasoningPart('After', 3, 'rs')")
    text = replace(text, "toEqual([first, reasoningPart('Legacy', 3)])", "toEqual([{ ...first, completedAt: 3 }, reasoningPart('Legacy', 3)])")
    file.write_text(text)


def prove_red():
    xml = OUT / "review-before.xml"
    red = run("bash", "scripts/run_tests.sh", PYTEST, "--file-retries", "0", "-q", "--tb=short", f"--junitxml={xml}", cwd=CANDIDATE, log="review-before.log", check=False)
    root = ET.parse(xml).getroot()
    if not red.returncode or not root.findall(".//failure") or root.findall(".//error"):
        raise RuntimeError("Expected behavioral baseline failures, not a harness/collection error")
    js = OUT / "timeline-before.json"
    red = run("npx", "--no-install", "vitest", "run", "src/lib/chat-messages.reasoning-boundary.test.ts", "--reporter=default", "--reporter=json", f"--outputFile={js}", cwd=CANDIDATE / "apps/desktop", log="timeline-before.log", check=False)
    if not red.returncode or not json.loads(js.read_text()).get("numFailedTests"):
        raise RuntimeError("Timeline regression did not fail behaviorally before the fix")


def verify():
    run(sys.executable, "scripts/gen_gateway_contracts.py", cwd=CANDIDATE, log="generate-contracts.log")
    changed = run("git", "diff", "--name-only", BASE, cwd=CANDIDATE).stdout.splitlines()
    tsfiles = [p for p in changed if p.startswith("apps/desktop/") and p.endswith((".ts", ".tsx"))] + [TSTEST]
    relative = [p.removeprefix("apps/desktop/") for p in tsfiles]
    run("npx", "--no-install", "prettier", "--write", *relative, cwd=CANDIDATE / "apps/desktop", log="format.log")
    paths = sorted({p for p in changed if p.startswith("tests/") and p.endswith(".py")} | {PYTEST,
        "tests/agent/test_codex_responses_adapter.py", "tests/agent/test_codex_reasoning_only_streak.py",
        "tests/agent/test_codex_incomplete_budget_escalation.py", "tests/agent/transports/test_codex_transport.py"})
    paths = [p for p in paths if (CANDIDATE / p).exists()]
    paths += [str(p.relative_to(CANDIDATE)) for pattern in ("*inline*reasoning*.py", "*think*stream*.py", "*stream*think*.py") for p in (CANDIDATE / "tests/agent").glob(pattern)]
    paths.append("tests/tui_gateway/contracts")
    run("bash", "scripts/run_tests.sh", *dict.fromkeys(paths), "--file-retries", "0", "-q", "--tb=short", cwd=CANDIDATE, log="python-matrix.log")
    run("bash", "scripts/run_tests.sh", PYTEST, "--file-retries", "0", "-q", "--tb=short", f"--junitxml={OUT / 'review-after.xml'}", cwd=CANDIDATE, log="review-after.log")
    desktop = CANDIDATE / "apps/desktop"
    js = [str(p.relative_to(desktop)) for p in (desktop / "src/lib").glob("chat-messages*.test.ts")]
    js += ["src/app/session/hooks/use-message-stream", "src/app/session/hooks/use-prompt-actions/steering-recovery.test.tsx"]
    run("npx", "--no-install", "vitest", "run", *js, "--reporter=default", "--reporter=json", f"--outputFile={OUT / 'desktop-after.json'}", cwd=desktop, log="desktop-matrix.log")
    run("npm", "run", "typecheck", cwd=desktop, log="typecheck.log")
    run("npx", "--no-install", "eslint", "--max-warnings", "0", *relative, cwd=desktop, log="eslint.log")
    run(sys.executable, "-m", "py_compile", "agent/codex_runtime.py", "agent/stream_delivery.py", PYTEST, cwd=CANDIDATE, log="compile.log")
    run(sys.executable, "-m", "ruff", "check", "--select", "F821,F822,F823", "agent/codex_runtime.py", "agent/stream_delivery.py", PYTEST, cwd=CANDIDATE, log="ruff.log")
    run("git", "diff", "--check", cwd=CANDIDATE, log="diffcheck.log")
    run("npm", "run", "build", cwd=desktop, log="desktop-build.log", timeout=1200)
    run("xvfb-run", "-a", "npx", "--no-install", "playwright", "test", "e2e/codex-commentary-hydration.spec.ts", "--workers=1", "--reporter=line", cwd=desktop, log="electron.log", timeout=600)


def finish():
    # Workbench files and install/build outputs must not leak into the product commit.
    before = set(run("git", "diff", "--name-only", COMMON, OLD).stdout.splitlines())
    allowed = before | {PYTEST, TSTEST}
    current = set(run("git", "diff", "--name-only", BASE, cwd=CANDIDATE).stdout.splitlines())
    if current - allowed:
        raise RuntimeError(f"Unexpected tracked modifications: {current - allowed}")
    run("git", "add", *sorted(allowed), cwd=CANDIDATE)
    run("git", "commit", "-m", "fix(codex): preserve reasoning section boundaries across consumers", "-m", "Address BearHuddleston's flat-consumer separator finding and andrexibiza's timeline lifecycle finding. Keep current-main app-server liveness and canonical event methods, retain summary coordinates and matching end events, and exercise the actual gateway and plugin observer paths. Original contributor lineage is preserved by rebase.", cwd=CANDIDATE)
    head = run("git", "rev-parse", "HEAD", cwd=CANDIDATE).stdout.strip()
    (OUT / "head.txt").write_text(head + "\n")
    run("git", "diff", BASE, "HEAD", cwd=CANDIDATE, log="final.diff")
    run("git", "diff", "--stat", BASE, "HEAD", cwd=CANDIDATE, log="final.stat")
    # Check the explicit companion composition without absorbing that PR into this one.
    run("git", "fetch", "--no-tags", "origin", "c1a2b924d668d8a472996c3055b5677f91aacd04")
    combined = Path(os.environ["RUNNER_TEMP"]) / "pr120894-with-continuation"
    run("git", "worktree", "add", "--detach", str(combined), head)
    run("git", "cherry-pick", "4ad4f8d977724393d10c3295fb71ed439259bbac", "c1a2b924d668d8a472996c3055b5677f91aacd04", cwd=combined, log="companion-composition.log")
    run("bash", "scripts/run_tests.sh", "tests/agent/test_codex_reasoning_only_streak.py", "tests/agent/test_codex_incomplete_budget_escalation.py", "tests/agent/test_codex_commentary_channels.py", PYTEST, "--file-retries", "0", "-q", "--tb=short", cwd=combined, log="companion-tests.log")
    # A rebase is an explicitly requested non-fast-forward update; guard concurrent work.
    actual = run("git", "ls-remote", "origin", f"refs/heads/{BRANCH}").stdout.split()[0]
    if actual != OLD:
        raise RuntimeError(f"PR advanced concurrently ({actual}); leaving its branch unchanged")
    run("git", "push", "origin", f"{OLD}:refs/heads/archive/pr120894-before-rebase-b0936c34", cwd=CANDIDATE, log="backup.log")
    run("git", "push", f"--force-with-lease=refs/heads/{BRANCH}:{OLD}", "origin", f"HEAD:refs/heads/{BRANCH}", cwd=CANDIDATE, log="publish.log")
    print("VERIFIED_AND_PUBLISHED", head, "BASE", BASE, flush=True)


def main():
    rebase()
    install_tests()
    run("npm", "ci", cwd=CANDIDATE, log="npm-ci.log", timeout=1200)
    prove_red()
    patch_sources()
    verify()
    finish()


if __name__ == "__main__":
    main()
