"""Exact candidate checks and a disposable three-PR merge. Never publishes code."""
from pathlib import Path
import json
import os
import shutil
import subprocess

ROOT = Path.cwd()
DESKTOP = ROOT / 'apps/desktop'
OUT = Path(os.environ['RUNNER_TEMP']) / 'history-suite-evidence'
OUT.mkdir(parents=True, exist_ok=True)
PRODUCT = os.environ['PRODUCT_SHA']
ORIGINAL = os.environ['ORIGINAL_SHA']
MAIN = os.environ['MAIN_SHA']
RAIL = os.environ['RAIL_SHA']
BELOW = os.environ['BELOW_SHA']
ENV = dict(os.environ, HERMES_DESKTOP_PYTHON=os.environ['HERMES_PYTHON'], PYTHONPATH=str(ROOT))
STATUS = {}
PREFIX = 'src/components/assistant-ui/thread/'
TIMELINE = 'apps/desktop/' + PREFIX + 'timeline.tsx'
IDENTITY = ['-c', 'user.name=History integration verification', '-c', 'user.email=verification@example.invalid']


def git(*args, check=True):
    result = subprocess.run(['git', *args], cwd=ROOT, text=True, capture_output=True)
    if check and result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result


def run(name, args, cwd=DESKTOP, timeout=600, expected=0):
    print('::group::' + name, flush=True)
    with (OUT / (name + '.log')).open('w') as log:
        log.write('$ ' + ' '.join(args) + '\n')
        log.flush()
        try:
            code = subprocess.run(args, cwd=cwd, env=ENV, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    STATUS[name] = {'exit': code, 'expected': expected, 'passed': code == expected}
    (OUT / 'status.json').write_text(json.dumps(STATUS, indent=2))
    print((OUT / (name + '.log')).read_text(errors='replace')[-6500:], flush=True)
    print(f'Exit: {code} (expected {expected})\n::endgroup::', flush=True)
    return code


def reports(label):
    for name in ('test-results', 'playwright-report'):
        if (DESKTOP / name).exists():
            shutil.copytree(DESKTOP / name, OUT / label / name, dirs_exist_ok=True)


def replace_once(text, old, new):
    assert text.count(old) == 1, old
    return text.replace(old, new, 1)


def merge(sha, name, conflict=None, resolution=None):
    result = git(*IDENTITY, 'merge', '--no-commit', '--no-ff', sha, check=False)
    (OUT / (name + '-merge.log')).write_text(result.stdout + result.stderr)
    conflicts = git('diff', '--name-only', '--diff-filter=U').stdout.splitlines()
    assert result.returncode in (0, 1), result.stderr
    assert set(conflicts) <= ({conflict} if conflict else set()), conflicts
    if resolution is not None:
        (ROOT / conflict).write_text(resolution)
        git('add', conflict)
    git(*IDENTITY, 'commit', '-m', 'test(integration): ' + name)
    return conflicts


assert git('rev-parse', 'HEAD').stdout.strip() == PRODUCT
(OUT / 'inputs.json').write_text(json.dumps({'candidate': PRODUCT, 'original': ORIGINAL, 'main': MAIN, 'rail': RAIL, 'below': BELOW}, indent=2))
(OUT / 'candidate.patch').write_text(git('diff', ORIGINAL, PRODUCT).stdout)
if run('npm-ci', ['npm', 'ci', '--no-audit', '--no-fund'], ROOT):
    raise SystemExit(1)

# The new tests must fail for the missing browser API, not for missing imports.
paths = [PREFIX + 'history-scroll.ts', PREFIX + 'timeline-scroll.ts']
saved = {path: (DESKTOP / path).read_bytes() for path in paths}
try:
    for path in paths:
        (DESKTOP / path).write_text(git('show', ORIGINAL + ':apps/desktop/' + path).stdout)
    run('red-selectors', ['npx', 'vitest', 'run', '--project', 'ui', PREFIX + 'history-scroll.test.ts', '--reporter=json', '--outputFile=' + str(OUT / 'red-selectors.json')], expected=1)
    red = json.loads((OUT / 'red-selectors.json').read_text())
    assert red['numFailedTests'] == 4 and red['numPassedTests'] == 5, red
    failures = [a for suite in red['testResults'] for a in suite['assertionResults'] if a['status'] == 'failed']
    assert all('TypeError' in '\n'.join(a['failureMessages']) for a in failures), failures
finally:
    for path, contents in saved.items():
        (DESKTOP / path).write_bytes(contents)

candidate_suites = ['src/app/chat/history-window.test.tsx', PREFIX + 'history-scroll.test.ts', PREFIX + 'list-session-scroll.test.tsx', PREFIX + 'timeline-idle.test.tsx', PREFIX + 'use-timeline-reveal.test.tsx', PREFIX + 'streaming.test.tsx', 'src/lib/chat-messages.test.ts']
run('candidate-ui', ['npx', 'vitest', 'run', '--project', 'ui', '--maxWorkers=2', *candidate_suites])
run('candidate-lint', ['npx', 'eslint', '--max-warnings=0', *paths, PREFIX + 'history-scroll.test.ts'])
run('candidate-types', ['npx', 'tsc', '-p', '.', '--noEmit'])
run('candidate-e2e-types', ['npx', 'tsc', '-p', 'tsconfig.e2e.json', '--noEmit'])
run('candidate-backend', ['bash', 'scripts/run_tests.sh', 'tests/hermes_cli/test_session_timeline.py'], ROOT)
if run('candidate-build', ['npm', 'run', 'build', '--workspace=apps/desktop'], ROOT, timeout=900) == 0:
    run('candidate-native', ['xvfb-run', '-a', 'npx', 'playwright', 'test', 'e2e/history-navigation.spec.ts', '--workers=1', '--retries=0'], timeout=360)
reports('candidate')
run('candidate-clean', ['git', 'diff', '--exit-code', 'HEAD'], ROOT)
run('candidate-diff-check', ['git', 'diff', '--check', ORIGINAL, PRODUCT], ROOT)

# All commits below are local to the runner; Actions has contents:read only.
try:
    git('checkout', '--detach', MAIN)
    merge(PRODUCT, 'history')
    combined = (ROOT / TIMELINE).read_text()
    combined = replace_once(combined, "import { TimelineRail } from './timeline-rail'", "import { createTimelinePositionReader } from './timeline-position'\nimport { TimelineRail } from './timeline-rail'")
    combined = replace_once(combined, 'scrollTimelineTarget, timelineTarget', 'scrollTimelineTarget')
    signature = '    const indexes = new Map(railEntries.map((entry, index) => [entry.id, index]))'
    combined = replace_once(combined, signature, signature + '''
    const position = createTimelinePositionReader(viewport, indexes)

    const leadingIndex =
      history.isHistorical && history.leadingRowId != null
        ? railEntries.findIndex(entry => entry.rowId === history.leadingRowId)
        : -1''')
    begin = combined.index('      const top = viewport.getBoundingClientRect().top')
    end_text = '      setActiveIndex(active === -1 ? Math.max(0, first) : active)'
    end = combined.index(end_text, begin) + len(end_text)
    combined = combined[:begin] + '      setActiveIndex(position.read(leadingIndex))' + combined[end:]
    combined = replace_once(combined, '    const observer = new MutationObserver(schedule)', '''    const observer = new MutationObserver(records => {
      position.invalidate(records)
      schedule()
    })
''')
    combined = replace_once(combined, "    viewport.addEventListener('pointerdown', cancelJump)", "    resize.observe(viewport)\n    viewport.addEventListener('pointerdown', cancelJump)")
    conflicts = merge(RAIL, 'rail', TIMELINE, combined)
    merge(BELOW, 'messages-below')
    tree = git('rev-parse', 'HEAD^{tree}').stdout.strip()
    files = git('diff', '--name-only', MAIN, 'HEAD').stdout.splitlines()
    assert not any(p.startswith(('workbench/', '.github/workflows/')) for p in files), files
    assert not {'package.json', 'package-lock.json'} & set(files), 'dependency installation must match the combined tree'
    (OUT / 'integration-manifest.json').write_text(json.dumps({'candidate': PRODUCT, 'rail': RAIL, 'below': BELOW, 'main': MAIN, 'tree': tree, 'conflicts': conflicts, 'files': files}, indent=2))
    (OUT / 'integration.patch').write_text(git('diff', MAIN, 'HEAD').stdout)
    (OUT / 'integration-timeline.tsx').write_text(combined)
    suites = list(dict.fromkeys(candidate_suites + [PREFIX + 'timeline-position.test.tsx', PREFIX + 'timeline-rail.test.tsx', PREFIX + 'use-timeline-history.test.tsx', PREFIX + 'use-messages-below.test.tsx', PREFIX + 'use-messages-below-perf.test.ts', 'src/app/chat/scroll-to-bottom-button.test.tsx']))
    run('integration-ui', ['npx', 'vitest', 'run', '--project', 'ui', '--maxWorkers=2', *suites])
    renderer_files = [str(Path(p).relative_to('apps/desktop')) for p in files if p.startswith('apps/desktop/src/') and p.endswith(('.ts', '.tsx'))]
    run('integration-lint', ['npx', 'eslint', '--max-warnings=0', *renderer_files])
    run('integration-types', ['npx', 'tsc', '-p', '.', '--noEmit'])
    run('integration-e2e-types', ['npx', 'tsc', '-p', 'tsconfig.e2e.json', '--noEmit'])
    run('integration-backend', ['bash', 'scripts/run_tests.sh', 'tests/hermes_cli/test_session_timeline.py'], ROOT)
    if run('integration-build', ['npm', 'run', 'build', '--workspace=apps/desktop'], ROOT, timeout=900) == 0:
        run('integration-native', ['xvfb-run', '-a', 'npx', 'playwright', 'test', 'e2e/history-navigation.spec.ts', 'e2e/timeline-position.spec.ts', 'e2e/messages-below-position.spec.ts', '--workers=1', '--retries=0', '--repeat-each=3'], timeout=700)
    reports('integration')
    run('integration-diff-check', ['git', 'diff', '--check', MAIN, 'HEAD'], ROOT)
    run('integration-clean', ['git', 'diff', '--exit-code', 'HEAD'], ROOT)
finally:
    git('merge', '--abort', check=False)
    git('checkout', '--detach', PRODUCT)

run('restored-product', ['git', 'diff', '--exit-code', PRODUCT], ROOT)
print('HISTORY_SUITE_STATUS=' + json.dumps(STATUS), flush=True)
raise SystemExit(0 if all(s['passed'] for s in STATUS.values()) else 1)
