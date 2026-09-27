"""Isolated verification; only the reviewed product paths reach the PR branch."""
from pathlib import Path
import hashlib
import json
import os
import runpy
import shutil
import subprocess
import sys

ROOT = Path.cwd()
BASE = '6e69a8933adda7dbbff7cf3009a259a4524477e9'
BRANCH = 'fix/desktop-history-navigation-125766'
EVIDENCE = Path(os.environ['RUNNER_TEMP']) / 'history-evidence'
EVIDENCE.mkdir(parents=True, exist_ok=True)
EDITS = {}
for index in range(4):
    EDITS.update(runpy.run_path(str(ROOT / f'workbench/history_edits_{index}.py'))['EDITS'])
assert hashlib.sha256(json.dumps(EDITS, ensure_ascii=False, sort_keys=True).encode()).hexdigest() == 'a5ec9994945ffd0ec4ee535e81e64ba8b582df3af81236ef18366caf8068f6cc', 'Transfer checksum mismatch'
STATUS = {}
ENV = dict(os.environ, HERMES_DESKTOP_PYTHON=os.environ['HERMES_PYTHON'])


def run(name, command, *, cwd=ROOT, timeout=600, required=False):
    print(f'::group::{name}', flush=True)
    log = EVIDENCE / f'{name}.log'
    with log.open('w') as output:
        output.write('$ ' + ' '.join(command) + '\n')
        output.flush()
        try:
            result = subprocess.run(command, cwd=cwd, env=ENV, stdout=output, stderr=subprocess.STDOUT, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    STATUS[name] = code
    text = log.read_text(errors='replace')
    print(text[-22000:], flush=True)
    print(f'Exit: {code}\n::endgroup::', flush=True)
    (EVIDENCE / 'status.json').write_text(json.dumps(STATUS, indent=2))
    if required and code:
        raise RuntimeError(f'{name} failed: {code}')
    return code


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, env=ENV, text=True).strip()


def apply(paths):
    for name in paths:
        spec = EDITS[name]
        target = ROOT / name
        original = target.read_bytes() if target.exists() else b''
        assert hashlib.sha256(original).hexdigest() == spec['sha256'], name
        lines = original.decode().splitlines(True)
        for start, end, replacement in reversed(spec['edits']):
            lines[start:end] = replacement.splitlines(True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(''.join(lines))


def publish():
    git('add', '--', *EDITS)
    tree = git('write-tree')
    remote = git('ls-remote', '--heads', 'origin', f'refs/heads/{BRANCH}')
    parent = remote.split()[0] if remote else BASE
    if remote:
        git('fetch', '--depth=1', 'origin', parent)
    # A retry is a normal fast-forward commit; never force-push someone else's work.
    ENV.update(GIT_AUTHOR_NAME='Xipong', GIT_AUTHOR_EMAIL='217837358+Xipong@users.noreply.github.com',
               GIT_COMMITTER_NAME='Xipong', GIT_COMMITTER_EMAIL='217837358+Xipong@users.noreply.github.com')
    sha = git('commit-tree', tree, '-p', parent, '-m', 'fix(desktop): make bounded history navigation contiguous and occurrence-stable')
    git('push', 'origin', f'{sha}:refs/heads/{BRANCH}')
    (EVIDENCE / 'candidate-sha.txt').write_text(sha + '\n')
    (EVIDENCE / 'candidate.patch').write_text(git('diff', BASE, sha) + '\n')
    print(f'PRODUCT_CANDIDATE={sha}', flush=True)
    return sha


def main():
    git('fetch', '--depth=1', 'origin', BASE)
    git('checkout', '--detach', BASE)
    test_path = 'tests/hermes_cli/test_session_timeline.py'
    apply([test_path])
    run('red-backend', ['bash', 'scripts/run_tests.sh', test_path, '-k', 'adjacent'], timeout=400)
    git('restore', '--', test_path)
    apply(EDITS)
    run('npm-ci', ['npm', 'ci', '--no-audit', '--no-fund'], timeout=600, required=True)
    desktop = ROOT / 'apps/desktop'
    ts_paths = [str(Path(name).relative_to('apps/desktop')) for name in EDITS if name.endswith(('.ts', '.tsx'))]
    src_paths = [name for name in ts_paths if name.startswith('src/')]
    run('eslint-fix', ['npx', 'eslint', '--fix', *src_paths], cwd=desktop)
    run('prettier', ['npx', 'prettier', '--write', *ts_paths], cwd=desktop)
    run('lint', ['npx', 'eslint', *src_paths], cwd=desktop)
    run('diff-check', ['git', 'diff', '--check'])
    run('backend', ['bash', 'scripts/run_tests.sh', test_path], timeout=400)
    ui = [
        'src/app/chat/history-window.test.tsx',
        'src/components/assistant-ui/thread/history-scroll.test.ts',
        'src/components/assistant-ui/thread/list-session-scroll.test.tsx',
        'src/components/assistant-ui/thread/timeline-idle.test.tsx',
        'src/components/assistant-ui/thread/use-timeline-reveal.test.tsx',
        'src/components/assistant-ui/thread/streaming.test.tsx',
        'src/lib/chat-messages.test.ts',
    ]
    run('ui', ['npx', 'vitest', 'run', '--project', 'ui', *ui], cwd=desktop, timeout=400)
    run('renderer-types', ['npx', 'tsc', '-p', '.', '--noEmit'], cwd=desktop, timeout=400)
    run('e2e-types', ['npx', 'tsc', '-p', 'tsconfig.e2e.json', '--noEmit'], cwd=desktop, timeout=400)
    publish()
    build = run('build', ['npm', 'run', 'build', '--workspace=apps/desktop'], timeout=900)
    if build == 0:
        run('native', ['xvfb-run', '-a', 'npx', 'playwright', 'test', 'e2e/history-navigation.spec.ts', '--workers=1', '--retries=0'], cwd=desktop, timeout=360)
    for name in ('test-results', 'playwright-report'):
        source = desktop / name
        if source.exists():
            shutil.copytree(source, EVIDENCE / name, dirs_exist_ok=True)
    (EVIDENCE / 'status.json').write_text(json.dumps(STATUS, indent=2))
    # Red is expected to fail; lint-fix can report transient issues fixed by prettier.
    required = ('npm-ci', 'prettier', 'lint', 'diff-check', 'backend', 'ui', 'renderer-types', 'e2e-types', 'build', 'native')
    return 0 if STATUS.get('red-backend', 0) != 0 and all(STATUS.get(key) == 0 for key in required) else 1


if __name__ == '__main__':
    sys.exit(main())
