from pathlib import Path
import base64
import gzip
import hashlib
import subprocess
import sys

staging = Path(__file__).parent
subprocess.run(['git', 'config', 'core.autocrlf', 'false'], check=True)
if sys.argv[1] == 'tests':
    encoded = (staging / 'tests.patch.gz.b64').read_text(encoding='utf-8')
    # Correct transport transcription before decoding; enforce the original checksum.
    for old, new in [('NaRZZiy', 'NaRZiy'), ('AOUGUG0', 'AOUG0'),
                     ('lfITITt', 'lfITt'), ('OvyH5Hqq', 'OvyHqq')]:
        encoded = encoded.replace(old, new)
    patch = gzip.decompress(base64.b64decode(encoded))
    assert hashlib.sha256(patch).hexdigest() == 'cda1d52a462d8fef03a9989c822f1e15697725d3c025bcd1477e36aeacdf5801'
    subprocess.run(['git', 'apply', '-'], input=patch, check=True)
else:
    paths = ['hermes_cli/config_defaults.py', 'hermes_cli/tools_config_cua.py',
             'tools/computer_use/cua_backend.py', 'tools/computer_use/cua_backend_daemon.py',
             'tools/computer_use/cua_backend_driver.py', 'tools/computer_use/tool.py',
             'website/docs/user-guide/features/computer-use.md']
    # Work on identical LF source on each hosted OS, regardless of checkout defaults.
    for path in paths:
        Path(path).write_bytes(subprocess.check_output(['git', 'show', 'HEAD:' + path]))
    patch = (staging / 'source.patch').read_text(encoding='utf-8').encode('utf-8')
    subprocess.run(['git', 'apply', '-'], input=patch, check=True)
    p = Path('tools/computer_use/cua_backend_daemon.py')
    s = p.read_text(encoding='utf-8').replace('if _driver.is_windows_driver(driver_cmd)\n',
                             'if sys.platform == "win32" or _driver.is_windows_driver(driver_cmd)\n')
    p.write_text(s, encoding='utf-8', newline='\n')
    p = Path('hermes_cli/tools_config_cua.py')
    s = p.read_text(encoding='utf-8')
    old = '''    try:
        result = _run_text([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                           timeout=300, env=_cua_driver_env())'''
    new = '''    from tools.computer_use.cua_backend import sanitized_cua_driver_env
    try:
        result = _run_text([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
                           timeout=300, env=sanitized_cua_driver_env() if wsl else _cua_driver_env())'''
    assert s.count(old) == 1
    p.write_text(s.replace(old, new, 1), encoding='utf-8', newline='\n')
    p = Path('tools/computer_use/cua_backend_driver.py')
    s = p.read_text(encoding='utf-8').replace(
        'os.path.realpath(shutil.which(command) or command).lower().endswith(".exe"))',
        'os.path.realpath(command if _has_path_separator(command) else shutil.which(command) or command).lower().endswith(".exe"))', 1)
    p.write_text(s, encoding='utf-8', newline='\n')
    if sys.platform == 'linux':
        patch = subprocess.check_output(['git', 'diff', '--binary', '--', *paths])
        assert hashlib.sha256(patch).hexdigest() == 'ef42bdf604f204f21cd56e0b84e1c7e5757909ce0a71a9f7fa0127be89865847'
