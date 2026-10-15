#!/usr/bin/env bash
set -euo pipefail

TARGET_BRANCH="fix/wsl12-server-global-fanout"
EXPECTED_HEAD="b6bdd300a1df285fb6be1e90accc85ddfb2e8825"

mkdir -p /tmp/rebase-conflicts
git config user.name "Xipong rebase helper"
git config user.email "217837358+Xipong@users.noreply.github.com"
git remote remove upstream 2>/dev/null || true
git remote add upstream https://github.com/NousResearch/hermes-agent.git
git fetch --no-tags upstream main
git fetch --no-tags origin "$TARGET_BRANCH"
git checkout -B "$TARGET_BRANCH" "origin/$TARGET_BRANCH"

set +e
GIT_EDITOR=true git rebase upstream/main
status=$?
set -e

if [[ $status -ne 0 ]]; then
  git status --short | tee /tmp/rebase-conflicts/status.txt
  git diff --cc | tee /tmp/rebase-conflicts/conflicts.diff
  while IFS= read -r -d '' file; do
    out="/tmp/rebase-conflicts/files/$file"
    mkdir -p "$(dirname "$out")"
    cp -- "$file" "$out.conflict"
    git show ":1:$file" > "$out.base" 2>/dev/null || true
    git show ":2:$file" > "$out.main" 2>/dev/null || true
    git show ":3:$file" > "$out.pr" 2>/dev/null || true
  done < <(git diff --name-only --diff-filter=U -z)
  exit "$status"
fi

git push --force-with-lease="refs/heads/$TARGET_BRANCH:$EXPECTED_HEAD" origin "HEAD:refs/heads/$TARGET_BRANCH"
