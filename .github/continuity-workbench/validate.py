"""Isolated integration receipt. No live providers, profiles or user state are used."""
import json
import os
from pathlib import Path
import subprocess
import zipfile

BASE = '32eeacdf7c1eba14a2abc51f4b7545b7e98afa40'
ROOT = Path.cwd()
OUT = Path(os.environ['RUNNER_TEMP']) / 'continuity-receipt'
RESULTS = {}
PYTHON = str(ROOT / '.venv/bin/python')
ENV = dict(os.environ)
ENV.update(HOME=str(OUT / 'home'), HERMES_HOME=str(OUT / 'hermes'),
           HERMES_PYTHON=PYTHON, HERMES_DESKTOP_PYTHON=PYTHON,
           VIRTUAL_ENV=str(ROOT / '.venv'), PYTHONPATH=str(ROOT),
           UV_NO_SYNC='1', UV_PYTHON=PYTHON, NODE_OPTIONS='--max-old-space-size=6144')
Path(ENV['HOME']).mkdir(exist_ok=True)
Path(ENV['HERMES_HOME']).mkdir(exist_ok=True)

def git(*args):
    return subprocess.check_output(['git', *args], text=True)

def run(name, args, cwd=ROOT, timeout=480):
    print('RUN', name, flush=True)
    with (OUT / (name + '.log')).open('w') as log:
        try:
            result = subprocess.run(args, cwd=cwd, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
            log.write('\nWORKBENCH TIMEOUT\n')
    RESULTS[name] = code
    (OUT / 'results.json').write_text(json.dumps(RESULTS, indent=2))
    print('RESULT', name, code, flush=True)
    if code:
        print((OUT / (name + '.log')).read_text(errors='replace')[-10000:], flush=True)
    return code

changed = git('diff', '--name-only', BASE, 'HEAD').splitlines()
new_py = [p for p in git('diff', '--name-only', '--diff-filter=A', BASE, 'HEAD').splitlines() if p.endswith('.py')]
ts = [p for p in changed if p.endswith(('.ts', '.tsx')) and not p.endswith('.generated.ts')]
run('format-new-python', [str(ROOT / '.venv/bin/ruff'), 'format', *new_py])
run('lint-new-python-fix', [str(ROOT / '.venv/bin/ruff'), 'check', '--fix', *new_py])
run('lint-typescript-fix', [str(ROOT / 'node_modules/.bin/eslint'), '--fix', '--no-warn-ignored', '--max-warnings', '0', *[str(ROOT / p) for p in ts]], cwd=ROOT / 'apps/desktop')
run('format-typescript', [str(ROOT / 'node_modules/.bin/prettier'), '--write', *ts])
# Generated artifacts are owned by the generator, never by generic formatting tools.
run('generate-contracts', [PYTHON, 'scripts/gen_gateway_contracts.py'])
if git('status', '--porcelain').strip():
    subprocess.run(['git', 'add', *changed], check=True)
    subprocess.run(['git', 'commit', '-m', 'style: apply project lint and preserve generator-owned contracts'], check=True)
(OUT / 'head.txt').write_text(git('rev-parse', 'HEAD'))
(OUT / 'publish-ready').write_text('Code is committed; check the validation receipt before marking the PR ready.\n')
run('typecheck-desktop', ['npm', 'run', 'typecheck'], cwd=ROOT / 'apps/desktop')
run('typecheck-shared', ['npm', 'run', 'typecheck', '--workspace', 'apps/shared'])
run('python-targeted', ['bash', 'scripts/run_tests.sh', '-j', '2', '--file-retries', '0', '--file-timeout', '180',
    'tests/agent/test_codex_commentary_channels.py', 'tests/hermes_cli/test_codex_commentary_channel.py',
    'tests/agent/test_reasoning_identity.py', 'tests/gateway/test_api_server_commentary_history.py',
    'tests/agent/test_run_agent_codex_responses.py', 'tests/agent/test_codex_app_server_event_bridge.py',
    'tests/agent/test_codex_stream_supersession.py', 'tests/hermes_cli/test_reasoning_command.py',
    'tests/hermes_cli/test_history_commentary_display.py', 'tests/gateway/test_session_api.py',
    'tests/gateway/test_api_server_compaction_projection.py', 'tests/hermes_cli/test_cli_quiet_stdout_leak.py',
    'tests/tui_gateway/test_codex_app_server_live_events.py', 'tests/tui_gateway/contracts/test_generated.py',
    '--tb=short', '--show-capture=no'], timeout=720)
run('desktop-targeted', ['npm', 'run', 'test:ui', '--', '--maxWorkers=2',
    'src/lib/chat-messages', 'src/app/session/hooks/use-message-stream',
    'src/app/session/hooks/use-prompt-actions/steering-recovery.test.tsx'], cwd=ROOT / 'apps/desktop', timeout=720)
run('lint-typescript', [str(ROOT / 'node_modules/.bin/eslint'), '--no-warn-ignored', '--max-warnings', '0', *[str(ROOT / p) for p in ts]], cwd=ROOT / 'apps/desktop', timeout=240)
mutation = ['agent/codex_responses_adapter.py', 'gateway/platforms/api_server.py']
try:
    for path in mutation:
        (ROOT / path).write_text(git('show', BASE + ':' + path))
    run('red-normalization-api', ['bash', 'scripts/run_tests.sh', '-j', '2', '--file-retries', '0',
        'tests/agent/test_codex_commentary_channels.py', 'tests/gateway/test_api_server_commentary_history.py', '--tb=short'], timeout=300)
finally:
    subprocess.run(['git', 'restore', '--', *mutation], check=True)
if RESULTS.get('typecheck-desktop') == 0 and RESULTS.get('desktop-targeted') == 0:
    if run('build-desktop', ['npm', 'run', 'build'], cwd=ROOT / 'apps/desktop', timeout=600) == 0:
        run('electron-replay', ['xvfb-run', '-a', '--server-args=-screen 0 1280x1024x24',
            str(ROOT / 'node_modules/.bin/playwright'), 'test', 'e2e/codex-commentary-hydration.spec.ts', '--workers=1', '--reporter=list'],
            cwd=ROOT / 'apps/desktop', timeout=480)
run('diff-check', ['git', 'diff', '--check', BASE, 'HEAD'])
(OUT / 'final.diff').write_text(git('diff', BASE, 'HEAD'))
(OUT / 'commits.txt').write_text(git('log', '--format=fuller', BASE + '..HEAD'))
(OUT / 'stat.txt').write_text(git('diff', '--stat', BASE, 'HEAD'))
with zipfile.ZipFile(OUT / 'candidate-sources.zip', 'w', zipfile.ZIP_DEFLATED) as bundle:
    for path in git('diff', '--name-only', BASE, 'HEAD').splitlines():
        bundle.write(ROOT / path, path)
# Keep failure diagnostics for the actual Electron execution, without any user data.
for directory in ('test-results', 'playwright-report'):
    path = ROOT / 'apps/desktop' / directory
    if path.exists():
        with zipfile.ZipFile(OUT / (directory + '.zip'), 'w', zipfile.ZIP_DEFLATED) as bundle:
            for source in path.rglob('*'):
                if source.is_file(): bundle.write(source, source.relative_to(path))
print(json.dumps(RESULTS, indent=2), flush=True)
failed = [name for name, code in RESULTS.items() if code and name != 'red-normalization-api']
if RESULTS.get('red-normalization-api') == 0:
    failed.append('negative control did not fail')
if failed:
    raise SystemExit('Validation failures: ' + ', '.join(failed))
