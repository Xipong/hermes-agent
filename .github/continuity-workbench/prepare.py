"""Apply review fixes to the published candidate, retaining its full authored history."""
import os
from pathlib import Path
import shutil
import subprocess

HEAD = 'd1aedc0022e86e36affaae53ebeb0f3158212efd'
BASE = '32eeacdf7c1eba14a2abc51f4b7545b7e98afa40'
root = Path('.github/continuity-workbench')
tmp = Path(os.environ['RUNNER_TEMP']) / 'continuity-receipt'
tmp.mkdir(exist_ok=True)
for name in ('validate.py', 'followup.diff'):
    shutil.copy(root / name, tmp / name)
subprocess.run(['git', 'config', 'user.name', 'Xipong'], check=True)
subprocess.run(['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'], check=True)
for sha in (BASE, HEAD):
    subprocess.run(['git', 'fetch', '--no-tags', '--depth=16', 'https://github.com/Xipong/hermes-agent.git', sha], check=True)
subprocess.run(['git', 'switch', '--detach', HEAD], check=True)
subprocess.run(['git', 'apply', '--check', str(tmp / 'followup.diff')], check=True)
subprocess.run(['git', 'apply', str(tmp / 'followup.diff')], check=True)
subprocess.run(['git', 'add', '-u'], check=True)
subprocess.run(['git', 'commit', '-m', 'test: align consolidated fixtures with current replay and event contracts'], check=True)
