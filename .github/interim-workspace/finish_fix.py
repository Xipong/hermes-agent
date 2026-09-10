"""Apply the product fix and align the legacy assertion with response boundaries."""
from apply_fix import apply, replace_once, source

apply()
path, text = source('lib/chat-messages.test.ts', '0874c2a6c60347d42ca48b735cec6bec7f1f68b5')
old = '''  it('removes all text parts and appends the final text', () => {
    const parts = [
      { type: 'text' as const, text: 'streamed delta 1' },
      { type: 'text' as const, text: 'streamed delta 2' },
      { type: 'tool-call' as const, toolCallId: 'tc1', toolName: 'terminal', args: {} as never, argsText: '{}' }
    ]

    const result = mergeFinalAssistantText(parts, 'final answer')

    expect(result.filter(p => p.type === 'text')).toHaveLength(1)
    expect(result.filter(p => p.type === 'text')[0]).toMatchObject({ text: 'final answer' })
    expect(result.some(p => p.type === 'tool-call')).toBe(true)
  })'''
new = '''  it('preserves pre-tool text and appends the later final response', () => {
    // These deltas precede the tool call: they belong to an earlier model
    // response, not to the provisional draft of the final being settled.
    const parts = [
      { type: 'text' as const, text: 'streamed delta 1' },
      { type: 'text' as const, text: 'streamed delta 2' },
      { type: 'tool-call' as const, toolCallId: 'tc1', toolName: 'terminal', args: {} as never, argsText: '{}' }
    ]

    const result = mergeFinalAssistantText(parts, 'final answer')

    expect(result.filter(p => p.type === 'text').map(p => p.text)).toEqual([
      'streamed delta 1',
      'streamed delta 2',
      'final answer'
    ])
    expect(result.some(p => p.type === 'tool-call')).toBe(true)
  })'''
path.write_text(replace_once(text, old, new))
