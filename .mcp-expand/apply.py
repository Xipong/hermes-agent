"""Fork-only patch transport for PR #107713, pinned to 3e19aab72403a73b7cf274dc062b25e00a4e004d."""
from pathlib import Path
ROOT = Path.cwd()

def edit(path, before, after):
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    assert text.count(before) == 1, (path, before[:100], text.count(before))
    p.write_text(text.replace(before, after), encoding='utf-8')

def add(path, text):
    p = ROOT / path
    assert not p.exists(), path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding='utf-8')

edit('tools/mcp_windows.py', 'def validate_mcp_network(url: str, network: str = "auto") -> None:', '''def validate_mcp_network_config(config: dict) -> None:
    """Validate explicit routing intent without opening sockets or loading the SDK."""
    if "network" not in config:
        return
    network = config["network"]
    if not isinstance(network, str) or network not in {"auto", "local", "windows"}:
        raise InvalidMcpNetworkError("MCP network must be auto, local, or windows")
    if not config.get("url"):
        raise InvalidMcpNetworkError("MCP network is only supported for HTTP/SSE servers, not stdio")
    # Environment placeholders are resolved by the runtime loader, which also
    # checks the final origin. Do not reject portable ${MCP_URL} configuration.
    url = config["url"]
    if network == "windows" and isinstance(url, str) and "${" not in url:
        try:
            endpoint = _loopback_endpoint(url)
        except ValueError:
            endpoint = None
        if endpoint is None:
            raise InvalidMcpNetworkError("network: windows requires an HTTP(S) loopback MCP URL")


@contextlib.asynccontextmanager
async def mcp_http_client(httpx, server_name: str, config: dict, **client_kwargs):
    """Route standalone MCP OAuth clients exactly like the resource transport.

    Each client owns its route. A cached OAuth provider must never retain a
    closed Unix socket or a route bound to another connection's event loop.
    Only the configured MCP origin is tunneled; external authorization servers
    keep their normal destination. This does not forward arbitrary redirects.
    """
    from tools.mcp_tool_errors import _resolve_client_cert

    verify = config.get("ssl_verify", True)
    cert = _resolve_client_cert(server_name, config)
    async with mcp_http_route(config["url"], network=config.get("network", "auto")) as route:
        options = route.client_options(httpx, verify=verify, cert=cert) if route else {}
        async with httpx.AsyncClient(
            **client_kwargs, verify=verify, **({"cert": cert} if cert is not None else {}), **options
        ) as client:
            yield client


def validate_mcp_network(url: str, network: str = "auto") -> None:''')
edit('tools/mcp_tool_server_run.py', 'from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network', 'from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network, validate_mcp_network_config')
edit('tools/mcp_tool_server_run.py', '        if not self._is_http():\n            return True\n        try:\n', '''        try:
            validate_mcp_network_config(config)
            if not self._is_http():
                return True
''')
edit('tools/mcp_schema_cache.py', '        "transport": config.get("transport"),', '        "transport": config.get("transport"),\n        "network": config.get("network", "auto"),')
edit('hermes_cli/mcp_config.py', 'def _validate_or_warn(name: str, server_config: dict) -> bool:', '''def _mcp_entry_issues(name: str, server_config: dict) -> list[str]:
    from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network_config

    issues = validate_mcp_server_entry(name, server_config)
    try:
        validate_mcp_network_config(server_config)
    except InvalidMcpNetworkError as exc:
        issues.append(f"Server '{name}': {exc}")
    return issues


def _validate_or_warn(name: str, server_config: dict) -> bool:''')
edit('hermes_cli/mcp_config.py', '    issues = validate_mcp_server_entry(name, server_config)\n    for issue in issues:', '    issues = _mcp_entry_issues(name, server_config)\n    for issue in issues:')
edit('hermes_cli/mcp_config.py', '        issues.extend(validate_mcp_server_entry(name, cfg))', '        issues.extend(_mcp_entry_issues(name, cfg))')
edit('hermes_cli/mcp_config.py', '    if raw_connect_timeout is not None:\n', '''    network = getattr(args, "network", None)
    transport = getattr(args, "transport", None)
    if network is not None:
        server_config["network"] = network
    if transport is not None:
        if not url:
            _error("--transport is only supported with an HTTP/SSE URL")
            return
        server_config["transport"] = transport
    if raw_connect_timeout is not None:
''')
edit('hermes_cli/mcp_config.py', '    """Reconfigure which tools are enabled for an existing MCP server."""\n', '''    """Reconfigure tools, or explicitly change the backend-relative network target."""
    network = getattr(args, "network", None)
    if network is not None:
        cfg = _lookup_server(args.name, _get_mcp_servers(), "Available")
        if cfg is not None and _save_mcp_server(args.name, {**cfg, "network": network}):
            _success(f"Saved network '{network}' for '{args.name}'")
            _info("Start a new session or explicitly reload MCP to apply the change.")
        return
''')
edit('hermes_cli/subcommands/mcp.py', '    mcp_add_p.add_argument("--auth",', '''    mcp_add_p.add_argument("--network", choices=["auto", "local", "windows"],
                           help="HTTP/SSE network target relative to the backend (default: auto)")
    mcp_add_p.add_argument("--transport", choices=["http", "sse"],
                           help="HTTP transport: Streamable HTTP or legacy SSE")
    mcp_add_p.add_argument("--auth",''')
edit('hermes_cli/subcommands/mcp.py', '    mcp_cfg_p.add_argument("name", help="Server name to configure")', '''    mcp_cfg_p.add_argument("name", help="Server name to configure")
    mcp_cfg_p.add_argument("--network", choices=["auto", "local", "windows"],
                           help="Set the HTTP/SSE network without opening the tool picker")''')
edit('hermes_cli/subcommands/mcp.py', '    mcp_install_p.add_argument("identifier", help="Catalog entry name (or `official/<name>`)")', '''    mcp_install_p.add_argument("identifier", help="Catalog entry name (or `official/<name>`)")
    mcp_install_p.add_argument("--network", choices=["auto", "local", "windows"],
                             help="HTTP catalog entry network (preserves prior choice on reinstall)")''')
edit('hermes_cli/web_models.py', '    url: Optional[str] = None\n    command: Optional[str] = None\n', '''    url: Optional[str] = None
    transport: Optional[Literal["http", "sse"]] = None
    network: Optional[Literal["auto", "local", "windows"]] = None
    command: Optional[str] = None
''')
edit('hermes_cli/web_models.py', 'class MCPCatalogInstall(BaseModel):\n    name: str', '''class MCPCatalogInstall(BaseModel):
    network: Optional[Literal["auto", "local", "windows"]] = None
    name: str''')
edit('hermes_cli/web_server_mcp.py', '    from hermes_cli.mcp_security import validate_mcp_server_entry', '    from hermes_cli.mcp_config import _mcp_entry_issues')
edit('hermes_cli/web_server_mcp.py', '    issues = validate_mcp_server_entry(name, server_config)', '''    if body.transport is not None:
        if not url:
            raise ValueError("HTTP/SSE transport requires a URL")
        server_config["transport"] = body.transport
    if body.network is not None:
        server_config["network"] = body.network
    issues = _mcp_entry_issues(name, server_config)''')
edit('hermes_cli/web_server_mcp.py', '    transport = "http" if cfg.get("url") else ("stdio" if cfg.get("command") else "unknown")', '    transport = (cfg.get("transport") or "http") if cfg.get("url") else ("stdio" if cfg.get("command") else "unknown")')
edit('hermes_cli/web_server_mcp.py', '        "transport": transport,', '        "transport": transport,\n        **({"network": cfg.get("network", "auto")} if cfg.get("url") else {}),')
edit('hermes_cli/agent_import.py', '        hermes_srv["url"] = srv["url"]', '''        hermes_srv["url"] = srv["url"]
        if "network" in srv:
            hermes_srv["network"] = srv["network"]
        transport = srv.get("transport", srv.get("type"))
        if isinstance(transport, str) and transport in {"http", "sse"}:
            hermes_srv["transport"] = transport''')
edit('hermes_cli/agent_import.py', '            existing[name] = hermes_srv', '''            from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network_config
            try:
                validate_mcp_network_config(hermes_srv)
            except InvalidMcpNetworkError as exc:
                self.record(kind, name, None, "skipped", str(exc))
                continue
            existing[name] = hermes_srv''')
edit('hermes_cli/mcp_catalog.py', 'def install_entry(entry: CatalogEntry, *, enable: bool = True) -> None:', 'def install_entry(entry: CatalogEntry, *, enable: bool = True, network: Optional[str] = None) -> None:')
edit('hermes_cli/mcp_catalog.py', '    print()\n    _say(f"  Installing MCP', '''    from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network_config

    if network is None and entry.transport.type == "http":
        network = (installed_servers().get(entry.name) or {}).get("network")
    if network is not None:
        try:
            validate_mcp_network_config({"url": entry.transport.url, "network": network})
        except InvalidMcpNetworkError as exc:
            raise CatalogError(str(exc)) from exc
    print()
    _say(f"  Installing MCP''')
edit('hermes_cli/mcp_catalog.py', '    server_cfg["enabled"] = enable', '    server_cfg["enabled"] = enable\n    if network is not None:\n        server_cfg["network"] = network')
edit('hermes_cli/mcp_picker.py', 'def install_by_name(identifier: str) -> int:', 'def install_by_name(identifier: str, *, network: str | None = None) -> int:')
edit('hermes_cli/mcp_picker.py', 'def _install(entry: CatalogEntry, verb: str) -> bool:', 'def _install(entry: CatalogEntry, verb: str, *, network: str | None = None) -> bool:')
edit('hermes_cli/mcp_picker.py', '        install_entry(entry, enable=True)', '        install_entry(entry, enable=True, **({"network": network} if network is not None else {}))')
edit('hermes_cli/mcp_picker.py', '    return 0 if _install(entry, "install") else 1', '    return 0 if _install(entry, "install", **({"network": network} if network is not None else {})) else 1')
edit('hermes_cli/mcp_config.py', 'mcp_picker.install_by_name(getattr(args, "identifier", "") or "")', 'mcp_picker.install_by_name(getattr(args, "identifier", "") or "", **({"network": args.network} if getattr(args, "network", None) is not None else {}))')
edit('hermes_cli/web_routers/mcp.py', '    # Catalog credentials are a closed schema:', '''    if body.network is not None:
        from tools.mcp_windows import InvalidMcpNetworkError, validate_mcp_network_config
        try:
            validate_mcp_network_config({"url": entry.transport.url, "network": body.network})
        except InvalidMcpNetworkError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Catalog credentials are a closed schema:''')
edit('hermes_cli/web_routers/mcp.py', '_profile_cli_args(effective_profile) + ["mcp", "install", name], action)', '_profile_cli_args(effective_profile) + ["mcp", "install", name] + (["--network", body.network] if body.network is not None else []), action)')
edit('hermes_cli/web_routers/mcp.py', 'mcp_catalog.install_entry(entry, enable=body.enable)', 'mcp_catalog.install_entry(entry, enable=body.enable, **({"network": body.network} if body.network is not None else {}))')
edit('tools/mcp_oauth_manager.py', '    pending_401: dict[str, "asyncio.Future[bool]"] = field(default_factory=dict)', '    pending_401: dict[str, "asyncio.Future[bool]"] = field(default_factory=dict)\n    http_config: dict = field(default_factory=dict)')
edit('tools/mcp_oauth_manager.py', 'def __init__(self, *args: Any, server_name: str = "", preregistered: bool = False, **kwargs: Any):', 'def __init__(self, *args: Any, server_name: str = "", preregistered: bool = False, http_config: dict | None = None, **kwargs: Any):')
edit('tools/mcp_oauth_manager.py', '        self._hermes_server_name = server_name', '        self._hermes_server_name = server_name\n        self._hermes_http_config = dict(http_config or {})')
edit('tools/mcp_oauth_manager.py', '        async with httpx.AsyncClient(timeout=10.0) as client:', '''        from tools.mcp_windows import mcp_http_client
        async with mcp_http_client(
            httpx, self._hermes_server_name, {**self._hermes_http_config, "url": server_url}, timeout=10.0
        ) as client:''')
edit('tools/mcp_oauth_manager.py', 'def get_or_build_provider(self, server_name: str, server_url: str, oauth_config: Optional[dict]) -> Optional[Any]:', 'def get_or_build_provider(self, server_name: str, server_url: str, oauth_config: Optional[dict], *, http_config: dict | None = None) -> Optional[Any]:')
edit('tools/mcp_oauth_manager.py', 'built on first use (rebuilt when ``server_url`` changes);', 'built on first use (rebuilt when endpoint or network/TLS settings change);')
edit('tools/mcp_oauth_manager.py', '        key = self._key(server_name)\n        with self._entries_lock:', '''        # Cache immutable routing settings, not a connection's Unix socket.
        http_config = {k: v for k, v in (http_config or {}).items()
                       if k in {"network", "ssl_verify", "client_cert", "client_key"}}
        key = self._key(server_name)
        with self._entries_lock:''')
edit('tools/mcp_oauth_manager.py', '            if entry is not None and entry.server_url != server_url:', '            if entry is not None and (entry.server_url != server_url or entry.http_config != http_config):')
edit('tools/mcp_oauth_manager.py', 'logger.info("MCP OAuth \'%s\': URL changed from %s to %s, discarding cache", server_name, entry.server_url, server_url)', 'logger.info("MCP OAuth \'%s\': endpoint or network/TLS settings changed, discarding provider cache", server_name)')
edit('tools/mcp_oauth_manager.py', '_ProviderEntry(server_url=server_url, oauth_config=oauth_config)', '_ProviderEntry(server_url=server_url, oauth_config=oauth_config, http_config=http_config)')
edit('tools/mcp_oauth_manager.py', 'server_name=server_name, preregistered=bool(cfg.get("client_id")), server_url=entry.server_url,', 'server_name=server_name, preregistered=bool(cfg.get("client_id")), server_url=entry.server_url, http_config=entry.http_config,')
edit('tools/mcp_tool_transport.py', 'get_or_build_provider(self.name, url, config.get("oauth"))', 'get_or_build_provider(self.name, url, config.get("oauth"), http_config=config)')
edit('hermes_cli/mcp_config.py', 'get_or_build_provider(name, url, server_config.get("oauth"))', 'get_or_build_provider(name, url, server_config.get("oauth"), http_config=server_config)')
edit('tools/mcp_oauth_device.py', 'async def login_device(name, server_url, oauth_config):', 'async def login_device(name, server_url, oauth_config, *, server_config: dict | None = None):')
edit('tools/mcp_oauth_device.py', '        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:', '''        from tools.mcp_windows import mcp_http_client
        async with mcp_http_client(
            httpx, name, {**(server_config or {}), "url": server_url}, timeout=10, follow_redirects=False
        ) as client:''')
edit('hermes_cli/mcp_config.py', 'asyncio.run(login_device(name, url, oauth_cfg))', 'asyncio.run(login_device(name, url, oauth_cfg, server_config=server_config))')
edit('web/src/lib/api.ts', 'export type McpHttpAuth = "none" | "header" | "oauth";', 'export type McpHttpAuth = "none" | "header" | "oauth";\nexport type McpNetwork = "auto" | "local" | "windows";')
edit('web/src/lib/api.ts', 'export interface McpServerCreate {\n  name: string;', 'export interface McpServerCreate {\n  name: string;\n  network?: McpNetwork;\n  transport?: "http" | "sse";')
edit('web/src/lib/api.ts', '  transport: "http" | "stdio" | "unknown";', '  transport: "http" | "sse" | "stdio" | "unknown";\n  network?: McpNetwork;')
edit('web/src/lib/mcp-server-create.ts', 'import type { McpHttpAuth, McpServerCreate }', 'import type { McpHttpAuth, McpNetwork, McpServerCreate }')
edit('web/src/lib/mcp-server-create.ts', '  transport: McpTransport;', '  transport: McpTransport;\n  network: McpNetwork;\n  httpTransport: "http" | "sse";')
edit('web/src/lib/mcp-server-create.ts', '    transport: "http",', '    transport: "http",\n    network: "auto",\n    httpTransport: "http",')
edit('web/src/lib/mcp-server-create.ts', '    const server: McpServerCreate = { name, url };', '''    const server: McpServerCreate = { name, url };
    // Omitted defaults remain compatible with older backends/configs.
    if (draft.network !== "auto") server.network = draft.network;
    if (draft.httpTransport === "sse") server.transport = "sse";''')
add('web/src/components/McpNetworkFields.tsx', '''import { Label } from "@nous-research/ui/ui/components/label";
import { Select, SelectOption } from "@nous-research/ui/ui/components/select";
import type { McpNetwork } from "@/lib/api";

interface McpNetworkFieldsProps {
  id: string;
  network: McpNetwork;
  transport: "http" | "sse";
  onNetworkChange: (value: McpNetwork) => void;
  onTransportChange: (value: "http" | "sse") => void;
}

export function McpNetworkFields({ id, network, transport, onNetworkChange, onTransportChange }: McpNetworkFieldsProps) {
  return <>
    <div className="grid gap-2">
      <Label htmlFor={`${id}-network`}>Network target</Label>
      <Select id={`${id}-network`} value={network} onValueChange={value => onNetworkChange(value as McpNetwork)}>
        <SelectOption value="auto">Automatic (backend first, then Windows from WSL)</SelectOption>
        <SelectOption value="local">Backend only</SelectOption>
        <SelectOption value="windows">Windows loopback</SelectOption>
      </Select>
      <p className="text-xs text-muted-foreground">Relative to the selected backend, not this browser. Windows loopback requires a WSL or Windows backend and a localhost URL.</p>
    </div>
    <div className="grid gap-2">
      <Label htmlFor={`${id}-http-transport`}>HTTP protocol</Label>
      <Select id={`${id}-http-transport`} value={transport} onValueChange={value => onTransportChange(value as "http" | "sse")}>
        <SelectOption value="http">Streamable HTTP</SelectOption>
        <SelectOption value="sse">Legacy SSE</SelectOption>
      </Select>
    </div>
  </>;
}
''')
edit('web/src/pages/McpPage.tsx', '  McpHttpAuth,', '  McpHttpAuth,\n  McpNetwork,')
edit('web/src/pages/McpPage.tsx', 'import { completeMcpDashboardOAuth }', 'import { McpNetworkFields } from "@/components/McpNetworkFields";\nimport { completeMcpDashboardOAuth }')
edit('web/src/pages/McpPage.tsx', '  const [url, setUrl] = useState("");', '''  const [url, setUrl] = useState("");
  const [network, setNetwork] = useState<McpNetwork>("auto");
  const [httpTransport, setHttpTransport] = useState<"http" | "sse">("http");''')
edit('web/src/pages/McpPage.tsx', '        transport,\n        url,', '        transport,\n        network,\n        httpTransport,\n        url,')
edit('web/src/pages/McpPage.tsx', '      setName("");', '      setName("");\n      setNetwork("auto");\n      setHttpTransport("http");')
edit('web/src/pages/McpPage.tsx', '              {transport === "http" ? (\n                <>', '''              {transport === "http" ? (
                <>
                  <McpNetworkFields id="mcp" network={network} transport={httpTransport}
                    onNetworkChange={setNetwork} onTransportChange={setHttpTransport} />''')
edit('web/src/pages/ProfileBuilderPage.tsx', 'import {\n  buildMcpServerCreate,', 'import { McpNetworkFields } from "@/components/McpNetworkFields";\nimport {\n  buildMcpServerCreate,')
edit('web/src/pages/ProfileBuilderPage.tsx', '                {mcpDraft.transport === "http" ? (\n                  <>', '''                {mcpDraft.transport === "http" ? (
                  <>
                    <McpNetworkFields id="pb-mcp" network={mcpDraft.network} transport={mcpDraft.httpTransport}
                      onNetworkChange={network => setMcpDraft({ ...mcpDraft, network })}
                      onTransportChange={httpTransport => setMcpDraft({ ...mcpDraft, httpTransport })} />''')
edit('web/src/pages/McpPage.tsx', '                    {server.transport === "http" ? (', '                    {server.url ? (')
edit('web/src/pages/McpPage.tsx', '                    {!server.enabled && <Badge tone="outline">disabled</Badge>}', '''                    {server.network && <Badge tone="outline">network: {server.network}</Badge>}
                    {!server.enabled && <Badge tone="outline">disabled</Badge>}''')
edit('web/src/lib/api.ts', '    enable = true,\n  ) =>\n    fetchJSON<{ ok: boolean; name: string; background: boolean; action?: string }>(', '    enable = true,\n    network?: McpNetwork,\n  ) =>\n    fetchJSON<{ ok: boolean; name: string; background: boolean; action?: string }>(')
edit('web/src/lib/api.ts', 'body: JSON.stringify({ name, env, enable }),', 'body: JSON.stringify({ name, env, enable, ...(network ? { network } : {}) }),')
edit('apps/desktop/src/api/mcp.ts', '''  profile?: ProfileScope
): Promise<{ ok: boolean; name?: string; pid?: number; action?: string; background?: boolean }>''', '''  profile?: ProfileScope,
  network?: 'auto' | 'local' | 'windows'
): Promise<{ ok: boolean; name?: string; pid?: number; action?: string; background?: boolean }>''')
edit('apps/desktop/src/api/mcp.ts', '    body: { name, env, enable: true },', '    body: { name, env, enable: true, ...(network ? { network } : {}) },')
edit('apps/desktop/src/api/mcp.ts', '    url?: string\n    command?: string', "    url?: string\n    network?: 'auto' | 'local' | 'windows'\n    transport?: 'http' | 'sse'\n    command?: string")
edit('apps/desktop/src/types/hermes.ts', 'export interface McpServerSummary {\n  name: string\n  transport: string', "export interface McpServerSummary {\n  name: string\n  transport: string\n  network?: 'auto' | 'local' | 'windows'")
edit('hermes_cli/mcp_config.py', '        print(f"  {name:<16} {transport:<30} {tools_str:<12} {status}")', '        print(f"  {name:<16} {transport:<30} {tools_str:<12} {status}")\n        if cfg.get("url") and "network" in cfg:\n            _info(f"Network: {cfg[\'network\']}")')
edit('hermes_cli/mcp_picker.py', 'def _handle_row(row: _Row) -> None:', '''def _network_actions(name: str) -> list:
    from hermes_cli.mcp_config import _get_mcp_servers, cmd_mcp_configure
    from types import SimpleNamespace

    if not (_get_mcp_servers().get(name) or {}).get("url"):
        return []

    def choose():
        labels = {"auto": "Automatic (backend first, then Windows from WSL)",
                  "local": "Backend only", "windows": "Windows loopback"}
        _run_submenu(f"Network target for '{name}'", [
            (label, lambda value=value: cmd_mcp_configure(SimpleNamespace(name=name, network=value)))
            for value, label in labels.items()
        ])

    return [("Network target (HTTP/SSE)", choose)]


def _handle_row(row: _Row) -> None:''')
edit('hermes_cli/mcp_picker.py', '        _run_submenu(f"Action for \'{row.name}\' (custom)", [', '        _run_submenu(f"Action for \'{row.name}\' (custom)", [\n            *_network_actions(row.name),')
edit('hermes_cli/mcp_picker.py', '    _run_submenu(f"Action for \'{row.name}\'", [', '    _run_submenu(f"Action for \'{row.name}\'", [\n        *_network_actions(row.name),')
edit('acp_adapter/server.py', '    return {"url": server.url, "headers": {i.name: i.value for i in server.headers}}', '    return {"url": server.url, "headers": {i.name: i.value for i in server.headers},\n            **({"transport": "sse"} if isinstance(server, McpServerSse) else {})}')
edit('tests/tools/test_mcp_windows.py', '"serverInfo": {"name": "unity-fixture", "version": "1"}, "capabilities": {"tools": {}}},', '"serverInfo": {"name": "unity-fixture", "version": "1"}, "capabilities": {"tools": {}, "prompts": {}, "resources": {}}},')
edit('tests/tools/test_mcp_windows.py', '                "ping": {},', '''                "prompts/list": {"prompts": [{"name": "scene"}]},
                "prompts/get": {"messages": [{"role": "user", "content": {"type": "text", "text": "scene prompt"}}]},
                "resources/list": {"resources": [{"name": "scene", "uri": "scene://active"}]},
                "resources/templates/list": {"resourceTemplates": []},
                "resources/read": {"contents": [{"uri": "scene://active", "text": "scene data"}]},
                "ping": {},''')
edit('tests/tools/test_mcp_windows.py', '            assert result.content[0].text == "pong"', '''            assert result.content[0].text == "pong"
            prompts = await task.session.list_prompts()
            assert prompts.prompts[0].name == "scene"
            prompt = await task.session.get_prompt("scene")
            assert prompt.messages[0].content.text == "scene prompt"
            resources = await task.session.list_resources()
            from pydantic import AnyUrl
            resource = await task.session.read_resource(AnyUrl(str(resources.resources[0].uri)))
            assert resource.contents[0].text == "scene data"''')
edit('evals/mcp_device_flow.py', 'def oauth_fixture(mode="success"):', 'def oauth_fixture(mode="success", *, advertised_base: str | None = None):')
edit('evals/mcp_device_flow.py', '    base = f"http://127.0.0.1:{server.server_port}"', '    direct_base = f"http://127.0.0.1:{server.server_port}"\n    base = advertised_base or direct_base')
edit('evals/mcp_device_flow.py', '        yield base, wire', '        yield direct_base, wire')
edit('website/docs/user-guide/features/mcp.md', '## mTLS / client certificates', '''### Configuring the target across Hermes surfaces

The network target belongs to the **server configuration in the selected profile**.
CLI, TUI, Desktop, dashboard, messaging gateway, scheduled runs and ACP use the
same MCP runtime. HTTP/SSE sessions carry tools, prompts and resources through the
same route. Ordinary backend-local and remote non-loopback URLs remain direct.

```bash
hermes mcp add unity --url http://localhost:8080/mcp --network windows
hermes mcp add unity-sse --url http://localhost:8080/sse --transport sse --network windows
hermes mcp configure unity --network local
hermes mcp install <catalog-entry> --network windows
```

The MCP picker has a **Network target (HTTP/SSE)** action for configured URL
servers. The dashboard Add Server and Profile Builder forms expose both the
network target and HTTP/SSE protocol. Desktop's MCP JSON editor/importer accepts
the same `network` and `transport` fields. The structured create/bulk-save APIs
and HTTP catalog install API preserve these choices; catalog reinstall retains
an existing network choice unless explicitly overridden.

Browser OAuth requests use the session route. Device-code login and cold-start
OAuth metadata discovery also use the configured route and TLS settings, with
separate connection lifetimes. A different authorization-server origin remains
direct rather than being sent to the MCP loopback listener. In-memory OAuth
providers and the on-disk tool-schema cache are invalidated when network intent
changes; existing prompt/tool snapshots still follow the normal new-session or
explicit MCP reload policy.

ACP-supplied HTTP and SSE servers use automatic routing, and SSE remains SSE.
ACP's standard server description does not provide Hermes' explicit `network`
selector. Set explicit targets in Hermes' own profile configuration instead.
Import from supported other-agent JSON configurations preserves explicit network
and HTTP/SSE fields without importing literal credentials.

Invalid network names, explicit Windows targeting of non-loopback URLs, and
network options on stdio entries are rejected rather than silently ignored.
These choices do **not** import another OS installation's config, translate
stdio executables or filesystem paths, scan for unconfigured application ports,
or add reverse Windows-to-WSL tunneling.

## mTLS / client certificates''')
