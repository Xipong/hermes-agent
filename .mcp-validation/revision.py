"""Fork-only second-pass validation: real Git Bash on Windows, policy tests,
and strict gates. Neither this harness nor its workflow enters either PR.
"""
from pathlib import Path


def harden_helper():
    p = ROOT / 'tools/mcp_windows.py'
    text = p.read_text(encoding='utf-8')
    start = text.index('    if not isinstance(network, str)')
    end = text.index('    if not wsl or endpoint is None or network == "local":', start)
    validation = text[start:end]
    text = text[:start] + '    validate_mcp_network(url, network)\n    endpoint = _loopback_endpoint(url)\n    wsl = is_wsl()\n' + text[end:]
    marker = '@contextlib.asynccontextmanager\nasync def mcp_http_route'
    text = text.replace(marker, 'def validate_mcp_network(url: str, network: str = "auto") -> None:\n    """Reject unfulfillable explicit targets before any optional preflight."""\n' + validation + '\n\n' + marker)
    text = text.replace('            process = None\n            pumps = []', '            process = None\n            connected = False\n            pumps = []')
    text = text.replace('                route.error = None\n                pumps =', '                connected = True\n                route.error = None\n                pumps =')
    old = '''                route.error = (f"Cannot reach Windows MCP at {host}:{port}; start its HTTP/SSE server "
                               "and check WSL Windows interop. No LAN port or firewall rule was changed.")'''
    new = '''                if not connected:
                    route.error = (f"Cannot reach Windows MCP at {host}:{port}; start its HTTP/SSE server "
                                   "and check WSL Windows interop. No LAN port or firewall rule was changed.")'''
    assert old in text
    text = text.replace(old, new)
    p.write_text(text, encoding='utf-8')


def complete_validation():
    edit('tools/mcp_tool_server_run.py',
         'from tools.mcp_windows import InvalidMcpNetworkError',
         'from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network')
    edit('tools/mcp_tool_server_run.py',
         '            _errors._validate_remote_mcp_url(self.name, config.get("url"))',
         '            _errors._validate_remote_mcp_url(self.name, config.get("url"))\n            validate_mcp_network(config["url"], config.get("network", "auto"))')


harness = Path(__file__).with_name('run.py').read_text(encoding='utf-8')
harness = harness.replace('NEW = [', "NEW = ['tests/tools/test_mcp_windows_policy.py', ", 1)
harness = harness.replace("test = ['bash',", "test = [str(Path(os.environ.get('ProgramFiles', r'C:\\Program Files')) / 'Git/bin/bash.exe') if sys.platform == 'win32' else 'bash',", 1)
harness = harness.replace("'tests/tools/test_mcp_windows.py', '-q'", "'tests/tools/test_mcp_windows.py', 'tests/tools/test_mcp_windows_policy.py', '-q'", 1)
harness = harness.replace('\ncache_test()\nmode =', '\nharden_helper()\ncache_test()\nmode =', 1)
assert harness.count('    apply()\n') == 2
harness = harness.replace('    apply()\n', '    apply()\n    complete_validation()\n')
harness += '''
assert all(value == 0 for key, value in results.items() if key != 'red'), results
if mode == 'desktop':
    red = json.loads((OUT / 'red.json').read_text(encoding='utf-8'))
    green = json.loads((OUT / 'green.json').read_text(encoding='utf-8'))
    assert red['numFailedTests'] == 4, red
    assert green['numFailedTests'] == 0 and green['numPassedTests'] >= 41, green
'''
exec(compile(harness, str(Path(__file__).with_name('run.py')), 'exec'), globals())
