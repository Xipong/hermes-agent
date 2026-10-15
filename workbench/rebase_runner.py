"""Fork-only rebase probe for selected upstream PR branches.

Runs only on a disposable fork PR. It never mutates source PR branches:
successful rebases are pushed to rebase-candidate/*; conflicts are archived.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

MAIN = "ca069e12239a2c8d13887ac9f983557d00bdcfd2"
BRANCHES = {
    "120373": "fix/wsl-windows-host-core-35337285136",
    "120894": "fix/codex-output-continuity",
    "121990": "fix/desktop-old-user-tail-reconciliation",
    "122179": "fix/codex-stream-message-phase-state",
}

OUT = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "rebase-runner-results"
OUT.mkdir(parents=True, exist_ok=True)


def run(*args: str, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, check=False,
                          env={**os.environ, "GIT_EDITOR": ":", "GIT_SEQUENCE_EDITOR": ":"})
    if check and proc.returncode:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stdout}")
    return proc


def write(name: str, text: str) -> None:
    (OUT / name).write_text(text, encoding="utf-8", errors="replace")


run("git", "config", "user.name", "Xipong rebase workbench")
run("git", "config", "user.email", "217837358+Xipong@users.noreply.github.com")
if run("git", "remote", "get-url", "upstream", check=False).returncode:
    run("git", "remote", "add", "upstream", "https://github.com/NousResearch/hermes-agent.git")
else:
    run("git", "remote", "set-url", "upstream", "https://github.com/NousResearch/hermes-agent.git")
run("git", "fetch", "--no-tags", "--depth=20000", "upstream", f"+{MAIN}:refs/remotes/upstream/rebase-main")
for branch in BRANCHES.values():
    run("git", "fetch", "--no-tags", "--depth=20000", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")

summary: dict[str, object] = {"main": MAIN, "results": {}}
for pr, branch in BRANCHES.items():
    local = f"probe-pr{pr}"
    run("git", "switch", "--discard-changes", "--force-create", local, f"refs/remotes/origin/{branch}")
    old = run("git", "rev-parse", "HEAD").stdout.strip()
    merge_base = run("git", "merge-base", "HEAD", MAIN, check=False).stdout.strip()
    proc = run("git", "rebase", "--reapply-cherry-picks", "--empty=keep", "--onto", MAIN, merge_base, check=False)
    result: dict[str, object] = {"branch": branch, "old": old, "merge_base": merge_base, "returncode": proc.returncode}
    write(f"pr{pr}-rebase.log", proc.stdout)
    if proc.returncode == 0:
        new = run("git", "rev-parse", "HEAD").stdout.strip()
        candidate = f"rebase-candidate/pr{pr}-ca069e12"
        push = run("git", "push", "--force", "origin", f"HEAD:refs/heads/{candidate}", check=False)
        result.update({"status": "rebased", "new": new, "candidate": candidate, "push_returncode": push.returncode})
        write(f"pr{pr}-push.log", push.stdout)
        write(f"pr{pr}-log.txt", run("git", "log", "--format=%H%x09%an%x09%ae%x09%s", f"{MAIN}..HEAD").stdout)
        write(f"pr{pr}-stat.txt", run("git", "diff", "--stat", f"{MAIN}...HEAD").stdout)
        write(f"pr{pr}-range-diff.txt", run("git", "range-diff", f"{merge_base}..{old}", f"{MAIN}..{new}", check=False).stdout)
    else:
        unmerged = [line for line in run("git", "diff", "--name-only", "--diff-filter=U", check=False).stdout.splitlines() if line]
        current = run("git", "rev-parse", "REBASE_HEAD", check=False).stdout.strip()
        result.update({"status": "conflict", "unmerged": unmerged, "rebase_head": current})
        write(f"pr{pr}-status.txt", run("git", "status", "--short", check=False).stdout)
        write(f"pr{pr}-diff-cc.patch", run("git", "diff", "--cc", check=False).stdout)
        write(f"pr{pr}-ls-files-u.txt", run("git", "ls-files", "-u", check=False).stdout)
        stage_dir = OUT / f"pr{pr}-stages"
        stage_dir.mkdir(parents=True, exist_ok=True)
        for path in unmerged:
            safe = path.replace("/", "__")
            for stage in (1, 2, 3):
                data = subprocess.run(["git", "show", f":{stage}:{path}"], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, check=False)
                if data.returncode == 0:
                    (stage_dir / f"{safe}.stage{stage}").write_bytes(data.stdout)
        run("git", "rebase", "--abort", check=False)
    summary["results"][pr] = result
write("summary.json", json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, indent=2, sort_keys=True))
