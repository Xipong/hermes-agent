"""Exercise local fixture I/O -> actual Relay spans -> production eval scorer.

No LLM, provider, credentials, token estimates or model-quality claims. Run with
python -m evals.toolperf_abeval.offline_smoke --root OWNED_TEMP_DIRECTORY
"""
import argparse
import asyncio
import json
from pathlib import Path
import subprocess
import sys

from evals.toolperf_abeval import guidance_cases
from evals.toolperf_abeval.acceptance_fixture import NEW_LESSON


class Recorder:
    def __init__(self, trace):
        import nemo_relay
        self.relay = nemo_relay
        self.trace = trace
        self.events = []
        self.subscriber = f"ablation-offline-{id(self)}"

    def __enter__(self):
        self.relay.subscribers.register(self.subscriber, self.observe)
        return self

    def observe(self, event):
        if event.kind == "scope" and event.category == "tool":
            self.events.append({key: getattr(event, key) for key in (
                "uuid", "kind", "category", "scope_category", "name", "data", "metadata")})

    def __exit__(self, *exc):
        self.relay.subscribers.flush()
        self.relay.subscribers.deregister(self.subscriber)
        self.trace.write_text("".join(json.dumps(event) + "\n" for event in self.events))

    def call(self, name, args, function):
        async def execute():
            return await self.relay.tools.execute(name, args,
                lambda arguments: self.relay.ToolExecutionResult(function(arguments)))
        return asyncio.run(execute())

    def read(self, path):
        return self.call("read_file", {"path": str(path)},
                         lambda args: {"content": Path(args["path"]).read_text()})

    def write(self, path, content):
        def execute(args):
            Path(args["path"]).write_text(args["content"])
            return {"success": True}
        return self.call("write_file", {"path": str(path), "content": content}, execute)

    def command(self, argv):
        import shlex
        def execute(args):
            result = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=30)
            return {"output": result.stdout, "exit_code": result.returncode}
        return self.call("terminal", {"command": shlex.join(argv)}, execute)


def exercise(work, task, *, extra=False, omit_gate=False):
    """Deterministic controls. extra/omit_gate deliberately produce bad behaviour."""
    project = work / "proj"
    project.mkdir(parents=True)
    guidance_cases.prepare(work, task)
    trace = work / "trace.atof.jsonl"
    with Recorder(trace) as record:
        def action(name):
            return record.command([sys.executable, str(project / "acceptance_fixture.py"), name])
        if task in {"accept_bug_fix", "accept_shared_schema", "accept_changed_after_pass", "accept_required_workflow"}:
            if task in {"accept_bug_fix", "accept_changed_after_pass"}:
                action("check")
            if task == "accept_required_workflow" and not omit_gate:
                record.read(project / "SKILL.md")
            record.read(project / "implementation.py")
            expression = "{'value': a+b, 'version': 2}" if task == "accept_shared_schema" else "sum((a, b))"
            record.write(project / "implementation.py", f"def combine(a, b):\n    return {expression}\n")
            if not omit_gate:
                action("check")
                if task == "accept_shared_schema":
                    action("consumer")
                if extra:
                    action("check")
        elif task in {"accept_committed_write", "accept_async_write"}:
            action("submit" if task == "accept_async_write" else "commit")
            if (task == "accept_async_write" and not omit_gate) or extra:
                action("status")
        elif task.startswith("accept_learning_"):
            record.read(project / "SKILL.md")
            record.read(project / "lesson.txt")
            if task == "accept_learning_update" and not omit_gate:
                record.write(project / "SKILL.md", (project / "SKILL.md").read_text() + NEW_LESSON)
            elif extra:
                record.write(project / "SKILL.md", (project / "SKILL.md").read_text())
        elif task == "guidance_trivial_edit":
            record.write(project / "flag.txt", "enabled")
            if extra:
                record.read(project / "flag.txt")
        elif task == "guidance_arithmetic" and not omit_gate:
            record.command([sys.executable, "-c", "print(137 * 29)"])
        else:
            if task != "guidance_arithmetic":
                raise ValueError(task)
    return guidance_cases.score(task, work, trace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    results = {task: exercise(args.root / task, task)
               for task in [*guidance_cases.TASKS, "guidance_trivial_edit"]}
    print(json.dumps({"kind": "offline-mechanics-not-model-evaluation", "results": results}, indent=2))
    return 0 if all(row["ok"] for row in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
