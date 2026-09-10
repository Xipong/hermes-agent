"""Fork-only validation harness; never included in the product PR."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path.cwd()
INPUT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'validation-output'
OUT.mkdir(exist_ok=True)
NEW = ['tools/mcp_windows.py', 'tests/tools/test_mcp_windows.py',
       'apps/desktop/src/api/config.test.ts', 'apps/desktop/src/app/skills/mcp-tab.test.tsx']
CHANGED = NEW + ['tools/mcp_tool_transport.py', 'tools/mcp_tool_server_run.py',
    'apps/desktop/src/api/config.ts', 'apps/desktop/src/app/skills/mcp-tab.tsx',
    'apps/desktop/src/lib/mcp-probe-cache.ts', 'apps/desktop/src/lib/mcp-probe-cache.test.ts',
    'cli-config.yaml.example', 'website/docs/reference/mcp-config-reference.md',
    'website/docs/user-guide/features/mcp.md']
for name in NEW:
    shutil.copyfile(INPUT / name, ROOT / name)


def edit(name, old, new):
    p = ROOT / name
    text = p.read_text(encoding='utf-8')
    assert text.count(old) == 1, (name, old[:80], text.count(old))
    p.write_text(text.replace(old, new), encoding='utf-8')


def cache_test():
    edit('apps/desktop/src/lib/mcp-probe-cache.test.ts', "  it('ignores non-connection fields", """  it('invalidates results when the same URL targets a different network namespace', () => {
    const server = { url: 'http://localhost:8080/mcp', network: 'local' }
    expect(probeKey('unity', server, 'default')).not.toBe(
      probeKey('unity', { ...server, network: 'windows' }, 'default')
    )
  })

  it('ignores non-connection fields""")


def apply():
    edit('apps/desktop/src/api/config.ts', "    ...capabilityScoped(profile),\n    path: '/api/config'\n", "    ...capabilityScoped(profile),\n    path: '/api/config',\n    timeoutMs: STARTUP_REQUEST_TIMEOUT_MS\n")
    p = ROOT / 'apps/desktop/src/app/skills/mcp-tab.tsx'
    s = p.read_text(encoding='utf-8')
    s = s.replace('    errorUpdatedAt: configErroredAt\n', '').replace('    dataUpdatedAt: configUpdatedAt,\n', '    dataUpdatedAt: configUpdatedAt\n')
    s = s.replace('  const staleErrorStamp = useRef<null | number>(null)\n', '')
    s = s.replace('  useOnProfileSwitch(() => {\n', '''  useOnProfileSwitch(() => {
    // Explicit scopes belong to the Capabilities selector, not the foreground
    // chat. SkillsView keys this tab by that scope and remounts it on a REAL
    // owner change. Resetting a pinned tab here loses its draft and can leave
    // Add/Import waiting forever for an unrelated query timestamp to change.
    if (profile != null) {
      return
    }

''')
    s = s.replace('    staleErrorStamp.current = configErroredAt\n', '')
    start = s.index('  // Clear once the config query settles for the new profile:')
    end = s.index('\n', s.index('  }, [profilePending, configUpdatedAt, configErroredAt])', start))
    s = s[:start] + '''  // Only a successful read may unlock writes for the new owner. React Query
  // keeps cached data after a failed refetch: releasing on error would let A's
  // server map be saved into B. The error pane below offers Retry while locked.
  // eslint-disable-next-line no-restricted-syntax -- legitimate non-atom ref write (see eslint rule comment)
  useEffect(() => {
    if (profilePending && staleConfigStamp.current !== null && configUpdatedAt !== staleConfigStamp.current) {
      setProfilePending(false)
      staleConfigStamp.current = null
    }
  }, [profilePending, configUpdatedAt])''' + s[end:]
    s = s.replace('  if (configFailed && !config) {', '  if (configFailed && (!config || profilePending)) {')
    s = s.replace('  if (!config) {\n    return <PageLoader', '  if (!config || profilePending) {\n    return <PageLoader')
    p.write_text(s, encoding='utf-8')
    edit('apps/desktop/src/lib/mcp-probe-cache.ts', 'server.transport, server.auth])', 'server.transport, server.auth, server.network])')

    p = ROOT / 'tools/mcp_tool_transport.py'
    s = p.read_text(encoding='utf-8')
    s = s.replace('from tools.mcp_tool_common import _core', 'from tools.mcp_tool_common import _core\nfrom tools.mcp_windows import mcp_http_route')
    s = s.replace('ssl_verify: bool = True, client_cert=None, timeout: float = 5.0) -> None:', 'ssl_verify: bool = True, client_cert=None, timeout: float = 5.0,\n                                      network: str = "auto") -> None:')
    start = s.index('            async with _httpx.AsyncClient(verify=ssl_verify')
    end = s.index('\n        except _httpx.HTTPError:', start)
    block = s[start:end].replace('**_present(cert=client_cert)) as client:', '**_present(cert=client_cert),\n                                          **(route.client_options(_httpx, verify=ssl_verify, cert=client_cert)\n                                             if route else {})) as client:')
    s = s[:start] + '            async with mcp_http_route(url, network=network, connect_timeout=timeout) as route:\n' + '\n'.join('    ' + line for line in block.splitlines()) + s[end:]
    s = s.replace('        except _httpx.HTTPError:', '        except (_httpx.HTTPError, ConnectionError):')
    s = s.replace('ssl_verify, client_cert, oauth_auth, strict_cfg_headers: bool):', 'ssl_verify, client_cert, oauth_auth, strict_cfg_headers: bool, route=None):')
    s = s.replace('        if client_cert is not None or ssl_verify is not True:', '        if route or client_cert is not None or ssl_verify is not True:')
    s = s.replace('                **_present(headers=headers, auth=auth, cert=client_cert))', '                **_present(headers=headers, auth=auth, cert=client_cert),\n                **(route.client_options(_httpx_mod, verify=ssl_verify, cert=client_cert) if route else {}))')
    s = s.replace('strict_cfg_headers: bool, configured_header_names: set):', 'strict_cfg_headers: bool, configured_header_names: set, route=None):')
    s = s.replace('        if not _core._MCP_NEW_HTTP:\n            if strict_cfg_headers:', '        if not _core._MCP_NEW_HTTP:\n            if route:\n                raise ImportError("Windows loopback MCP requires mcp >= 1.24.0; upgrade MCP support")\n            if strict_cfg_headers:')
    s = s.replace('                               **_present(auth=oauth_auth, cert=client_cert)}', '                               **_present(auth=oauth_auth, cert=client_cert),\n                               **(route.client_options(httpx, verify=ssl_verify, cert=client_cert) if route else {})}')
    start = s.index('        common = (url, headers, connect_timeout,')
    end = s.index('\n\n    # -------------------------------------------------------------- discovery', start)
    s = s[:start] + '''        async with mcp_http_route(url, network=config.get("network", "auto"),
                                  connect_timeout=float(connect_timeout)) as route:
            common = (url, headers, connect_timeout, config.get("ssl_verify", True), _resolve_client_cert(self.name, config),
                      self._build_oauth_auth(url, config), bool(config.get("strict_redirect_headers")))
            if config.get("transport") == "sse":
                transport, label = self._sse_transport(*common, route=route), "SSE"
            else:
                transport = self._streamable_http_transport(*common, configured_header_names, route=route)
                label = "HTTP" if _core._MCP_NEW_HTTP else "legacy HTTP"
            return await self._serve_transport(transport, label, float(connect_timeout))''' + s[end:]
    p.write_text(s, encoding='utf-8')
    edit('tools/mcp_tool_server_run.py', 'from tools import mcp_tool_sampling as _sampling', 'from tools import mcp_tool_sampling as _sampling\nfrom tools.mcp_windows import InvalidMcpNetworkError')
    edit('tools/mcp_tool_server_run.py', '                    client_cert=_errors._resolve_client_cert(self.name, config))', '                    client_cert=_errors._resolve_client_cert(self.name, config),\n                    **({"network": config["network"]} if "network" in config else {}))')
    edit('tools/mcp_tool_server_run.py', 'except (_errors.InvalidMcpUrlError, _errors.NonMcpEndpointError) as exc:', 'except (_errors.InvalidMcpUrlError, _errors.NonMcpEndpointError, InvalidMcpNetworkError) as exc:')

    edit('cli-config.yaml.example', '# Optional per-server settings:\n', '# Optional per-server settings:\n#   network: auto | local | windows (HTTP/SSE only; default: auto).\n#     On WSL, auto tries local loopback first, then Windows loopback over\n#     Windows interop. windows explicitly selects the Windows listener;\n#     local disables bridging. Other hosts and non-loopback URLs stay direct.\n')
    edit('website/docs/reference/mcp-config-reference.md', '    headers: {}\n', '    headers: {}\n    network: auto      # auto | local | windows; see WSL-to-Windows guide\n')
    edit('website/docs/reference/mcp-config-reference.md', '| `headers` | mapping | HTTP | Headers for remote server requests |', '| `headers` | mapping | HTTP | Headers for remote server requests |\n| `network` | string | HTTP/SSE | `auto` (default): in WSL, try local loopback first, then Windows loopback through Windows interop. `local`: disable bridging. `windows`: explicitly select Windows loopback (requires a WSL or native Windows backend and a loopback URL). See [Windows MCP servers from WSL](/user-guide/features/mcp#windows-mcp-servers-from-wsl). |')
    edit('website/docs/user-guide/features/mcp.md', '## mTLS / client certificates', '''## Windows MCP servers from WSL

When the Hermes **backend** runs in WSL and an HTTP MCP server runs on Windows
(for example, in Unity), the same `localhost` URL can name different machines.
Hermes tries the WSL-local listener first. If no local TCP listener is reachable,
it automatically reaches Windows loopback through Windows interop. Native Windows,
macOS, ordinary Linux, and non-loopback URLs retain their normal direct connection.

Keep the server's original URL. For example, when Unity displays
`http://localhost:8080/mcp`, paste that URL into Desktop's MCP editor or use:

```yaml
mcp_servers:
  unity:
    url: http://localhost:8080/mcp  # use the actual port/path shown by your server
    network: windows
```

`network: windows` selects Windows explicitly, including when an unrelated WSL
service occupies the same port. Omit it (or use `auto`) for local-first detection;
use `local` to prohibit crossing into Windows. The setting also works with
`transport: sse`. The MCP tool probe and runtime connection use the same routing.
Changing `network` invalidates Desktop's cached probe result.

The bridge uses Windows PowerShell via WSL interop and a private Unix socket. It
opens **no TCP listening port** and changes no Windows firewall rules. It preserves
the configured URL, HTTP Host, TLS certificate verification/SNI, and authentication
headers. Only the configured loopback origin uses the bridge; another redirect
origin is not tunneled to that local server. The current MCP dependency supports
this path; old Streamable HTTP SDKs below 1.24 require upgrading.

Windows interop and `powershell.exe` must be available, and the Windows MCP server
must be running. The server may remain bound to Windows loopback; changing its bind
to `0.0.0.0` or adding a LAN firewall exception is unnecessary. A bridge failure
reports the endpoint and an interop/start-server hint without logging credentials.

Routing is relative to the **selected backend**, not the Desktop window. A remote
Linux gateway cannot use this setting to reach your PC's Windows localhost.
This feature does not import another installation's MCP configuration, translate
stdio executables/arguments, or make Windows filesystem paths valid inside WSL.

## mTLS / client certificates''')


def run(label, command, cwd=ROOT):
    env = {**os.environ, 'HERMES_TEST_FILE_RETRIES': '0', 'NO_COLOR': '1'}
    with (OUT / (label + '.log')).open('w', encoding='utf-8') as log:
        print(label, command, flush=True)
        result = subprocess.run(command, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=700)
    text = (OUT / (label + '.log')).read_text(encoding='utf-8', errors='replace')
    print(text[-18000:], flush=True)
    return result.returncode


cache_test()
mode = sys.argv[1]
results = {}
if mode == 'python':
    test = ['bash', 'scripts/run_tests.sh', '-j', '4', '--file-timeout', '180', 'tests/tools/test_mcp_windows.py', '-q', '--tb=short']
    if sys.platform != 'win32':
        results['red'] = run('red', test + ['-k', 'real_mcp_probe_and_runtime'])
    apply()
    results['green'] = run('green', test)
    neighbors = [str(p) for p in (ROOT / 'tests/tools').glob('test_mcp*.py') if p.name in {
        'test_mcp_preflight_content_type.py', 'test_mcp_sse_transport.py', 'test_mcp_streamable_http_arity.py',
        'test_mcp_protocol_negotiation.py', 'test_mcp_probe.py', 'test_mcp_client_cert.py',
        'test_mcp_tool_issue_948.py', 'test_mcp_tool.py', 'test_mcp_http_redirect_headers.py'}]
    if sys.platform != 'win32':
        results['neighbors'] = run('neighbors', ['bash', 'scripts/run_tests.sh', '-j', '4', '--file-timeout', '180', *neighbors, '-q', '--tb=short'])
    results['ruff'] = run('ruff', [sys.executable, '-m', 'ruff', 'check', *[p for p in CHANGED if p.endswith('.py')]])
elif mode == 'desktop':
    cwd = ROOT / 'apps/desktop'
    ui = ['src/api/config.test.ts', 'src/app/skills/mcp-tab.test.tsx', 'src/lib/mcp-probe-cache.test.ts']
    vitest = ['node', '../../node_modules/vitest/vitest.mjs', 'run', '--project', 'ui']
    results['red'] = run('red', vitest + ui + ['--reporter=json', '--outputFile=' + str(OUT / 'red.json')], cwd)
    apply()
    ts = [str(ROOT / p) for p in CHANGED if p.endswith(('.ts', '.tsx'))]
    results['eslint'] = run('eslint', ['node', '../../node_modules/eslint/bin/eslint.js', '--fix', *ts], cwd)
    results['format'] = run('format', ['node', '../../node_modules/prettier/bin/prettier.cjs', '--write', *ts], cwd)
    results['green'] = run('green', vitest + ui + ['src/lib/mcp-servers.test.ts', 'src/lib/mcp-import.test.ts', 'src/api/client.test.ts', '--reporter=json', '--outputFile=' + str(OUT / 'green.json')], cwd)
    results['typecheck'] = run('typecheck', ['node', '../../node_modules/typescript/bin/tsc', '-p', '.', '--noEmit'], cwd)
else:
    raise ValueError(mode)
subprocess.run(['git', 'add', '-N', *NEW], check=True)
patch = subprocess.check_output(['git', 'diff', '--binary', '--', *CHANGED])
(OUT / 'candidate.patch').write_bytes(patch)
(OUT / 'results.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
print(results, flush=True)
assert results.get('red', 1) != 0, 'regression must fail on baseline'
assert results['green'] == 0, results
