"""Apply the authored, hash-pinned patch series to real upstream main (fork workbench only)."""
import base64
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess

BASE = '32eeacdf7c1eba14a2abc51f4b7545b7e98afa40'
EXPECTED = 'd211a365a29124522b135ab1cd8aa0d446b7b2967f8d2f81067e18e47f79bc5b'
root = Path('.github/continuity-workbench')
tmp = Path(os.environ['RUNNER_TEMP']) / 'continuity-receipt'
tmp.mkdir(exist_ok=True)
parts = [(root / f'implementation.part{i}').read_bytes() for i in range(4)]
# Correct one diagnosed transport transcription before checking the full source hash.
# This is a workbench-only byte transfer, never part of the product patch.
encoded = base64.b64encode(parts[1]).decode()
encoded = encoded.replace('vXp28euxv', 'vXp28+xv') + 'Z'
parts[1] = base64.b64decode(encoded, validate=True)
patch = gzip.decompress(b''.join(parts))
assert hashlib.sha256(patch).hexdigest() == EXPECTED, 'Source archive integrity mismatch'
(tmp / 'implementation.mbox').write_bytes(patch)
shutil.copy(root / 'validate.py', tmp / 'validate.py')
subprocess.run(['git', 'config', 'user.name', 'Xipong'], check=True)
subprocess.run(['git', 'config', 'user.email', '217837358+Xipong@users.noreply.github.com'], check=True)
subprocess.run(['git', 'fetch', '--no-tags', '--depth=1', 'https://github.com/NousResearch/hermes-agent.git', BASE], check=True)
subprocess.run(['git', 'switch', '--detach', BASE], check=True)
subprocess.run(['git', 'am', str(tmp / 'implementation.mbox')], check=True)
print('Applied pinned source series; no workbench files are in the candidate tree.')
