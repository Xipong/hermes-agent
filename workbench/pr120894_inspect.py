"""Disposable read-only PR/main merge rehearsal; no product refs are updated."""
from pathlib import Path
import os
import subprocess

BASE = "59004a62356f3a4697ab0fe8ad5086d2b405e2a6"
OLD = "b0936c3406566fa133c07aed4b7a6e1199f3695c"
ROOT = Path.cwd()
OUT = Path(os.environ["RUNNER_TEMP"]) / "pr120894-evidence"
OUT.mkdir(exist_ok=True)

def run(*args, cwd=ROOT, check=True):
    p = subprocess.run(args, cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and p.returncode:
        raise RuntimeError(p.stdout)
    return p.stdout

run("git", "fetch", "--no-tags", "origin", OLD, BASE)
common = run("git", "merge-base", BASE, OLD).strip()
print("BASE", BASE, "OLD", OLD, "MERGE_BASE", common, flush=True)
print("COUNTS", run("git", "rev-list", "--left-right", "--count", f"{BASE}...{OLD}"), flush=True)
print("PR_LINEAGE\n", run("git", "log", "--reverse", "--format=%H %an <%ae>%n%B", f"{common}..{OLD}"), flush=True)
print("PR_FILES\n", run("git", "diff", "--stat", common, OLD), flush=True)
candidate = Path(os.environ["RUNNER_TEMP"]) / "pr120894-conflicts"
run("git", "worktree", "add", "--detach", str(candidate), BASE)
run("git", "config", "user.name", "Xipong", cwd=candidate)
run("git", "config", "user.email", "217837358+Xipong@users.noreply.github.com", cwd=candidate)
print("MERGE_REHEARSAL\n", run("git", "merge", "--no-commit", "--no-ff", OLD, cwd=candidate, check=False), flush=True)
paths = run("git", "diff", "--name-only", "--diff-filter=U", cwd=candidate).splitlines()
print("CONFLICT_FILES", len(paths), paths, flush=True)
for path in paths:
    print(f"\n=== CONFLICT {path} ===\n", run("git", "diff", "--cc", "--", path, cwd=candidate), flush=True)
    print(f"=== UPSTREAM_CHANGES {path} ===\n", run("git", "log", "--format=%h %ad %s", "--date=iso-strict", f"{common}..{BASE}", "--", path), flush=True)
(OUT / "conflicts.txt").write_text("\n".join(paths))
(OUT / "merge.diff").write_text(run("git", "diff", "--cc", cwd=candidate))
(OUT / "pr.diff").write_text(run("git", "diff", common, OLD))
for area in ["apps/desktop/src", "tui_gateway", "tests"]:
    p = candidate / area
    print("AREA_GUIDES", area, [str(x.relative_to(candidate)) for x in p.rglob("AGENTS.md")][:80], flush=True)
print("RECENT_MAIN\n", run("git", "log", "--first-parent", "--oneline", "-25", BASE), flush=True)
