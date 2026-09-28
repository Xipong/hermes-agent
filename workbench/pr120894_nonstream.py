"""Fork-only orchestration. Product history is published only after all gates pass."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
OUT = Path(os.environ["RUNNER_TEMP"]) / "pr120894-evidence"
OUT.mkdir(exist_ok=True)
CANDIDATE = Path(os.environ["RUNNER_TEMP"]) / "pr120894-candidate"
BASE = "7dbbb0f4a6ebeec9a8714ec37fa41340fe9e4e00"
COMMON = "59004a62356f3a4697ab0fe8ad5086d2b405e2a6"
OLD = "d39d5cf86a1a51cd86f97e23271291143f242a6e"
BRANCH = "fix/codex-output-continuity"
TEST = "tests/tui_gateway/test_native_reasoning_segments.py"
HELPER = "agent/chat_completion_helpers.py"


def run(*args, cwd=ROOT, log=None, check=True, timeout=1200):
    print("RUN", str(cwd), args, flush=True)
    result = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=timeout,
                            env={**os.environ, "GIT_EDITOR": ":", "GIT_SEQUENCE_EDITOR": ":"})
    if log:
        (OUT / log).write_text(result.stdout)
    print(result.stdout[-22000:], flush=True)
    if check and result.returncode:
        raise RuntimeError(f"Command returned {result.returncode}: {args}")
    return result


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one exact patch anchor, got {text.count(old)}: {old[:100]!r}")
    return text.replace(old, new, 1)


def resolve_rebase():
    paths = run("git", "diff", "--name-only", "--diff-filter=U", cwd=CANDIDATE).stdout.splitlines()
    run("git", "diff", "--cc", cwd=CANDIDATE, log="rebase-conflicts.diff")
    pattern = re.compile(r"^<<<<<<< [^\n]*\n(.*?)^=======\n(.*?)^>>>>>>> [^\n]*\n", re.M | re.S)
    for path in paths:
        file = CANDIDATE / path
        copy = OUT / "conflicts" / path
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(file.read_text())
        def resolve(match):
            ours, theirs = match.groups()
            if (path == "tui_gateway/agent_callbacks.py"
                and ours.strip() == '"reasoning_callback": lambda text: _emit_reasoning_delta(sid, text),'
                and '"reasoning_event_callback": _reasoning_event,' in theirs
                and '"reasoning.delta", sid,' in theirs):
                return ours + '        "reasoning_event_callback": _reasoning_event,\n'
            raise RuntimeError(f"Unreviewed conflict in {path}:\nOURS\n{ours}\nTHEIRS\n{theirs}")
        text, count = pattern.subn(resolve, file.read_text())
        if not count or any(marker in text for marker in ("<<<<<<< ", ">>>>>>> ")):
            raise RuntimeError(f"Unresolved conflicts: {path}")
        if path == "tui_gateway/agent_callbacks.py":
            # Main's display gate applies to the new identified lane too, including lifecycle events.
            text = replace(text,
                '    def _reasoning_event(phase: str, item_id: str, text: str = "") -> bool:\n        payload =',
                '    def _reasoning_event(phase: str, item_id: str, text: str = "") -> bool:\n        if not _session_show_reasoning(sid):\n            return False\n        payload =')
        file.write_text(text)
        run("git", "add", path, cwd=CANDIDATE)
    if not paths:
        raise RuntimeError("Rebase stopped without a reviewed content conflict")


def prepare():
    run("git", "fetch", "--no-tags", "--depth=64", "origin", OLD)
    run("git", "cat-file", "-e", f"{COMMON}^{{commit}}")
    run("git", "fetch", "--no-tags", "--depth=1", "https://github.com/NousResearch/hermes-agent.git", BASE)
    run("git", "config", "user.name", "Xipong")
    run("git", "config", "user.email", "217837358+Xipong@users.noreply.github.com")
    run("git", "worktree", "add", "--detach", str(CANDIDATE), OLD)
    result = run("git", "rebase", "--reapply-cherry-picks", "--empty=keep", "--onto", BASE, COMMON,
                 cwd=CANDIDATE, check=False, log="rebase-start.log")
    for _ in range(20):
        if result.returncode == 0:
            break
        resolve_rebase()
        result = run("git", "rebase", "--continue", cwd=CANDIDATE, check=False)
    if result.returncode:
        raise RuntimeError("Rebase did not finish")
    before = run("git", "log", "--reverse", "--format=%an <%ae>%n%B", f"{COMMON}..{OLD}").stdout
    after = run("git", "log", "--reverse", "--format=%an <%ae>%n%B", f"{BASE}..HEAD", cwd=CANDIDATE).stdout
    if before != after:
        raise RuntimeError("Contributor names, emails or commit messages changed")
    (OUT / "preserved-lineage.txt").write_text(after)
    run("git", "range-diff", f"{COMMON}..{OLD}", f"{BASE}..HEAD", cwd=CANDIDATE, log="rebase-range.diff")
    (OUT / "rebased-head.txt").write_text(run("git", "rev-parse", "HEAD", cwd=CANDIDATE).stdout)
    test = CANDIDATE / TEST
    test.write_text(replace(test.read_text(),
        '{"verbose": False}', '{"verbose": False, "show_reasoning": True}').rstrip()
        + (ROOT / "workbench/pr120894_nonstream_tests.py").read_text())


def test_report(path):
    root = ET.parse(path).getroot()
    return {key: len(root.findall(f".//{tag}")) for key, tag in
            [("tests", "testcase"), ("failures", "failure"), ("errors", "error"), ("skipped", "skipped")]}


def verify():
    # Build against the candidate's own committed dependency lock, not the workbench lock.
    run(sys.executable, "-m", "pm.build_env", "--source", str(CANDIDATE), "--out", str(CANDIDATE / ".venv"),
        "--group", "dev", "--group", "test", "--extra", "all", "--extra", "anthropic",
        cwd=CANDIDATE, log="candidate-python-environment.log")
    python = str(CANDIDATE / ".venv/bin/python")
    os.environ["HERMES_PYTHON"] = python
    os.environ["HERMES_DESKTOP_PYTHON"] = python
    # The control uses main's own helper/delivery code, with only flat callback cases selected.
    baseline = Path(os.environ["RUNNER_TEMP"]) / "pr120894-main-control"
    run("git", "worktree", "add", "--detach", str(baseline), BASE)
    (baseline / TEST).write_text((CANDIDATE / TEST).read_text())
    run("bash", "scripts/run_tests.sh", TEST, "-k", "nonstream_reemit_preserves_flat_text_and_native_identity and False",
        "--file-retries", "0", "-q", "--tb=short", f"--junitxml={OUT / 'main-control.xml'}",
        cwd=baseline, log="main-control.log")
    red = run("bash", "scripts/run_tests.sh", TEST, "-k", "nonstream_reemit", "--file-retries", "0",
              "-q", "--tb=short", f"--junitxml={OUT / 'nonstream-before.xml'}", cwd=CANDIDATE,
              check=False, log="nonstream-before.log")
    report = test_report(OUT / "nonstream-before.xml")
    if not red.returncode or report["failures"] != 3 or report["errors"] or report["tests"] != 10:
        raise RuntimeError(f"Expected precisely three native multi-part behavioral failures, got {report}")

    helper = CANDIDATE / HELPER
    text = replace(helper.read_text(), '''    for item in native:
        for index, part in enumerate(item["summary"]):
            source_id = f"{item['id']}:summary:{index}"
            delivery("start", source_id, "")
            delivery("delta", source_id, part["text"])
            delivery("end", source_id, "")
''', '''    # Preserve the exact flat view validated by native_reasoning_items: one
    # newline within an item, two between items. Identified consumers need it too.
    for item_index, item in enumerate(native):
        for index, part in enumerate(item["summary"]):
            source_id = f"{item['id']}:summary:{index}"
            separator = "\\n" if index else ("\\n\\n" if item_index else "")
            delivery("start", source_id, "")
            delivery("delta", source_id, separator + part["text"])
            delivery("end", source_id, "")
''')
    helper.write_text(text)
    run("bash", "scripts/run_tests.sh", TEST, "--file-retries", "0", "-q", "--tb=short",
        f"--junitxml={OUT / 'nonstream-after.xml'}", cwd=CANDIDATE, log="nonstream-after.log")

    run(python, "scripts/gen_gateway_contracts.py", cwd=CANDIDATE, log="generate-contracts.log")
    changed = run("git", "diff", "--name-only", BASE, cwd=CANDIDATE).stdout.splitlines()
    pytests = {path for path in changed if path.startswith("tests/") and path.endswith(".py")}
    pytests.update({TEST, "tests/agent/test_codex_responses_adapter.py",
                   "tests/agent/test_codex_reasoning_only_streak.py",
                   "tests/agent/test_codex_incomplete_budget_escalation.py",
                   "tests/agent/transports/test_codex_transport.py",
                   "tests/agent/test_stream_delivery.py", "tests/tui_gateway/contracts"})
    for pattern in ("*inline*reasoning*.py", "*think*stream*.py", "*stream*think*.py"):
        pytests.update(str(path.relative_to(CANDIDATE)) for path in (CANDIDATE / "tests/agent").glob(pattern))
    for pattern in ("*reasoning*.py", "*display*.py"):
        pytests.update(str(path.relative_to(CANDIDATE)) for path in (CANDIDATE / "tests/tui_gateway").glob(pattern))
    pytests = sorted(path for path in pytests if (CANDIDATE / path).exists())
    (OUT / "python-test-paths.json").write_text(json.dumps(pytests, indent=2))
    run("bash", "scripts/run_tests.sh", *pytests, "--file-retries", "0", "-q", "--tb=short",
        cwd=CANDIDATE, log="python-matrix.log")
    python_files = [path for path in changed if path.endswith(".py")]
    run(python, "-m", "py_compile", *python_files, cwd=CANDIDATE, log="compile.log")
    run(python, "-m", "ruff", "check", "--select", "F63,F7,F821,F822,F823", HELPER, TEST, "agent/codex_runtime.py", "agent/stream_delivery.py",
        cwd=CANDIDATE, log="ruff.log")

    run("npm", "ci", cwd=CANDIDATE, log="npm-ci.log")
    desktop = CANDIDATE / "apps/desktop"
    js = [str(path.relative_to(desktop)) for path in (desktop / "src/lib").glob("chat-messages*.test.ts")]
    js += ["src/app/session/hooks/use-message-stream", "src/app/session/hooks/use-prompt-actions/steering-recovery.test.tsx"]
    run("npx", "--no-install", "vitest", "run", *js, "--reporter=default", "--reporter=json",
        f"--outputFile={OUT / 'desktop-after.json'}", cwd=desktop, log="desktop-matrix.log")
    run("npm", "run", "typecheck", cwd=desktop, log="typecheck.log")
    tsfiles = [path.removeprefix("apps/desktop/") for path in changed
               if path.startswith("apps/desktop/") and path.endswith((".ts", ".tsx"))]
    run("npx", "--no-install", "eslint", "--max-warnings", "0", *tsfiles, cwd=desktop, log="eslint.log")
    run("npx", "--no-install", "prettier", "--check", *tsfiles, cwd=desktop, log="prettier.log")
    run("git", "diff", "--check", BASE, cwd=CANDIDATE, log="diffcheck.log")
    run("npm", "run", "build", cwd=desktop, log="desktop-build.log")
    run("xvfb-run", "-a", "npx", "--no-install", "playwright", "test",
        "e2e/codex-commentary-hydration.spec.ts", "--workers=1", "--reporter=line",
        cwd=desktop, log="electron.log", timeout=600)


def publish():
    allowed = set(run("git", "diff", "--name-only", COMMON, OLD).stdout.splitlines())
    changed = set(run("git", "diff", "--name-only", BASE, cwd=CANDIDATE).stdout.splitlines())
    if changed - allowed:
        raise RuntimeError(f"Unexpected product scope: {changed - allowed}")
    # Explicit tracked paths only: no workbench, interpreter, fixtures or build output.
    run("git", "add", *sorted(changed), cwd=CANDIDATE)
    run("git", "commit", "-m", "fix(codex): preserve separators in non-streaming reasoning re-emission", "-m",
        "Address Enough1122's review on #120894: native summary re-emission must reconstruct the exact validated flat reasoning string, with one newline within an item and two between items. Exercise the non-streaming helper through the real gateway callbacks and stream delivery owner, plugin observations, legacy fallback, invalid sidecars and repeated delivery. Preserve original contributor lineage across the main rebase.", cwd=CANDIDATE)
    head = run("git", "rev-parse", "HEAD", cwd=CANDIDATE).stdout.strip()
    run("git", "merge-base", "--is-ancestor", BASE, head, cwd=CANDIDATE)
    run("git", "diff", BASE, head, cwd=CANDIDATE, log="final.diff")
    run("git", "diff", "--stat", BASE, head, cwd=CANDIDATE, log="final.stat")
    run("git", "show", "--format=fuller", "HEAD", cwd=CANDIDATE, log="review-fix.diff")
    actual = run("git", "ls-remote", "origin", f"refs/heads/{BRANCH}").stdout.split()[0]
    if actual != OLD:
        raise RuntimeError(f"PR changed concurrently to {actual}; product branch was not updated")
    run("git", "push", "origin", f"{OLD}:refs/heads/archive/pr120894-before-rebase-d39d5cf8",
        cwd=CANDIDATE, log="backup.log")
    run("git", "push", f"--force-with-lease=refs/heads/{BRANCH}:{OLD}", "origin", f"HEAD:refs/heads/{BRANCH}",
        cwd=CANDIDATE, log="publish.log")
    remote = run("git", "ls-remote", "origin", f"refs/heads/{BRANCH}").stdout.split()[0]
    if remote != head:
        raise RuntimeError(f"Remote head {remote} does not match verified head {head}")
    receipt = {"head": head, "base": BASE, "previous_head": OLD,
               "main_control": test_report(OUT / "main-control.xml"),
               "before": test_report(OUT / "nonstream-before.xml"),
               "after": test_report(OUT / "nonstream-after.xml")}
    (OUT / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print("VERIFIED_AND_PUBLISHED", json.dumps(receipt), flush=True)


if __name__ == "__main__":
    prepare()
    verify()
    publish()
