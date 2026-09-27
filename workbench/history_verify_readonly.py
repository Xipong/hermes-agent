"""Read-only validation of a pinned PR commit; never pushes or rewrites history."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tarfile

ROOT = Path.cwd()
OUT = Path(os.environ['RUNNER_TEMP']) / 'history-evidence'
OUT.mkdir(parents=True, exist_ok=True)
ENV = dict(os.environ, HERMES_DESKTOP_PYTHON=os.environ['HERMES_PYTHON'])
STATUS = {}


def run(name, args, cwd=ROOT, timeout=600):
    print('::group::' + name, flush=True)
    with (OUT / (name + '.log')).open('w') as log:
        log.write('$ ' + ' '.join(args) + '\n')
        log.flush()
        try:
            code = subprocess.run(args, cwd=cwd, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    STATUS[name] = code
    (OUT / 'status.json').write_text(json.dumps(STATUS, indent=2))
    print((OUT / (name + '.log')).read_text(errors='replace')[-25000:], flush=True)
    print(f'Exit: {code}\n::endgroup::', flush=True)
    return code


sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
assert sha == os.environ['PRODUCT_SHA']
(OUT / 'candidate-sha.txt').write_text(sha + '\n')
base = '26472756f1d8f65e714d6228f76b6816df87ea13'
subprocess.run(['git', 'fetch', '--depth=1', 'origin', base], check=True)
paths = subprocess.check_output(['git', 'diff', '--name-only', base, sha], text=True).splitlines()
assert not any(path.startswith(('workbench/', '.github/workflows/')) for path in paths)
(OUT / 'candidate.patch').write_bytes(subprocess.check_output(['git', 'diff', base, sha]))
with tarfile.open(OUT / 'candidate-source.tar.gz', 'w:gz') as archive:
    for name in paths:
        archive.add(ROOT / name, arcname=name)
if run('npm-ci', ['npm', 'ci', '--no-audit', '--no-fund']):
    sys.exit(1)
desktop = ROOT / 'apps/desktop'
src = [str(Path(p).relative_to('apps/desktop')) for p in paths if p.startswith('apps/desktop/src/') and p.endswith(('.ts', '.tsx'))]
run('lint', ['npx', 'eslint', *src], desktop)
run('diff-check', ['git', 'diff', '--check', base, sha])
run('backend', ['bash', 'scripts/run_tests.sh', 'tests/hermes_cli/test_session_timeline.py'], timeout=400)
ui = ['src/app/chat/history-window.test.tsx',
      'src/components/assistant-ui/thread/history-scroll.test.ts',
      'src/components/assistant-ui/thread/list-session-scroll.test.tsx',
      'src/components/assistant-ui/thread/timeline-idle.test.tsx',
      'src/components/assistant-ui/thread/use-timeline-reveal.test.tsx',
      'src/components/assistant-ui/thread/streaming.test.tsx',
      'src/lib/chat-messages.test.ts']
run('ui', ['npx', 'vitest', 'run', '--project', 'ui', *ui], desktop, 400)
run('renderer-types', ['npx', 'tsc', '-p', '.', '--noEmit'], desktop, 400)
run('e2e-types', ['npx', 'tsc', '-p', 'tsconfig.e2e.json', '--noEmit'], desktop, 400)
if run('build', ['npm', 'run', 'build', '--workspace=apps/desktop'], timeout=900) == 0:
    run('native', ['xvfb-run', '-a', 'npx', 'playwright', 'test', 'e2e/history-navigation.spec.ts', '--workers=1', '--retries=0'], desktop, 360)
for name in ('test-results', 'playwright-report'):
    if (desktop / name).exists():
        shutil.copytree(desktop / name, OUT / name, dirs_exist_ok=True)
run('clean-product', ['git', 'diff', '--exit-code', 'HEAD'])
sys.exit(0 if STATUS.get('native') == 0 and all(code == 0 for code in STATUS.values()) else 1)
