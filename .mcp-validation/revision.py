"""Fork-only validation: native Windows, routing policy and strict gates.
Neither this harness nor its workflow enters either product PR.
"""
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')


def harden_helper():
    p = ROOT / 'tools/mcp_windows.py'
    text = p.read_text(encoding='utf-8')
    old_connect = '''$client = [System.Net.Sockets.TcpClient]::new()
try {{
    $connect = $client.ConnectAsync('{host}', {port})
    if (-not $connect.Wait(10000)) {{ throw 'Windows loopback connection timed out' }}
    $connect.GetAwaiter().GetResult()'''
    new_connect = '''$client = $null
try {{
    # Windows PowerShell's .NET Framework default TcpClient is IPv4-only.
    # Resolve localhost to fixed loopback literals, never an arbitrary DNS IP.
    $addresses = if ('{host}' -eq 'localhost') {{ @('127.0.0.1', '::1') }} else {{ @('{host}') }}
    foreach ($address in $addresses) {{
        $family = if ($address -eq '::1') {{ [System.Net.Sockets.AddressFamily]::InterNetworkV6 }} else {{ [System.Net.Sockets.AddressFamily]::InterNetwork }}
        $candidate = [System.Net.Sockets.TcpClient]::new($family)
        try {{
            $connect = $candidate.ConnectAsync($address, {port})
            if (-not $connect.Wait(10000)) {{ throw 'Windows loopback connection timed out' }}
            # PowerShell must not emit the Task's VoidTaskResult to stdout.
            [void]$connect.GetAwaiter().GetResult()
            $client = $candidate
            break
        }} catch {{
            $candidate.Dispose()
        }}
    }}
    if ($null -eq $client) {{ throw 'Windows loopback connection failed' }}'''
    assert old_connect in text
    text = text.replace(old_connect, new_connect)
    text = text.replace('    $client.Dispose()\n}}', '    if ($null -ne $client) {{ $client.Dispose() }}\n}}')
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
    test = ROOT / 'tests/tools/test_mcp_windows.py'
    text = test.read_text(encoding='utf-8')
    text = text.replace('async def test_native_powershell_bridge_carries_binary_bytes_and_exits_on_stdin_eof():', '''@pytest.mark.parametrize("host,bind_host", [("127.0.0.1", "127.0.0.1"), ("localhost", "127.0.0.1"),
                                          ("::1", "::1"), ("localhost", "::1")])
async def test_native_powershell_bridge_carries_binary_bytes_and_exits_on_stdin_eof(host, bind_host):''')
    text = text.replace('    import socketserver\n', '    import socket\n    import socketserver\n')
    text = text.replace('    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Echo) as server:', '''    class EchoServer(socketserver.ThreadingTCPServer):
        address_family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET

    with EchoServer((bind_host, 0), Echo) as server:''')
    text = text.replace('mcp_windows._windows_tunnel_command("127.0.0.1", server.server_address[1])', 'mcp_windows._windows_tunnel_command(host, server.server_address[1])')
    test.write_text(text, encoding='utf-8')


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
