"""Reviewed, pinned-source Desktop interim fix. Used only in the fork validation job."""
from pathlib import Path
import hashlib

ROOT = Path('apps/desktop/src')


def source(relative, expected):
    path = ROOT / relative
    raw = path.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    assert blob == expected, (path, blob, expected)
    return path, raw.decode()


def replace_once(text, old, new):
    assert text.count(old) == 1, (old[:120], text.count(old))
    return text.replace(old, new, 1)


def apply():
    path, text = source('lib/chat-messages/hydration.ts', 'df3b765df39628fe2b99ba60ae1f2ce03eac679c')
    start = text.index('/**\n * Reply text from a Responses-API')
    end = text.index('function displayContentForMessage', start)
    text = text[:start] + '''/**
 * Responses message items retain their channel in stored history. Commentary
 * is public assistant text, not analysis; restore it even when the same row
 * has a canonical final answer. Final items remain a content fallback only.
 */
function codexMessageItemText(message: SessionMessage): { commentary: string[]; reply: string } {
  let items = message.codex_message_items
  const commentary: string[] = []
  const replies: string[] = []

  // REST carries SQLite JSON text; RPC history carries the decoded list.
  if (typeof items === 'string') {
    try {
      items = JSON.parse(items)
    } catch {
      return { commentary, reply: '' }
    }
  }

  if (!Array.isArray(items)) {
    return { commentary, reply: '' }
  }

  for (const item of items) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) {
      continue
    }

    const record = item as Record<string, unknown>

    if (record.type !== 'message' || record.role !== 'assistant') {
      continue
    }

    const phase = typeof record.phase === 'string' ? record.phase.trim().toLowerCase() : ''

    if (phase === 'analysis' || !Array.isArray(record.content)) {
      continue
    }

    const chunks: string[] = []

    for (const part of record.content) {
      if (!part || typeof part !== 'object' || Array.isArray(part)) {
        continue
      }

      const partRecord = part as Record<string, unknown>

      if (
        (partRecord.type === 'output_text' || partRecord.type === 'text') &&
        typeof partRecord.text === 'string'
      ) {
        chunks.push(partRecord.text)
      }
    }

    const text = chunks.join('')

    if (phase === 'commentary') {
      if (text.trim()) {
        commentary.push(text.trim())
      }
    } else {
      replies.push(text)
    }
  }

  return { commentary, reply: replies.join('') }
}

''' + text[end:]
    old = '''    if (displayContent) {
      parts.push(
        displayRole === 'assistant'
          ? assistantTextPart(displayContent, message.timestamp)
          : textPart(displayContent, message.timestamp)
      )
    }

    // Reply text can live only in the sidecar alongside reasoning or tool parts.
    // Those parts are not a substitute for the answer; canonical content still wins.
    if (message.role === 'assistant' && message.display_kind !== 'hidden' && !displayContent) {
      const codexText = codexMessageItemText(message)

      if (codexText) {
        parts.push(assistantTextPart(codexText, message.timestamp))
      }
    }
'''
    new = '''    const codexText =
      displayRole === 'assistant' && message.display_kind !== 'hidden' ? codexMessageItemText(message) : null
    const reply = displayContent || codexText?.reply
    // Some providers also persist the joined commentary as canonical content.
    // Keep that authoritative copy once, without treating unrelated final text
    // as a reason to discard the earlier public messages.
    const normalized = (value: string) => renderMediaTags(value).replace(/\\s+/g, ' ').trim()
    const commentaryIsReply = Boolean(
      reply && codexText?.commentary.length && normalized(codexText.commentary.join('\\n\\n')) === normalized(reply)
    )

    if (codexText && !commentaryIsReply) {
      parts.push(...codexText.commentary.map(text => assistantTextPart(text, message.timestamp)))
    }

    if (reply) {
      parts.push(
        displayRole === 'assistant'
          ? assistantTextPart(reply, message.timestamp)
          : textPart(reply, message.timestamp)
      )
    }
'''
    text = replace_once(text, old, new)
    text = replace_once(text,
        "import { assistantTextPart, chatMessageText, dedupeRepeatedTextInParts, reasoningPart, textPart } from './parts'",
        "import { assistantTextPart, chatMessageText, dedupeRepeatedTextInParts, reasoningPart, renderMediaTags, textPart } from './parts'")
    path.write_text(text)

    path, text = source('lib/chat-messages/parts.ts', '997b61a797a9a19527b0253db7abb3fbfcf32360')
    text = replace_once(text,
        ''' * - Removes all existing `text` parts (they were streamed deltas, now superseded
 *   by the authoritative final response).''',
        ''' * - Preserves earlier tool-delimited responses: a missed interim frame must
 *   not make their public text disposable.
 * - Replaces provisional text only in the latest response with its authoritative
 *   final text, retaining confirmed text/reasoning boundaries.''')
    text = replace_once(text,
        "  const previousText = parts.findLast(part => part.type === 'text')\n",
        '''  // A tool call is an explicit model-response boundary even when no
  // message.interim frame sealed the earlier text into a separate bubble.
  // Only the suffix after the last call belongs to this authoritative final.
  const lastToolIndex = parts.findLastIndex(part => part.type === 'tool-call')

  if (lastToolIndex >= 0) {
    const earlier = parts.slice(0, lastToolIndex + 1)
    const earlierText = earlier
      .filter((part): part is Extract<ChatMessagePart, { type: 'text' }> => part.type === 'text')
      .map(part => part.text)
      .join('')
    // Some terminal frames carry cumulative text. Strip only an exact prefix;
    // fuzzy similarity is not proof that two assistant messages are the same.
    const responseText = earlierText && finalText.startsWith(earlierText) ? finalText.slice(earlierText.length) : finalText

    return [...earlier, ...mergeFinalAssistantText(parts.slice(lastToolIndex + 1), responseText, fallbackTimestamp)]
  }

  const previousText = parts.findLast(part => part.type === 'text')
''')
    text = replace_once(text,
        '''      // Sealed text parts were already finalized into their own bubbles —
      // this filter only runs on the LAST streaming bubble, so there are no
      // sealed parts here. All text parts are streamed deltas that get
      // replaced by the authoritative final text.''',
        '''      // The tool-delimited prefix was retained above. This suffix is
      // provisional text from the response being finalized.''')
    path.write_text(text)

    path, text = source('lib/chat-messages.codex-sidecar-hydration.test.ts', 'cd6122d47029a93dcabb4098ba1d9e5e0446479b')
    text = replace_once(text,
        '// ...and commentary / analysis narration (reasoning channel on the backend) is not.',
        '// ...and public commentary survives too, without promoting analysis.')
    text = replace_once(text,
        "expect(chatMessageText(messages[1])).not.toContain('Working through the approach...')",
        "expect(chatMessageText(messages[1])).toContain('Working through the approach...')")
    path.write_text(text)

    path, text = source('lib/chat-messages.codex-json-sidecar.test.ts', '984d193be120a298e92f263ef0df3b7ff6729826')
    old = '''  for (const phase of ['analysis', 'commentary']) {
    expect(toChatMessages([{ ...empty, codex_message_items: JSON.stringify([{ ...items[0], phase }]) }])).toEqual([])
  }
'''
    new = '''  expect(
    toChatMessages([{ ...empty, codex_message_items: JSON.stringify([{ ...items[0], phase: 'analysis' }]) }])
  ).toEqual([])
  expect(
    chatMessageText(
      toChatMessages([{ ...empty, codex_message_items: JSON.stringify([{ ...items[0], phase: 'commentary' }]) }])[0]
    )
  ).toBe('Durable reply')
'''
    path.write_text(replace_once(text, old, new))


if __name__ == '__main__':
    apply()
