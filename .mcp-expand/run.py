"""Fork-only validation; artifacts contain the tested product-only diff."""
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')
ROOT = Path.cwd()
INPUT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'validation-output'
OUT.mkdir(exist_ok=True)
NEW_PY = ['tests/hermes_cli/test_mcp_network_surfaces.py', 'tests/tools/test_mcp_network_oauth.py']
for name in NEW_PY:
    shutil.copyfile(INPUT / name, ROOT / name)
runpy.run_path(str(INPUT / '.mcp-expand/apply.py'))
runpy.run_path(str(INPUT / '.mcp-expand/ui-tests.py'))
p = ROOT / NEW_PY[1]
p.write_text(p.read_text(encoding='utf-8').replace('lambda *_: object()', 'lambda *_: type("FixtureProvider", (), {})()'), encoding='utf-8')
if (INPUT / '.mcp-expand/refine.py').exists():
    runpy.run_path(str(INPUT / '.mcp-expand/refine.py'))
NEW = NEW_PY + ['web/src/lib/mcp-network.test.ts', 'apps/desktop/src/api/mcp-network.test.ts', 'web/src/components/McpNetworkFields.tsx']
subprocess.run(['git', 'add', '-N', *NEW], check=True)
changed = subprocess.check_output(['git', 'diff', '--name-only']).decode().splitlines()
product = [name for name in changed if not name.startswith(('tests/', 'evals/')) and '.test.' not in name]
snapshot = {name: (ROOT / name).read_bytes() for name in product}
tracked = [name for name in product if subprocess.run(['git', 'cat-file', '-e', 'HEAD:' + name], capture_output=True).returncode == 0]
subprocess.run(['git', 'restore', '--', *tracked], check=True)
for name in set(product) - set(tracked):
    (ROOT / name).unlink()


def run(label, argv, cwd=ROOT):
    env = {**os.environ, 'HERMES_TEST_FILE_RETRIES': '0', 'NO_COLOR': '1'}
    with (OUT / (label + '.log')).open('w', encoding='utf-8') as log:
        print(label, argv, flush=True)
        result = subprocess.run(argv, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=800)
    print((OUT / (label + '.log')).read_text(encoding='utf-8', errors='replace')[-18000:], flush=True)
    return result.returncode


def failures(label):
    text = (OUT / (label + '.log')).read_text(encoding='utf-8', errors='replace')
    return set(re.findall(r'(?m)^FAILED (\S+)', text))


mode = sys.argv[1]
results = {}
bash = str(Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'Git/bin/bash.exe') if sys.platform == 'win32' else 'bash'
pytest = [bash, 'scripts/run_tests.sh', '-j', '4', '--file-timeout', '180']
if mode == 'python':
    results['red'] = run('red', pytest + NEW_PY + ['-q', '--tb=short'])
    if sys.platform == 'win32':
        # This existing POSIX-mode assertion fails on NTFS. Prove the exact
        # failure on unchanged production code; do not weaken or skip its test.
        results['baseline-permissions'] = run('baseline-permissions', pytest + [
            'tests/tools/test_mcp_schema_cache.py', '-q', '--tb=short',
            '-k', 'test_cache_lives_under_hermes_home_cache_dir_with_0600'])
elif mode == 'ui':
    results['red-desktop'] = run('red-desktop', ['node', '../../node_modules/vitest/vitest.mjs', 'run', '--project', 'ui', 'src/api/mcp-network.test.ts', '--reporter=json', '--outputFile=' + str(OUT / 'red-desktop.json')], ROOT / 'apps/desktop')
    results['red-web'] = run('red-web', ['node', '../node_modules/vitest/vitest.mjs', 'run', 'src/lib/mcp-network.test.ts', '--reporter=json', '--outputFile=' + str(OUT / 'red-web.json')], ROOT / 'web')
else:
    raise ValueError(mode)
for name, content in snapshot.items():
    (ROOT / name).write_bytes(content)

if mode == 'python':
    results['green'] = run('green', pytest + NEW_PY + ['tests/tools/test_mcp_windows.py', 'tests/tools/test_mcp_windows_policy.py', '-q', '--tb=short'])
    candidates = [
        'tests/hermes_cli/test_mcp_config.py', 'tests/hermes_cli/test_mcp_catalog.py',
        'tests/hermes_cli/test_mcp_catalog_env_boundary.py', 'tests/hermes_cli/test_mcp_dashboard_oauth.py',
        'tests/tools/test_mcp_device_flow.py', 'tests/tools/test_mcp_oauth_manager.py',
        'tests/tools/test_mcp_oauth_cold_load_expiry.py', 'tests/tools/test_mcp_oauth_metadata.py',
        'tests/tools/test_mcp_schema_cache.py', 'tests/tools/test_mcp_schema_cache_ttl.py',
        'tests/acp_adapter/test_acp_mcp_discovery.py', 'tests/hermes_cli/test_agent_import.py',
        'tests/tools/test_mcp_preflight_content_type.py', 'tests/tools/test_mcp_sse_transport.py',
        'tests/tools/test_mcp_http_redirect_headers.py', 'tests/tools/test_mcp_client_cert.py']
    results['neighbors'] = run('neighbors', pytest + [name for name in candidates if (ROOT / name).exists()] + ['-q', '--tb=short'])
    results['api-security-profile'] = run('api-security-profile', pytest + [
        'tests/hermes_cli/test_dashboard_admin_endpoints.py',
        'tests/hermes_cli/test_web_server_profile_unification.py',
        'tests/hermes_cli/test_mcp_security.py', '-q', '--tb=short', '-k', 'mcp'])
    results['ruff'] = run('ruff', [sys.executable, '-m', 'ruff', 'check', *[p for p in changed if p.endswith('.py')]])
else:
    for surface, prefix in [('desktop', 'apps/desktop'), ('web', 'web')]:
        cwd = ROOT / prefix
        rel = '../..' if surface == 'desktop' else '..'
        files = [str(ROOT / p) for p in changed if p.startswith(prefix + '/') and p.endswith(('.ts', '.tsx'))]
        results[surface + '-lint'] = run(surface + '-lint', ['node', rel + '/node_modules/eslint/bin/eslint.js', '--fix', *files], cwd)
        results[surface + '-format'] = run(surface + '-format', ['node', rel + '/node_modules/prettier/bin/prettier.cjs', '--write', *files], cwd)
        results[surface + '-typecheck'] = run(surface + '-typecheck', ['node', rel + '/node_modules/typescript/bin/tsc', '-p', '.', '--noEmit'], cwd)
    results['green-desktop'] = run('green-desktop', ['node', '../../node_modules/vitest/vitest.mjs', 'run', '--project', 'ui', 'src/api', 'src/lib/mcp-import.test.ts', 'src/lib/mcp-servers.test.ts', 'src/lib/mcp-probe-cache.test.ts', '--reporter=json', '--outputFile=' + str(OUT / 'green-desktop.json')], ROOT / 'apps/desktop')
    results['green-web'] = run('green-web', ['node', '../node_modules/vitest/vitest.mjs', 'run', 'src/lib/mcp-network.test.ts', 'src/lib/mcp-server-create.test.ts', 'src/lib/mcp-oauth.test.ts', '--reporter=json', '--outputFile=' + str(OUT / 'green-web.json')], ROOT / 'web')
results['diff-check'] = run('diff-check', ['git', 'diff', '--check'])
subprocess.run(['git', 'add', '-N', *NEW], check=True)
# Fixed-length blob identities allow byte-for-byte artifact comparison across
# Git versions whose default abbreviations differ (Windows uses 8 vs Linux 7).
(OUT / 'candidate.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary', '--full-index']))
(OUT / 'python.patch').write_bytes(subprocess.check_output(['git', 'diff', '--binary', '--full-index', '--', '*.py']))
(OUT / 'files.json').write_text(json.dumps(changed, indent=2), encoding='utf-8')
(OUT / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(results, flush=True)
allowed = set()
if mode == 'python' and sys.platform == 'win32':
    expected = {'tests/tools/test_mcp_schema_cache.py::TestCacheFileLocation::test_cache_lives_under_hermes_home_cache_dir_with_0600'}
    assert results['baseline-permissions'] == results['neighbors'] == 1, results
    assert failures('baseline-permissions') == failures('neighbors') == expected
    (OUT / 'verified-baseline-failure.json').write_text(json.dumps(sorted(expected)), encoding='utf-8')
    allowed = {'baseline-permissions', 'neighbors'}
assert all(value != 0 for key, value in results.items() if key.startswith('red')), results
assert all(value == 0 for key, value in results.items() if not key.startswith('red') and key not in allowed), results
