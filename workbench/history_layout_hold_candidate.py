from pathlib import Path
import os
import subprocess

BASE = 'da7f4d0a35e73411a460af0c45434f2d979bceff'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
PREFIX = 'apps/desktop/src/components/assistant-ui/thread/'
changed = set()


def edit(name, old, new):
    path = Path(PREFIX + name)
    text = path.read_text()
    assert text.count(old) == 1, (name, old, text.count(old))
    path.write_text(text.replace(old, new, 1))
    changed.add(str(path))


helper = Path(PREFIX + 'history-scroll.ts')
helper.write_text(helper.read_text() + '''
/**
 * Runtime publication and descendant layout are separate commits. Keep the
 * chosen occurrence through later DOM/size changes, not an arbitrary number
 * of frames. The owner releases this hold on user navigation or scope change.
 * An idle historical page does no work: there is no polling/animation loop.
 */
export function holdHistoryScroll(
  viewport: HTMLElement,
  content: HTMLElement,
  anchors: readonly HistoryScrollAnchor[],
  beforeRestore: () => void
): () => void {
  let active = true
  let frame = 0

  const restore = () => {
    if (!active) {
      return
    }

    beforeRestore()
    restoreHistoryScroll(viewport, anchors)
  }

  const schedule = () => {
    if (active && !frame) {
      frame = requestAnimationFrame(() => {
        frame = 0
        restore()
      })
    }
  }

  const resize = new ResizeObserver(restore)
  const mutations = new MutationObserver(schedule)
  resize.observe(content)
  mutations.observe(content, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['data-message-id', 'data-history-anchor']
  })
  restore()
  schedule()

  return () => {
    active = false
    cancelAnimationFrame(frame)
    resize.disconnect()
    mutations.disconnect()
  }
}
''')
changed.add(str(helper))

edit('list.tsx',
     "import { captureHistoryScroll, type HistoryScrollAnchor, restoreHistoryScroll } from './history-scroll'",
     "import { captureHistoryScroll, type HistoryScrollAnchor, holdHistoryScroll } from './history-scroll'")
edit('list.tsx', '  const historyFrameRef = useRef(0)',
     '  const historyHoldRef = useRef<(() => void) | null>(null)')
edit('list.tsx', '''  const clearHistoryAnchor = useCallback(() => {
    cancelAnimationFrame(historyFrameRef.current)
    historyAnchorRef.current = []
  }, [])''', '''  const clearHistoryAnchor = useCallback(() => {
    historyHoldRef.current?.()
    historyHoldRef.current = null
    historyAnchorRef.current = []
  }, [])''')
edit('list.tsx', '''          stopScroll()
          historyAnchorRef.current = captureHistoryScroll(el)''', '''          stopScroll()
          clearHistoryAnchor()
          historyAnchorRef.current = captureHistoryScroll(el)''')
edit('list.tsx', '    [expandWindow, isHistorical, paneVisible, revealNewer, scrollRef, stopScroll]',
     '    [clearHistoryAnchor, expandWindow, isHistorical, paneVisible, revealNewer, scrollRef, stopScroll]')
old = '''    cancelAnimationFrame(historyFrameRef.current)
    restoreHistoryScroll(el, historyAnchorRef.current)
    // The external-store runtime can notify descendants after their parent.
    // Keep the anchor through that commit and the next layout frame.
    historyFrameRef.current = requestAnimationFrame(() => {
      restoreHistoryScroll(el, historyAnchorRef.current)
      historyFrameRef.current = requestAnimationFrame(() => {
        restoreHistoryScroll(el, historyAnchorRef.current)
        historyAnchorRef.current = []
      })
    })
  }, [currentMessages, expectedRuntimeIds, runtimeMessageIds, structuralSignature, weightSignature, scrollRef])'''
new = '''    const content = contentRef.current

    if (!content) {
      return
    }

    const release = holdHistoryScroll(el, content, historyAnchorRef.current, stopScroll)
    historyHoldRef.current = release

    return () => {
      release()

      if (historyHoldRef.current === release) {
        historyHoldRef.current = null
      }
    }
  }, [contentRef, currentMessages, expectedRuntimeIds, runtimeMessageIds, structuralSignature, weightSignature, scrollRef, stopScroll])'''
edit('list.tsx', old, new)
edit('list.tsx', '''        if (direction > 0 && isHistorical && newerAvailable && el.scrollHeight - el.clientHeight - el.scrollTop <= 48) {''', '''        clearHistoryAnchor()

        if (direction > 0 && isHistorical && newerAvailable && el.scrollHeight - el.clientHeight - el.scrollTop <= 48) {''')
edit('list.tsx', '''    [
      growHistoryWindow,
      hiddenCount,''', '''    [
      clearHistoryAnchor,
      growHistoryWindow,
      hiddenCount,''')

path = Path(PREFIX + 'history-layout-hold.test.ts')
assert not path.exists()
path.write_text('''import { afterEach, describe, expect, it, vi } from 'vitest'

import { holdHistoryScroll } from './history-scroll'

const rect = (top: number, height: number): DOMRect =>
  ({ top, bottom: top + height, height, width: 800 } as DOMRect)

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('history layout hold', () => {
  it.each(['resize', 'mutation'] as const)('keeps the anchor through a late %s and releases all pending work', cause => {
    const viewport = window.document.createElement('div')
    const content = window.document.createElement('div')
    const part = window.document.createElement('div')
    part.dataset.historyAnchor = 'text-99'
    content.append(part)
    viewport.append(content)
    viewport.scrollTop = 900
    let displacement = 0
    vi.spyOn(viewport, 'getBoundingClientRect').mockReturnValue(rect(0, 600))
    vi.spyOn(part, 'getBoundingClientRect').mockImplementation(() => rect(1000 + displacement - viewport.scrollTop, 100))

    let resize!: ResizeObserverCallback
    let mutation!: MutationCallback
    const resizeDisconnect = vi.fn()
    const mutationDisconnect = vi.fn()
    vi.stubGlobal('ResizeObserver', class {
      constructor(callback: ResizeObserverCallback) { resize = callback }
      observe() {}
      disconnect = resizeDisconnect
    })
    vi.stubGlobal('MutationObserver', class {
      constructor(callback: MutationCallback) { mutation = callback }
      observe() {}
      disconnect = mutationDisconnect
    })

    let serial = 0
    const frames = new Map<number, FrameRequestCallback>()
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
      frames.set(++serial, callback)

      return serial
    })
    vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id))

    const tick = () => {
      const callbacks = [...frames.values()]
      frames.clear()
      callbacks.forEach(callback => callback(0))
    }

    const stop = vi.fn()
    const release = holdHistoryScroll(viewport, content, [{ key: 'text-99', occurrence: 0, offset: 100 }], stop)
    tick()
    const stopped = stop.mock.calls.length

    // No busy animation loop, even though the hold survives many idle frames.
    for (let frame = 0; frame < 20; frame++) {
      tick()
    }

    expect(stop).toHaveBeenCalledTimes(stopped)
    displacement = -800

    if (cause === 'resize') {
      resize([], {} as ResizeObserver)
    } else {
      mutation([], {} as MutationObserver)
      mutation([], {} as MutationObserver)
      expect(frames.size).toBe(1)
      tick()
    }

    expect(part.getBoundingClientRect().top).toBe(100)
    expect(viewport.scrollTop).toBe(100)
    mutation([], {} as MutationObserver)
    expect(frames.size).toBe(1)
    release()
    expect(frames.size).toBe(0)
    expect(resizeDisconnect).toHaveBeenCalledOnce()
    expect(mutationDisconnect).toHaveBeenCalledOnce()
    displacement = 400
    resize([], {} as ResizeObserver)
    mutation([], {} as MutationObserver)
    tick()
    expect(viewport.scrollTop).toBe(100)
  })
})
''')
changed.add(str(path))
assert set(subprocess.check_output(['git', 'status', '--porcelain'], text=True).splitlines())
subprocess.run(['git', 'diff', '--check'], check=True)
subprocess.run(['git', 'add', *sorted(changed)], check=True)
subprocess.run(['git', '-c', 'user.name=Xipong', '-c', 'user.email=217837358+Xipong@users.noreply.github.com', 'commit', '-m', 'fix(desktop): hold historical anchors through deferred descendant layout'], check=True)
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
dest = 'refs/heads/verify/history-layout-hold-125766'
subprocess.run(['git', 'push', '--force-with-lease=' + dest + ':', 'origin', 'HEAD:' + dest], check=True)
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write('sha=' + sha + '\n')
print('CANDIDATE_SHA=' + sha)
