from pathlib import Path
import base64
import gzip
import hashlib
import subprocess
import sys

staging = Path(__file__).parent
if sys.argv[1] == 'tests':
    encoded = (staging / 'tests.patch.gz.b64').read_text()
    # Correct transport transcription before decoding; the SHA below is the
    # authoritative local test patch, not a best-effort decoded payload.
    for old, new in [('NaRZZiy', 'NaRZiy'), ('AOUGUG0', 'AOUG0'),
                     ('lfITITt', 'lfITt'), ('OvyH5Hqq', 'OvyHqq')]:
        encoded = encoded.replace(old, new)
    patch = gzip.decompress(base64.b64decode(encoded))
    assert hashlib.sha256(patch).hexdigest() == 'cda1d52a462d8fef03a9989c822f1e15697725d3c025bcd1477e36aeacdf5801'
    subprocess.run(['git', 'apply', '-'], input=patch, check=True)
else:
    subprocess.run(['git', 'apply', str(staging / 'source.patch')], check=True)
    p = Path('tools/computer_use/cua_backend_daemon.py')
    s = p.read_text().replace('if _driver.is_windows_driver(driver_cmd)\n',
                             'if sys.platform == "win32" or _driver.is_windows_driver(driver_cmd)\n')
    p.write_text(s)
    p = Path('hermes_cli/tools_config_cua.py')
    s = p.read_text()
    old = '''    try:
        result = _run_text([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                           timeout=300, env=_cua_driver_env())'''
    new = '''    from tools.computer_use.cua_backend import sanitized_cua_driver_env
    try:
        result = _run_text([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                           timeout=300, env=sanitized_cua_driver_env() if wsl else _cua_driver_env())'''
    assert s.count(old) == 1
    p.write_text(s.replace(old, new, 1))
    if sys.platform == 'linux':
        paths = ['hermes_cli/config_defaults.py', 'hermes_cli/tools_config_cua.py',
                 'tools/computer_use/cua_backend.py', 'tools/computer_use/cua_backend_daemon.py',
                 'tools/computer_use/cua_backend_driver.py', 'tools/computer_use/tool.py',
                 'website/docs/user-guide/features/computer-use.md']
        patch = subprocess.check_output(['git', 'diff', '--binary', '--', *paths])
        assert hashlib.sha256(patch).hexdigest() == '7cc08efba8ef469382e15dbe7b63da3851ca35da39bc6abfae3865fb7f61f91c'
