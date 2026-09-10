from pathlib import Path
files = {
'web/src/lib/mcp-network.test.ts': '''import { describe, expect, it } from "vitest";

import { buildMcpServerCreate, emptyMcpServerDraft } from "./mcp-server-create";

describe("MCP target shared by Add Server and Profile Builder", () => {
  it.each(["local", "windows"] as const)("retains %s on Streamable HTTP and SSE", network => {
    for (const httpTransport of ["http", "sse"] as const) {
      const body = buildMcpServerCreate({ ...emptyMcpServerDraft(), name: "unity", url: "http://localhost:8080/mcp", network, httpTransport });
      expect(body.network).toBe(network);
      expect(body.transport ?? "http").toBe(httpTransport);
      expect(body).not.toHaveProperty("command");
    }
  });

  it("keeps the compatible auto default and never leaks HTTP settings into stdio", () => {
    const draft = { ...emptyMcpServerDraft(), name: "unity", url: "http://localhost:8080/mcp" };
    expect(buildMcpServerCreate(draft)).toEqual({ name: "unity", url: draft.url });
    const body = buildMcpServerCreate({ ...draft, network: "windows", httpTransport: "sse", transport: "stdio", command: "python" });
    expect(body).not.toHaveProperty("network");
    expect(body).not.toHaveProperty("transport");
  });
});
''',
'apps/desktop/src/api/mcp-network.test.ts': '''import { afterEach, describe, expect, it, vi } from 'vitest'

import { parseMcpImport } from '@/lib/mcp-import'
import { getServers } from '@/lib/mcp-servers'

import { addMcpServer, installMcpCatalogEntry, saveMcpServers } from './mcp'

afterEach(() => vi.unstubAllGlobals())

describe('MCP network intent at the Desktop API boundary', () => {
  it('keeps the explicit owner and network through create, bulk save and catalog install', async () => {
    const api = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('hermesDesktop', { api })
    const scope = { connectionId: 'local', profile: 'unity' }
    const config = { url: 'http://localhost:8080/sse', network: 'windows' as const, transport: 'sse' as const }
    await addMcpServer({ name: 'unity', ...config }, scope)
    expect(api).toHaveBeenLastCalledWith(expect.objectContaining({ ...scope, body: { name: 'unity', ...config } }))
    await saveMcpServers({ unity: config }, scope)
    expect(api).toHaveBeenLastCalledWith(expect.objectContaining({ ...scope, body: { servers: { unity: config } } }))
    await installMcpCatalogEntry('unity', {}, scope, 'windows')
    expect(api).toHaveBeenLastCalledWith(expect.objectContaining({ ...scope, body: { name: 'unity', env: {}, enable: true, network: 'windows' } }))
  })

  it('round-trips pasted cross-environment SSE entries through the shared config reader', () => {
    const imported = parseMcpImport(JSON.stringify({ mcpServers: { unity: { type: 'sse', network: 'windows', url: 'http://localhost:8080/sse' } } }))
    expect(imported).toEqual([{ name: 'unity', config: { transport: 'sse', network: 'windows', url: 'http://localhost:8080/sse' } }])
    expect(getServers({ mcp_servers: Object.fromEntries(imported!.map(entry => [entry.name, entry.config])) }).unity).toEqual(imported![0].config)
  })
})
'''
}
for name, text in files.items():
    p = Path(name)
    assert not p.exists(), name
    p.write_text(text, encoding='utf-8')
