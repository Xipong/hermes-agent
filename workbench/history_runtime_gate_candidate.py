"""Apply exact reviewed edits to a pinned candidate; create a new branch only."""
from pathlib import Path
import os
import subprocess

BASE = 'e7176142b0da4c31ab7b5583bd18fcbc66a47038'
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == BASE
PREFIX = 'apps/desktop/src/components/assistant-ui/thread/'
CHANGED = set()


def edit(path, old, new, count=1):
    target = Path(path)
    text = target.read_text()
    assert text.count(old) == count, (path, old, text.count(old))
    target.write_text(text.replace(old, new, count))
    CHANGED.add(path)


edit(PREFIX + 'transcript-window.tsx',
     '  currentMessages?: readonly ChatMessage[]',
     '''  currentMessages?: readonly ChatMessage[]
  /** Canonical visible runtime branch expected after this history page commits. */
  expectedRuntimeIds?: string | null''')
edit(PREFIX + 'transcript-window.tsx',
     '  currentMessages: []',
     '  currentMessages: [],\n  expectedRuntimeIds: null')

boundary = 'apps/desktop/src/app/chat/index.tsx'
edit(boundary, '  const isHistorical = Boolean(history.page)', '''  const isHistorical = Boolean(history.page)

  // Source rows can coalesce or form hidden/sibling branches. Follow the
  // canonical repository's visible chain rather than comparing raw source IDs.
  const expectedRuntimeIds = useMemo(() => {
    if (!isHistorical) {
      return null
    }

    const parents = new Map(runtimeMessageRepository.messages.map(item => [item.message.id, item.parentId]))
    const ids: string[] = []
    let id = runtimeMessageRepository.headId

    while (id) {
      ids.push(id)
      id = parents.get(id) ?? null
    }

    return ids.reverse().join('\\n')
  }, [isHistorical, runtimeMessageRepository])
''')
edit(boundary, '      currentMessages,\n      isHistorical,',
     '      currentMessages,\n      expectedRuntimeIds,\n      isHistorical,', count=2)

listing = PREFIX + 'list.tsx'
edit(listing, '    currentMessages,\n    historyError',
     '    currentMessages,\n    expectedRuntimeIds,\n    historyError')
edit(listing, '  const historyAnchorRef = useRef<HistoryScrollAnchor[]>([])', '''  const runtimeMessageIds = useAuiState(s =>
    isHistorical ? s.thread.messages.map(message => message.id).join('\\n') : ''
  )

  const historyAnchorRef = useRef<HistoryScrollAnchor[]>([])''')
edit(listing, '    if (!el || !historyAnchorRef.current.length) {', '''    // Context selects the source before the external-store runtime publishes
    // its rows. Spending the two-frame restore on that old DOM loses the
    // reading anchor before an eviction actually commits.
    if (
      !el ||
      !historyAnchorRef.current.length ||
      (expectedRuntimeIds !== null && runtimeMessageIds !== expectedRuntimeIds)
    ) {''')
edit(listing, '  }, [currentMessages, structuralSignature, weightSignature, scrollRef])',
     '  }, [currentMessages, expectedRuntimeIds, runtimeMessageIds, structuralSignature, weightSignature, scrollRef])')

tests = 'apps/desktop/src/app/chat/history-window.test.tsx'
edit(tests, '    expect(mounted.runtime.thread.getState().messages).toHaveLength(120)', '''    expect(mounted.runtime.thread.getState().messages).toHaveLength(120)
    expect(mounted.window.expectedRuntimeIds).toBe(
      mounted.runtime.thread.getState().messages.map(message => message.id).join('\\n')
    )''')
edit(tests, '      // Raw retention is three pages even though hundreds of rows hydrate into', '''      expect(mounted.window.expectedRuntimeIds).toBe(
        mounted.runtime.thread.getState().messages.map(message => message.id).join('\\n')
      )

      // Raw retention is three pages even though hundreds of rows hydrate into''')

changed = set(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines())
assert changed == CHANGED and len(CHANGED) == 4, changed
subprocess.run(['git', 'diff', '--check'], check=True)
subprocess.run(['git', 'add', *sorted(CHANGED)], check=True)
subprocess.run(['git', '-c', 'user.name=Xipong', '-c', 'user.email=217837358+Xipong@users.noreply.github.com',
                'commit', '-m', 'fix(desktop): retain history anchors until canonical runtime publication'], check=True)
sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
dest = 'refs/heads/verify/history-runtime-gate-125766'
subprocess.run(['git', 'push', '--force-with-lease=' + dest + ':', 'origin', 'HEAD:' + dest], check=True)
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write('sha=' + sha + '\n')
print('CANDIDATE_SHA=' + sha)
