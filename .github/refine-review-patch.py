from pathlib import Path
import sys


def swap(path, old, new):
    p=Path(path); s=p.read_text(); n=s.count(old)
    if n!=1: raise RuntimeError((path,n,old[:100]))
    p.write_text(s.replace(old,new,1))

p='apps/desktop/src/app/session/hooks/use-message-stream/review-summary-durability.test.tsx'
swap(p, 'const refresh = (rows: SessionMessage[], previous: ReturnType<typeof toChatMessages>) =>\n  preserveLocalAssistantErrors(graftRefreshedTailOntoBackfill(toChatMessages(rows), previous), previous)',
     'const refresh = (rows: SessionMessage[], previous: ReturnType<typeof toChatMessages>, beforeRead = previous) =>\n  preserveLocalAssistantErrors(graftRefreshedTailOntoBackfill(toChatMessages(rows), previous), previous, beforeRead)')
swap(p,'const stale = refresh(base, previous)', 'const stale = refresh(base, previous, toChatMessages(base))')
swap(p, '// An authoritative empty/reset transcript must not resurrect old receipts.',
     '// An authoritative rewind started after delivery must not resurrect its removed receipt.\n    expect(refresh(base, current).filter(message => message.role === \'system\')).toHaveLength(0)\n    // An authoritative empty/reset transcript must not resurrect old receipts.')

if '--apply' not in sys.argv:
    raise SystemExit(0)
p='apps/desktop/src/lib/chat-messages/review-summary.ts'
swap(p, 'export function preserveNewerReviewSummaries(next: ChatMessage[], previous: ChatMessage[]): ChatMessage[] {',
     'export function preserveNewerReviewSummaries(next: ChatMessage[], previous: ChatMessage[], beforeRead: ChatMessage[]): ChatMessage[] {')
swap(p, '  const ids = new Set(next.map(message => message.id))',
     '  const ids = new Set([...next, ...beforeRead].map(message => message.id))')
swap(p, ' * Only carry proven newer durable rows. Empty/reset history and older omitted rows',
     ' * Only carry durable rows received DURING this read. Empty/reset history and earlier rows')
p='apps/desktop/src/lib/chat-messages/reconciliation.ts'
swap(p,'  currentMessages: ChatMessage[]\n): ChatMessage[] {\n  nextMessages = preserveNewerReviewSummaries(nextMessages, currentMessages)',
     '  currentMessages: ChatMessage[],\n  reviewSnapshot?: ChatMessage[]\n): ChatMessage[] {\n  if (reviewSnapshot) {\n    nextMessages = preserveNewerReviewSummaries(nextMessages, currentMessages, reviewSnapshot)\n  }')
p='apps/desktop/src/app/contrib/wiring.tsx'
swap(p,'          const latest = await getLatestSessionMessages(storedSessionId, storedProfile)',
     '          const messagesBeforeRead = sessionStateByRuntimeIdRef.current.get(runtimeSessionId)?.messages ?? []\n          const latest = await getLatestSessionMessages(storedSessionId, storedProfile)')
swap(p, '                graftRefreshedTailOntoBackfill(messages, state.messages),\n                state.messages\n',
     '                graftRefreshedTailOntoBackfill(messages, state.messages),\n                state.messages,\n                messagesBeforeRead\n')
p='apps/desktop/src/app/contrib/hooks/use-background-sync.ts'
swap(p, '      const latest = await getLatestSessionMessages(storedSessionId, profileScope, { passive: true })',
     '      const messagesBeforeRead = $sessionStates.get()[runtimeSessionId]?.messages ?? []\n      const latest = await getLatestSessionMessages(storedSessionId, profileScope, { passive: true })')
swap(p, '            graftRefreshedTailOntoBackfill(messages, state.messages),\n            state.messages\n',
     '            graftRefreshedTailOntoBackfill(messages, state.messages),\n            state.messages,\n            messagesBeforeRead\n')
swap(p, '    const latest = await getLatestSessionMessages(storedSessionId, profileScope)',
     '    const messagesBeforeRead = $sessionStates.get()[runtimeSessionId]?.messages ?? []\n    const latest = await getLatestSessionMessages(storedSessionId, profileScope)')
swap(p, '        messages: preserveLocalAssistantErrors(graftRefreshedTailOntoBackfill(messages, state.messages), state.messages)',
     '        messages: preserveLocalAssistantErrors(graftRefreshedTailOntoBackfill(messages, state.messages), state.messages, messagesBeforeRead)')
