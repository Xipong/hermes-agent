from pathlib import Path
root = Path.cwd()
p = root / 'apps/desktop/src/app/skills/index.test.tsx'
s = p.read_text(encoding='utf-8')
s = s.replace('const getSkillContent = vi.fn()', '''const getSkillContent = vi.fn()
const getComputerUseStatus = vi.fn()
const saveHermesConfigRecord = vi.fn()
const runToolsetPostSetup = vi.fn()
const getActionStatus = vi.fn()''', 1)
s = s.replace('  getSkillContent: (name: string, profile?: null | string) => getSkillContent(name, profile)', '''  getSkillContent: (name: string, profile?: null | string) => getSkillContent(name, profile),
  getComputerUseStatus: (profile?: HermesApi.ProfileScope) => getComputerUseStatus(profile),
  saveHermesConfigRecord: (config: unknown, profile?: HermesApi.ProfileScope) => saveHermesConfigRecord(config, profile),
  runToolsetPostSetup: (name: string, key: string, profile?: HermesApi.ProfileScope) =>
    runToolsetPostSetup(name, key, profile),
  getActionStatus: (name: string, lines?: number, profile?: HermesApi.ProfileScope) =>
    getActionStatus(name, lines, profile)''', 1)
s += '''

describe('Computer Use target and provider matrix integration', { timeout: 60_000 }, () => {
  it.each([false, true])('refreshes the real install panel without losing an active setup: %s', async installing => {
    let target = 'auto'
    let complete!: (value: { name: string; running: boolean; exit_code: number; lines: string[] }) => void
    const completion = new Promise<{ name: string; running: boolean; exit_code: number; lines: string[] }>(resolve => {
      complete = resolve
    })

    getToolsets.mockResolvedValue([toolset({ name: 'computer_use', label: 'Computer Use', tools: ['computer_use'] })])
    getComputerUseStatus.mockImplementation(async () => ({
      platform: 'linux', platform_supported: true, is_wsl: true, target,
      installed: target !== 'windows', ready: target !== 'windows', can_grant: false, checks: [],
      driver_platform: target === 'windows' ? null : 'linux',
      driver_command: target === 'windows' ? null : '/usr/bin/cua-driver'
    }))
    getToolsetConfig.mockImplementation(async () => ({
      name: 'computer_use', has_category: true, active_provider: 'cua-driver',
      providers: [{
        name: 'cua-driver', badge: 'local', tag: 'Desktop control', env_vars: [],
        post_setup: 'cua_driver', requires_nous_auth: false, is_active: true,
        status: target === 'windows' ? 'needs_setup' : 'ready'
      }]
    }))
    saveHermesConfigRecord.mockImplementation(async (config: { computer_use: { target: string } }) => {
      target = config.computer_use.target
      return { ok: true }
    })
    runToolsetPostSetup.mockResolvedValue({ ok: true, name: 'install-cua' })
    getActionStatus.mockReturnValue(completion)

    await renderSkills()
    const rerun = await screen.findByRole('button', { name: 'Re-run setup' })
    const initialConfigCalls = getToolsetConfig.mock.calls.length
    const scope = getToolsetConfig.mock.calls.at(-1)?.[1]

    if (installing) {
      fireEvent.click(rerun)
      // Wait until the existing runner owns a live poll. A remount would
      // abandon this poll and reset the busy state despite the running action.
      await waitFor(() => expect(getActionStatus).toHaveBeenCalled(), { timeout: 5000 })
    }

    fireEvent.click(await screen.findByRole('button', { name: 'Windows host' }))
    await waitFor(() => expect(getToolsetConfig.mock.calls.length).toBeGreaterThan(initialConfigCalls))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Windows host' }).getAttribute('aria-pressed')).toBe('true'))
    expect(saveHermesConfigRecord).toHaveBeenCalledWith({ computer_use: { target: 'windows' } }, scope)
    expect(getToolsetConfig).toHaveBeenLastCalledWith('computer_use', scope)
    expect(screen.getByText(/Install the cua-driver backend below/)).toBeTruthy()
    expect(screen.queryByText('Installed')).toBeNull()

    if (installing) {
      expect(screen.getByRole('button', { name: 'Installing…' }).hasAttribute('disabled')).toBe(true)
      await act(async () => complete({ name: 'install-cua', running: false, exit_code: 0, lines: ['finished'] }))
      await waitFor(() => expect(screen.queryByRole('button', { name: 'Installing…' })).toBeNull())
      expect(runToolsetPostSetup).toHaveBeenCalledTimes(1)
      expect(getActionStatus).toHaveBeenCalledTimes(1)
    }

    expect(await screen.findByRole('button', { name: 'Run setup' })).toBeTruthy()
  })
})
'''
p.write_text(s, encoding='utf-8')
p = root / 'apps/desktop/src/app/settings/computer-use-panel.test.tsx'
s = p.read_text(encoding='utf-8')
old = "    expect(screen.getByText(/through WSL/)).toBeTruthy()"
assert s.count(old) == 1
s = s.replace(old, "    expect(screen.getByRole('button', { name: 'Automatic' }).getAttribute('aria-pressed')).toBe('true')")
s += '''

it.each(['macos', 'darwin'])('formats the effective macOS driver platform %s', async driverPlatform => {
  getComputerUseStatus.mockResolvedValue(status({ platform: 'darwin', is_wsl: false, driver_platform: driverPlatform }))
  render(<ComputerUsePanel />)
  expect(await screen.findByText('Effective driver: macOS')).toBeTruthy()
})
'''
p.write_text(s, encoding='utf-8')
p = root / 'apps/desktop/src/app/settings/toolset-config-panel.test.tsx'
s = p.read_text(encoding='utf-8') + '''

it('discards an older provider response after a same-scope target refresh', async () => {
  let resolveOld!: (value: ToolsetConfig) => void
  const old = new Promise<ToolsetConfig>(resolve => { resolveOld = resolve })
  const ready = config({ name: 'computer_use', providers: [{
    name: 'cua-driver', badge: 'local', tag: 'Desktop control', env_vars: [],
    post_setup: 'cua_driver', requires_nous_auth: false, is_active: true, status: 'ready'
  }] })
  const missing = { ...ready, providers: ready.providers.map(provider => ({ ...provider, status: 'needs_setup' as const })) }
  getToolsetConfig.mockReturnValueOnce(old).mockResolvedValueOnce(missing)

  const { rerender } = render(<ToolsetConfigPanel toolset="computer_use" refreshKey={0} />)
  await waitFor(() => expect(getToolsetConfig).toHaveBeenCalledTimes(1))
  // Keep the router/provider wrappers and component identity across rerenders.
  rerender(<MemoryRouter><QueryClientProvider client={new QueryClient()}>
    <ToolsetConfigPanel toolset="computer_use" refreshKey={1} />
  </QueryClientProvider></MemoryRouter>)
  expect(await screen.findByRole('button', { name: 'Run setup' })).toBeTruthy()
  await act(async () => resolveOld(ready))
  expect(getToolsetConfig).toHaveBeenCalledTimes(2)
  expect(screen.queryByText('Installed')).toBeNull()
  expect(screen.getByRole('button', { name: 'Run setup' })).toBeTruthy()
})
'''
s = s.replace('import { cleanup, fireEvent, render as rtlRender, screen, waitFor }', 'import { act, cleanup, fireEvent, render as rtlRender, screen, waitFor }')
p.write_text(s, encoding='utf-8')
