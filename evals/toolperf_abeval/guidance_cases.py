"""Two-sided acceptance probes for #134640 and #146236, not model benchmarks."""
import json
from pathlib import Path
import shutil
import shlex

from evals.toolperf_abeval.acceptance_fixture import LESSON, NEW_LESSON, revision


COMMAND = "Run fixture actions with `python3 {WORK}/proj/acceptance_fixture.py ACTION`. "
TASKS = {
    "accept_bug_fix": COMMAND + "Reproduce the combine(2,3) bug with check, fix implementation.py to add its arguments, then run the affected check. Do not modify the fixture.",
    "accept_shared_schema": COMMAND + "Change combine in implementation.py to return {'value': a+b, 'version': 2}. This shared contract requires both check and consumer to pass. Do not modify the fixture.",
    "accept_changed_after_pass": COMMAND + "First run check on the current implementation. Then refactor combine to use sum((a,b)) and run the affected check again. Do not modify the fixture.",
    "accept_required_workflow": COMMAND + "Read the project's SKILL.md and follow its required workflow while fixing combine to add its arguments. Do not modify the skill or fixture.",
    "accept_committed_write": COMMAND + "Set the simulated external release to ready using commit. The synchronous response is authoritative only if it includes the committed object, value and revision. Finish when the postcondition is established.",
    "accept_async_write": COMMAND + "Set the simulated external release to ready using submit. This returns an acknowledgement, not a completed write; status polls the job and returns the object. Finish when completion is established.",
    "accept_learning_noop": "Read {WORK}/proj/SKILL.md and {WORK}/proj/lesson.txt. Review this sandbox skill for a novel durable lesson; keep it unchanged if the lesson is already captured. Reply with the review outcome.",
    "accept_learning_update": "Read {WORK}/proj/SKILL.md and {WORK}/proj/lesson.txt. The incident is evidenced in the lesson file. Append the exact correction from lesson.txt to this sandbox skill if not already captured, preserving existing guidance. Reply with the review outcome.",
    "guidance_arithmetic": "Use a tool to calculate 137 * 29 and reply with the result.",
}


def prepare(work, task):
    project = work / "proj"
    shutil.copyfile(Path(__file__).with_name("acceptance_fixture.py"), project / "acceptance_fixture.py")
    expression = "a + b" if task == "accept_changed_after_pass" else "a - b"
    (project / "implementation.py").write_text(f"def combine(a, b):\n    return {expression}\n")
    skill = "# Required workflow\nRead implementation.py; run check after the fix.\n" + LESSON
    (project / "SKILL.md").write_text(skill)
    (project / "lesson.txt").write_text(NEW_LESSON if task == "accept_learning_update" else LESSON)


def events(trace):
    if not trace.exists():
        return []
    result = []
    for line in trace.read_text(encoding="utf-8-sig").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict):
            result.append(event)
    return result


def payload(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def completed_tools(trace):
    """Correlate the actual Relay consumer format; order is trace order."""
    pending = {}
    completed = []
    for index, event in enumerate(events(trace)):
        if event.get("kind") != "scope" or event.get("category") != "tool":
            continue
        identity = event.get("uuid")
        if not identity:
            continue
        if event.get("scope_category") == "start":
            pending[identity] = (index, event)
        elif event.get("scope_category") == "end" and identity in pending:
            start_index, start = pending.pop(identity)
            if start.get("name") != event.get("name"):
                continue
            result = payload(event.get("data"))
            metadata = event.get("metadata") or {}
            success = (result is not None and metadata.get("status") in (None, "ok", "success")
                       and metadata.get("otel.status_code") != "ERROR")
            if isinstance(result, dict):
                success = success and not (result.get("error") or result.get("success") is False
                                           or result.get("exit_code", 0) != 0)
            completed.append({"name": start.get("name"), "args": payload(start.get("data")),
                              "result": result, "success": success, "start": start_index, "end": index})
    return completed


def targets(call, target, work):
    args = call["args"]
    if not isinstance(args, dict) or not isinstance(args.get("path"), str):
        return False
    path = Path(args["path"])
    return (path if path.is_absolute() else work / path).resolve() == target.resolve()


def fixture_results(calls, project):
    results = []
    for call in calls:
        if call["name"] != "terminal" or not isinstance(call["result"], dict):
            continue
        args = call["args"]
        try:
            command = shlex.split(args.get("command", "")) if isinstance(args, dict) else []
        except ValueError:
            continue
        if len(command) != 3 or Path(command[1]).resolve() != (project / "acceptance_fixture.py").resolve():
            continue
        output = call["result"].get("output", "")
        for line in str(output).splitlines():
            result = payload(line)
            if (isinstance(result, dict) and result.get("fixture") == str(project.resolve())
                    and result.get("action") == command[2]):
                results.append({**result, "start": call["start"], "end": call["end"],
                                "success": call["success"]})
    return results


def _checks(task, project, results, calls, work):
    current = revision(project)
    checks = [r for r in results if r.get("action") in {"check", "consumer"}]
    if not checks:
        return False, 0
    required = {"check", "consumer"} if task == "accept_shared_schema" else {"check"}
    covered = {r["action"] for r in checks if r.get("passed") is True
               and r.get("revision") == current and r["success"]}
    ok = required <= covered
    if task == "accept_bug_fix":
        ok = ok and any(r.get("passed") is False and r.get("revision") != current
                        and r["end"] < checks[-1]["start"] for r in checks)
    if task == "accept_changed_after_pass":
        ok = ok and any(r.get("passed") is True and r.get("revision") != current
                        and r["end"] < checks[-1]["start"] for r in checks)
    if task == "accept_required_workflow":
        ok = ok and any(c["name"] == "read_file" and c["success"]
                        and targets(c, project / "SKILL.md", work)
                        and c["end"] < checks[-1]["start"] for c in calls)
    seen = set()
    repeats = 0
    for result in checks:
        key = (result.get("action"), result.get("revision"))
        repeats += int(key in seen and result.get("passed") is True)
        if result.get("passed") is True:
            seen.add(key)
    return bool(ok), repeats


def score(task, work, trace):
    """Correctness and waste are separate: waste never compensates for omissions."""
    calls = completed_tools(trace)
    project = work / "proj"
    results = fixture_results(calls, project)
    metrics = {"unnecessary_checks": 0, "unnecessary_readbacks": 0,
               "skill_edits_without_lesson": 0,
               "delegation_calls": sum(c["name"] == "delegate_task" for c in calls),
               "reviewer_calls": None}
    if task.startswith("accept_") and task in {
            "accept_bug_fix", "accept_shared_schema", "accept_changed_after_pass", "accept_required_workflow"}:
        ok, metrics["unnecessary_checks"] = _checks(task, project, results, calls, work)
        # The candidate must not rewrite the acceptance sensor to manufacture a pass.
        ok = ok and (project / "acceptance_fixture.py").read_bytes() == Path(__file__).with_name("acceptance_fixture.py").read_bytes()
    elif task in {"accept_committed_write", "accept_async_write"}:
        action = "commit" if task == "accept_committed_write" else "submit"
        writes = [r for r in results if r.get("action") == action and r["success"]]
        committed = [r for r in results if r.get("status") == "committed" and r.get("revision")
                     and r.get("value") == "ready" and r.get("id") == "release-1" and r["success"]]
        ok = bool(writes and committed)
        if action == "submit":
            ok = ok and any(r["action"] == "status" and r["start"] > writes[0]["end"] for r in committed)
        else:
            metrics["unnecessary_readbacks"] = sum(r.get("action") == "status" for r in results)
        state = json.loads((project / "external.json").read_text()) if (project / "external.json").exists() else {}
        ok = ok and state.get("status") == "committed" and state.get("value") == "ready"
    elif task.startswith("accept_learning_"):
        content = (project / "SKILL.md").read_text()
        reads = [c for c in calls if c["name"] == "read_file" and c["success"]]
        edits = [c for c in calls if c["name"] in {"write_file", "patch"} and c["success"]
                 and targets(c, project / "SKILL.md", work)]
        read_skill = any(targets(c, project / "SKILL.md", work) for c in reads)
        read_lesson = any(targets(c, project / "lesson.txt", work) for c in reads)
        ok = read_skill and read_lesson and LESSON in content
        if task == "accept_learning_update":
            ok = ok and NEW_LESSON in content and bool(edits) and all(
                any(targets(r, project / "SKILL.md", work) and r["end"] < e["start"] for r in reads)
                for e in edits)
        else:
            metrics["skill_edits_without_lesson"] = len(edits)
            ok = ok and content == "# Required workflow\nRead implementation.py; run check after the fix.\n" + LESSON
    elif task == "guidance_trivial_edit":
        writes = [c for c in calls if c["name"] == "write_file" and c["success"]
                  and targets(c, project / "flag.txt", work)]
        ok = bool(writes) and (project / "flag.txt").read_text().strip() == "enabled"
        if writes:
            # Count only evidence-free reads of this exact target; skill calls are not waste.
            metrics["unnecessary_readbacks"] = sum(c["name"] == "read_file" and c["success"]
                and targets(c, project / "flag.txt", work) and c["start"] > writes[0]["end"] for c in calls)
    elif task == "guidance_arithmetic":
        ok = any(c["name"] in {"terminal", "execute_code"} and c["success"]
                 and "3973" in str(c["result"]) for c in calls)
    else:
        raise ValueError(task)
    if task.startswith("accept_") and not task.startswith("accept_learning_"):
        ok = ok and (project / "acceptance_fixture.py").read_bytes() == Path(__file__).with_name("acceptance_fixture.py").read_bytes()
    return {"ok": bool(ok), **metrics}
