def revise(root):
    def change(name, old, new):
        path = root / name
        text = path.read_text()
        assert old in text, (name, old)
        path.write_text(text.replace(old, new, 1))

    change('apps/desktop/src/components/assistant-ui/thread/history-scroll.test.ts',
           "import { afterEach, describe, expect, it, vi } from 'vitest'",
           "import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'")
    change('apps/desktop/src/components/assistant-ui/thread/history-scroll.test.ts',
           "afterEach(() =>",
           "beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false })) })\n\nafterEach(() =>")
    change('apps/desktop/src/components/assistant-ui/thread/list-session-scroll.test.tsx',
           "expect(getByRole('button', { name: 'Show later messages' })).toBeDisabled()",
           "expect((getByRole('button', { name: 'Show later messages' }) as HTMLButtonElement).disabled).toBe(true)")
    change('apps/desktop/src/app/chat/history-window.test.tsx',
           '    expect(await mounted.window.expandWindow()).toBe(false)',
           '    await act(async () => { expect(await mounted.window.expandWindow()).toBe(false) })')
    change('apps/desktop/e2e/history-navigation.spec.ts',
           "    await page.getByRole('button', { name: 'Jump to latest', exact: true }).click()",
           """    // Return through adjacent pages, not by jumping to another prompt or live.
    for (let pageNumber = 0; pageNumber < 2; pageNumber += 1) {
      const before = await viewport.textContent()
      await viewport.getByRole('button', { name: 'Show earlier messages' }).click()
      await expect.poll(() => viewport.textContent()).not.toBe(before)
      expect(await viewport.locator('[data-message-id]').count()).toBeLessThanOrEqual(360)
    }
    await expect(viewport).toContainText('NAV prompt 00')
    await expect(viewport.getByRole('button', { name: 'Show earlier messages' })).toHaveCount(0)
    await expect(later).toBeVisible()
    await page.getByRole('button', { name: 'Jump to latest', exact: true }).click()""")
