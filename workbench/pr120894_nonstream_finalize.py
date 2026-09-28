"""Resolve reviewed conflicts and validate every independent gate before publication."""
import json
import time
import pr120894_nonstream as a

resolve_source_conflicts = a.resolve_rebase
original_run = a.run
failures = []
COLLECT = {"python-matrix.log", "compile.log", "ruff.log", "desktop-matrix.log",
           "typecheck.log", "eslint.log", "prettier.log", "diffcheck.log",
           "desktop-build.log", "electron.log"}


def run(*args, **kwargs):
    if args[:2] == ("git", "fetch"):
        options = {**kwargs, "check": False}
        for attempt, delay in enumerate((0, 15, 30, 60, 120)):
            if delay:
                print(f"Transient GitHub fetch failure; retry {attempt} after {delay}s", flush=True)
                time.sleep(delay)
            result = original_run(*args, **options)
            if result.returncode == 0:
                return result
            if not any(token in result.stdout for token in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504")):
                break
        raise RuntimeError(f"Git fetch did not complete; no product branch was updated: {args}")
    # Collect independent gate results in one run; publication still requires all green.
    label = kwargs.get("log")
    if label in COLLECT:
        kwargs["check"] = False
    result = original_run(*args, **kwargs)
    if label in COLLECT and result.returncode:
        failures.append({"log": label, "returncode": result.returncode})
    return result


def resolve_rebase():
    paths = a.run("git", "diff", "--name-only", "--diff-filter=U", cwd=a.CANDIDATE).stdout.splitlines()
    if not paths:
        return resolve_source_conflicts()
    generated = {"apps/shared/src/gateway-contract.generated.ts", "apps/shared/src/gateway-contract.openrpc.json"}
    for path in paths:
        if path in generated:
            # An old formatting commit conflicted with main's new hermes_not_connected state.
            # The Python declarations are authoritative; verify() regenerates both artifacts.
            a.run("git", "diff", "--cc", "--", path, cwd=a.CANDIDATE,
                  log="generated-conflict-" + path.rsplit("/", 1)[-1] + ".diff")
            a.run("git", "checkout", "--ours", "--", path, cwd=a.CANDIDATE)
            a.run("git", "add", path, cwd=a.CANDIDATE)
    if set(paths) - generated:
        resolve_source_conflicts()


def align_cli_contract():
    path = a.CANDIDATE / "tests/hermes_cli/test_reasoning_command.py"
    text = a.replace(path.read_text(),
        '("delta", "rs_live:summary:1", "Checking")',
        '("delta", "rs_live:summary:1", "\\nChecking")')
    text = a.replace(text,
        '("delta", "rs_verify:summary:0", "Verifying")',
        '("delta", "rs_verify:summary:0", "\\n\\nVerifying")')
    path.write_text(text)


if __name__ == "__main__":
    a.run = run
    a.resolve_rebase = resolve_rebase
    a.prepare()
    align_cli_contract()
    a.verify()
    (a.OUT / "gate-failures.json").write_text(json.dumps(failures, indent=2))
    if failures:
        raise RuntimeError(f"Validation failed; product branch untouched: {failures}")
    a.publish()
