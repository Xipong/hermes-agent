"""Finish native-callback integration with existing notification policy, in isolation."""
import os
from pathlib import Path
import shutil
import subprocess

HEAD = '9b4fc16d8bd41dfdefb98c0fe35bede3eedcdcf7'
BASE = '32eeacdf7c1eba14a2abc51f4b7545b7e98afa40'
root = Path('.github/continuity-workbench')
tmp = Path(os.environ['RUNNER_TEMP']) / 'continuity-receipt'
tmp.mkdir(exist_ok=True)
shutil.copy(root / 'followup.diff', tmp / 'followup.diff')
validation = (root / 'validate.py').read_text()
needle = "    'tests/agent/test_reasoning_identity.py', 'tests/gateway/test_api_server_commentary_history.py',"
assert needle in validation
validation = validation.replace(needle, "    'tests/agent/test_reasoning_identity.py', 'tests/agent/test_warning_presentation.py',\n    'tests/tui_gateway/test_diagnostic_notification_presentation.py', 'tests/gateway/test_api_server_commentary_history.py',")
needle = "mutation = ['agent/codex_responses_adapter.py', 'gateway/platforms/api_server.py']"
assert needle in validation
control = """mute_path = 'agent/notification_presentation.py'
try:
    (ROOT / mute_path).write_text(git('show', BASE + ':' + mute_path))
    run('red-muted-reasoning', ['bash', 'scripts/run_tests.sh', '-j', '1', '--file-retries', '0',
        'tests/agent/test_reasoning_identity.py', '--tb=short'], timeout=180)
finally:
    subprocess.run(['git', 'restore', '--', mute_path], check=True)
"""
validation = validation.replace(needle, control + needle)
validation = validation.replace("if code and name != 'red-normalization-api'", "if code and name not in ('red-normalization-api', 'red-muted-reasoning')")
validation = validation.replace("if failed:\n", "if RESULTS.get('red-muted-reasoning') == 0:\n    failed.append('mute negative control did not fail')\nif failed:\n")
(tmp / 'validate.py').write_text(validation)
subprocess.run(['git', 'config', 'user.name', 'Xipong'], check=True)
subprocess.run(['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'], check=True)
for sha in (BASE, HEAD):
    subprocess.run(['git', 'fetch', '--no-tags', '--depth=16', 'https://github.com/Xipong/hermes-agent.git', sha], check=True)
subprocess.run(['git', 'switch', '--detach', HEAD], check=True)
subprocess.run(['git', 'apply', '--check', str(tmp / 'followup.diff')], check=True)
subprocess.run(['git', 'apply', str(tmp / 'followup.diff')], check=True)
subprocess.run(['git', 'add', '-u'], check=True)
subprocess.run(['git', 'commit', '-m', 'fix(codex): honor muted notification policy for native reasoning events'], check=True)
