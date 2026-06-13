/**
 * M5 — unit + integration tests for the H5 SSE stream consumer.
 *
 * Coverage map (vs M5 acceptance gate):
 *   - happy path        → session_started → 3× message_delta → message_complete
 *   - half-packet       → event split across two TCP-style chunks
 *   - sticky packet     → multiple events in one chunk
 *   - Unicode / CJK     → UTF-8 multi-byte boundary handling
 *   - AbortSignal       → fetch passes signal, consumer aborts cleanly
 *   - 4 error codes     → DIFY_AUTH / DIFY_BAD_REQUEST / DIFY_UPSTREAM / DIFY_UNKNOWN
 *   - HTTP 4xx          → DifyStreamError code=BAD_HTTP
 *   - network failure   → DifyStreamError code=NETWORK
 *   - parseFields       → field parsing edge cases (comments, missing colon, multi-line data)
 *   - parseEvent        → unknown event name skipped; unknown error code coerced to DIFY_UNKNOWN
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

import {
  DifyStreamError,
  abortStatePatch,
  createThinkStripper,
  parseEvent,
  parseFields,
  streamChat,
  stripThinkTags,
  type AbortStatePatch,
  type DifyStreamEvent,
} from '../difyStream'

const encoder = new TextEncoder()

function streamResponse(chunks: string[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
  return new Response(body, {
    status,
    headers: { 'content-type': 'text/event-stream' },
  })
}

function installFetchMock(response: Response | Error | (() => Response | Error)) {
  const fn = vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    const r = typeof response === 'function' ? response() : response
    if (r instanceof Error) throw r
    return r
  })
  globalThis.fetch = fn as unknown as typeof fetch
  return fn
}

async function collectEvents(
  gen: AsyncGenerator<DifyStreamEvent, void, void>,
): Promise<DifyStreamEvent[]> {
  const out: DifyStreamEvent[] = []
  for await (const ev of gen) out.push(ev)
  return out
}

describe('parseFields', () => {
  it('extracts event and data lines', () => {
    const raw = 'event: message_delta\ndata: {"text":"hi"}'
    expect(parseFields(raw)).toEqual({ event: 'message_delta', data: '{"text":"hi"}' })
  })

  it('ignores SSE comments and blank lines', () => {
    const raw = ': keepalive\nevent: ping\n\n: another'
    expect(parseFields(raw)).toEqual({ event: 'ping' })
  })

  it('joins multi-line data fields with newline', () => {
    const raw = 'event: foo\ndata: line1\ndata: line2'
    expect(parseFields(raw)).toEqual({ event: 'foo', data: 'line1\nline2' })
  })

  it('treats missing colon as event name fallback', () => {
    const raw = 'bareword'
    expect(parseFields(raw)).toEqual({ event: 'bareword' })
  })

  it('handles CRLF line endings', () => {
    const raw = 'event: end\r\ndata: {}\r\n'
    expect(parseFields(raw)).toEqual({ event: 'end', data: '{}' })
  })
})

describe('parseEvent', () => {
  it('parses session_started', () => {
    expect(parseEvent('event: session_started\ndata: {"session_id":"abc","started_at":null}'))
      .toEqual({ type: 'session_started', session_id: 'abc', started_at: null })
  })

  it('parses message_delta', () => {
    expect(parseEvent('event: message_delta\ndata: {"text":"hi"}'))
      .toEqual({ type: 'message_delta', text: 'hi' })
  })

  it('parses message_complete with numeric fields', () => {
    expect(parseEvent('event: message_complete\ndata: {"text":"done","total_tokens":42,"elapsed_time":1.5}'))
      .toEqual({ type: 'message_complete', text: 'done', total_tokens: 42, elapsed_time: 1.5 })
  })

  // M6.1 — null is preserved (distinct from empty string), so UI can show
  // "no reply" vs "empty reply" differently.
  it('preserves text: null on message_complete (M6.1 contract)', () => {
    expect(parseEvent('event: message_complete\ndata: {"text":null,"total_tokens":0,"elapsed_time":0.1}'))
      .toEqual({ type: 'message_complete', text: null, total_tokens: 0, elapsed_time: 0.1 })
  })

  it('preserves empty-string text on message_complete (distinct from null)', () => {
    expect(parseEvent('event: message_complete\ndata: {"text":"","total_tokens":0,"elapsed_time":0.1}'))
      .toEqual({ type: 'message_complete', text: '', total_tokens: 0, elapsed_time: 0.1 })
  })

  it('coerces missing text field on message_complete to empty string', () => {
    // Per M6.1 contract: only JSON `null` maps to null. Missing field falls back
    // to '' — backend omitting the field is indistinguishable from "empty reply".
    expect(parseEvent('event: message_complete\ndata: {"total_tokens":0,"elapsed_time":0.1}'))
      .toEqual({ type: 'message_complete', text: '', total_tokens: 0, elapsed_time: 0.1 })
  })

  it('parses end marker', () => {
    expect(parseEvent('event: end\ndata: {}')).toEqual({ type: 'end' })
  })

  it('parses each of the 4 error codes', () => {
    const codes = ['DIFY_AUTH', 'DIFY_BAD_REQUEST', 'DIFY_UPSTREAM', 'DIFY_UNKNOWN'] as const
    for (const code of codes) {
      const ev = parseEvent(`event: error\ndata: {"code":"${code}","message":"x"}`)
      expect(ev).toEqual({ type: 'error', code, message: 'x' })
    }
  })

  it('coerces unknown error code to DIFY_UNKNOWN', () => {
    expect(parseEvent('event: error\ndata: {"code":"WHAT","message":"x"}'))
      .toEqual({ type: 'error', code: 'DIFY_UNKNOWN', message: 'x' })
  })

  it('returns null for unknown event name', () => {
    expect(parseEvent('event: mystery\ndata: {}')).toBeNull()
  })

  it('returns null for malformed JSON in data', () => {
    expect(parseEvent('event: message_delta\ndata: {not json')).toBeNull()
  })

  it('returns null when event/data missing', () => {
    expect(parseEvent('')).toBeNull()
    expect(parseEvent('event: foo')).toBeNull()
  })
})

describe('streamChat — happy path', () => {
  beforeEach(() => {
    installFetchMock(
      streamResponse([
        'event: session_started\ndata: {"session_id":"s1","started_at":null}\n\n',
        'event: message_delta\ndata: {"text":"你"}\n\n',
        'event: message_delta\ndata: {"text":"好"}\n\n',
        'event: message_complete\ndata: {"text":"你好","total_tokens":7,"elapsed_time":0.42}\n\n',
      ]),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('emits 4 events in order', async () => {
    const events = await collectEvents(streamChat({ text: 'hi' }))
    expect(events.map((e) => e.type)).toEqual([
      'session_started',
      'message_delta',
      'message_delta',
      'message_complete',
    ])
  })

  it('concatenates delta text correctly (UTF-8 CJK)', async () => {
    const events = await collectEvents(streamChat({ text: 'hi' }))
    const text = events
      .filter((e) => e.type === 'message_delta')
      .map((e) => (e as { text: string }).text)
      .join('')
    expect(text).toBe('你好')
  })
})

describe('streamChat — buffering', () => {
  afterEach(() => vi.restoreAllMocks())

  it('handles half-packet: event split mid-block across chunks', async () => {
    installFetchMock(
      streamResponse([
        'event: message_delta\ndata: {"te',
        'xt":"split"}\n\nevent: message_complete\ndata: {"text":"split","total_tokens":1,"elapsed_time":0.1}\n\n',
      ]),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events).toEqual([
      { type: 'message_delta', text: 'split' },
      { type: 'message_complete', text: 'split', total_tokens: 1, elapsed_time: 0.1 },
    ])
  })

  it('handles sticky packet: multiple events in one chunk', async () => {
    installFetchMock(
      streamResponse([
        'event: session_started\ndata: {"session_id":"s","started_at":null}\n\nevent: message_delta\ndata: {"text":"a"}\n\nevent: message_delta\ndata: {"text":"b"}\n\n',
      ]),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events.map((e) => e.type)).toEqual([
      'session_started',
      'message_delta',
      'message_delta',
    ])
  })

  it('flushes trailing event without \\n\\n terminator at EOF', async () => {
    installFetchMock(
      streamResponse(['event: end\ndata: {}']),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events).toEqual([{ type: 'end' }])
  })
})

describe('streamChat — abort + errors', () => {
  afterEach(() => vi.restoreAllMocks())

  it('passes AbortSignal to fetch and re-throws AbortError when aborted', async () => {
    const ctrl = new AbortController()
    const fn = installFetchMock(
      streamResponse([
        'event: session_started\ndata: {"session_id":"s","started_at":null}\n\n',
      ]),
    )
    ctrl.abort()
    await expect(async () => {
      for await (const ev of streamChat({ text: 'x', signal: ctrl.signal })) {
        void ev
        // should not enter
      }
    }).rejects.toMatchObject({ name: 'AbortError' })
    expect(fn).toHaveBeenCalledOnce()
    const call = fn.mock.calls[0]?.[1] as RequestInit | undefined
    expect(call?.signal).toBe(ctrl.signal)
  })

  it('surfaces server error events (DIFY_AUTH)', async () => {
    installFetchMock(
      streamResponse([
        'event: error\ndata: {"code":"DIFY_AUTH","message":"bad key"}\n\n',
        'event: end\ndata: {}\n\n',
      ]),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events).toEqual([
      { type: 'error', code: 'DIFY_AUTH', message: 'bad key' },
      { type: 'end' },
    ])
  })

  it('yields DIFY_BAD_REQUEST error events', async () => {
    installFetchMock(
      streamResponse([
        'event: error\ndata: {"code":"DIFY_BAD_REQUEST","message":"missing input_text"}\n\n',
      ]),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events[0]).toEqual({
      type: 'error',
      code: 'DIFY_BAD_REQUEST',
      message: 'missing input_text',
    })
  })

  it('yields DIFY_UPSTREAM error events', async () => {
    installFetchMock(
      streamResponse([
        'event: error\ndata: {"code":"DIFY_UPSTREAM","message":"0 events"}\n\n',
      ]),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events[0]).toMatchObject({ type: 'error', code: 'DIFY_UPSTREAM' })
  })

  it('yields DIFY_UNKNOWN error events', async () => {
    installFetchMock(
      streamResponse([
        'event: error\ndata: {"code":"DIFY_UNKNOWN","message":"oops"}\n\n',
      ]),
    )
    const events = await collectEvents(streamChat({ text: 'x' }))
    expect(events[0]).toMatchObject({ type: 'error', code: 'DIFY_UNKNOWN' })
  })

  it('throws DifyStreamError BAD_HTTP on 4xx', async () => {
    installFetchMock(streamResponse([], 422))
    await expect(async () => {
      for await (const ev of streamChat({ text: 'x' })) {
        void ev
        // drain
      }
    }).rejects.toMatchObject({
      name: 'DifyStreamError',
      code: 'BAD_HTTP',
      status: 422,
    })
  })

  it('throws DifyStreamError NETWORK when fetch itself rejects', async () => {
    installFetchMock(new TypeError('Failed to fetch'))
    await expect(async () => {
      for await (const ev of streamChat({ text: 'x' })) {
        void ev
        // drain
      }
    }).rejects.toBeInstanceOf(DifyStreamError)
    await expect(async () => {
      for await (const ev of streamChat({ text: 'x' })) {
        void ev
        // drain
      }
    }).rejects.toMatchObject({ code: 'NETWORK' })
  })

  it('posts JSON body with text and file_ids to /api/chat/stream', async () => {
    const fn = installFetchMock(
      streamResponse(['event: end\ndata: {}']),
    )
    await collectEvents(
      streamChat({
        text: 'hello',
        file_ids: ['f-1', 'f-2'],
        language: '普通话',
        end_user: 'u-1',
      }),
    )
    expect(fn).toHaveBeenCalledOnce()
    const [url, init] = fn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/chat/stream')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      text: 'hello',
      file_ids: ['f-1', 'f-2'],
      language: '普通话',
      end_user: 'u-1',
    })
  })
})

// ============== M8.2 — stripThinkTags helper ==============

describe('stripThinkTags', () => {
  it('removes a single inline <think> block', () => {
    expect(stripThinkTags('hello<think>internal</think> world')).toBe('hello world')
  })

  it('removes multi-line <think> spanning newlines (lazy [\\s\\S]*?)', () => {
    const input = 'before\n<think>line1\nline2\nline3</think>\nafter'
    expect(stripThinkTags(input)).toBe('before\n\nafter')
  })

  it('removes multiple <think> blocks in one string (g flag)', () => {
    const input = 'a<think>x</think>b<think>y</think>c'
    expect(stripThinkTags(input)).toBe('abc')
  })

  it('is non-greedy — stops at first </think> (no over-strip)', () => {
    // Lazy regex must match minimally; greedy would eat everything to last </think>
    const input = '<think>first</think>KEEP_ME<think>second</think>'
    expect(stripThinkTags(input)).toBe('KEEP_ME')
  })

  it('passes through text with no <think> blocks unchanged', () => {
    expect(stripThinkTags('plain text 中文 🎉')).toBe('plain text 中文 🎉')
  })

  it('handles empty string', () => {
    expect(stripThinkTags('')).toBe('')
  })

  it('tolerates uppercase/mixed-case <THINK> / <Think> (i flag)', () => {
    expect(stripThinkTags('a<THINK>X</THINK>b')).toBe('ab')
    expect(stripThinkTags('a<Think>X</Think>b')).toBe('ab')
  })
})

// ============== M8.1 — abortStatePatch helper ==============

describe('abortStatePatch', () => {
  it('returns noResponse=true for empty string (no text_chunk arrived)', () => {
    const patch: AbortStatePatch = abortStatePatch('')
    expect(patch).toEqual({ stopped: false, noResponse: true })
  })

  it('returns noResponse=true for null (bubble never populated)', () => {
    const patch: AbortStatePatch = abortStatePatch(null)
    expect(patch).toEqual({ stopped: false, noResponse: true })
  })

  it('returns noResponse=true for undefined (defensive, missing field)', () => {
    const patch: AbortStatePatch = abortStatePatch(undefined)
    expect(patch).toEqual({ stopped: false, noResponse: true })
  })

  it('returns stopped=true for partial text (mid-stream abort)', () => {
    const patch: AbortStatePatch = abortStatePatch('partial reply 你好')
    expect(patch).toEqual({ stopped: true, noResponse: false })
  })

  it('always sets BOTH fields (no leak from prior stopped state)', () => {
    // Regression: ensure noResponse path explicitly clears stopped,
    // so spreading the patch onto a message that had stopped:true from
    // a previous abort attempt resets it to false.
    const patch = abortStatePatch('')
    expect(patch.stopped).toBe(false)
    expect(patch.noResponse).toBe(true)

    const patch2 = abortStatePatch('x')
    expect(patch2.stopped).toBe(true)
    expect(patch2.noResponse).toBe(false)
  })
})

// ============== M9.1 — createThinkStripper stream-level buffer ==============

describe('createThinkStripper', () => {
  it('emits prefix before open tag and holds the think block itself', () => {
    // Arrange — chunk boundary at the start of <think>
    const s = createThinkStripper()

    // Act — first chunk crosses into think block
    const emitted = s.feed('hello<think>reasoning still in progress')

    // Assert — only the prefix before <think> reaches the bubble
    expect(emitted).toBe('hello')
  })

  it('emits everything after the close tag, swallowing the think body', () => {
    // Arrange — complete think block in one chunk
    const s = createThinkStripper()

    // Act
    const emitted = s.feed('a<think>secret reasoning</think>final answer')

    // Assert — only the surrounding text reaches the bubble
    expect(emitted).toBe('afinal answer')
  })

  it('releases nothing while waiting for </think> (chunk boundary inside think)', () => {
    // Arrange — feed enters think mode, hold all subsequent content
    const s = createThinkStripper()

    // Act — multiple chunks all inside the think block
    const e1 = s.feed('before<think>rea')
    const e2 = s.feed('soning ch')
    const e3 = s.feed('unk 1')

    // Assert — nothing emitted while inside think
    expect(e1).toBe('before')
    expect(e2).toBe('')
    expect(e3).toBe('')
  })

  it('emits everything after close once </think> arrives', () => {
    // Arrange — hold then release pattern
    const s = createThinkStripper()

    // Act — three chunks: hold mid-think, then emit post-think across two chunks
    const e1 = s.feed('prefix<think>reasoning')
    const e2 = s.feed('</think>post-')
    const e3 = s.feed('fix')

    // Assert
    expect(e1).toBe('prefix')
    expect(e2).toBe('post-')
    expect(e3).toBe('fix')
  })

  it('strips multiple adjacent think blocks in one stream', () => {
    // Arrange — three think blocks + intervening visible text (matches the
    // 3-block-per-response baseline measured in M9-PROMPT §1.5)
    const s = createThinkStripper()

    // Act — all in one chunk to keep the test focused on multi-block logic
    const emitted = s.feed(
      'intro<think>r1</think>mid<think>r2</think>end<think>r3</think>tail',
    )

    // Assert — only visible text crosses the boundary
    expect(emitted).toBe('intromidendtail')
  })

  it('drops unclosed think residue on flush (model anomaly)', () => {
    // Arrange — chunk enters think block but stream ends before close
    const s = createThinkStripper()

    // Act
    const e1 = s.feed('safe<think>orphaned reasoning that never closed')
    const residual = s.flush()

    // Assert — flush drops the unclosed think block, returns the safe prefix
    expect(e1).toBe('safe')
    expect(residual).toBe('')
  })

  it('flushes a trailing safe suffix (lookahead hold at end-of-stream)', () => {
    // Arrange — text that contains no <think> tag and no trailing `<`
    const s = createThinkStripper()

    // Act — feed text in two chunks, then flush
    const e1 = s.feed('plain visible ')
    const e2 = s.feed('reply')
    const residual = s.flush()

    // Assert — nothing pending after second feed; flush returns empty
    // (lookahead only kicks in when a trailing `<` could start a tag).
    expect(e1).toBe('plain visible ')
    expect(e2).toBe('reply')
    expect(residual).toBe('')
  })

  it('disambiguates a partial <thi prefix that does NOT form <think>', () => {
    // Arrange — chunk 1 holds `<thi` (4 chars, < 7-char lookahead window).
    // Chunk 2 starts with `ng>` so combined becomes `<thing>literal` — NOT
    // the think tag (after `<thi` we need `nk>`, but we get `ng>`). The
    // stripper must release the held prefix as literal text once it
    // sees the next chunk fails to complete the tag.
    const s = createThinkStripper()

    // Act
    const e1 = s.feed('abc<thi')
    const e2 = s.feed('ng>literal text')

    // Assert — e1 emits the safe prefix "abc"; e2 emits the held "<thi"
    // plus new chunk as literal text (combined "<thing>literal text").
    expect(e1).toBe('abc')
    expect(e2).toBe('<thing>literal text')
  })

  it('isolates buffer state between separate stripper instances', () => {
    // Arrange — two concurrent strippers must not share state
    const a = createThinkStripper()
    const b = createThinkStripper()

    // Act — feed different content into each
    const a1 = a.feed('AAA<think>secret')
    const b1 = b.feed('BBB safe')

    // Assert — each only sees its own buffer
    expect(a1).toBe('AAA')
    expect(b1).toBe('BBB safe')
  })
})

// ============== M9.1 — streamChat integration with ThinkStripper ==============

describe('streamChat M9.1 — think strip across SSE chunk boundaries', () => {
  it('never yields a message_delta containing <think> or </think> substring', async () => {
    // Arrange — simulate the real-Dify pattern from M9-PROMPT §1:
    // character-level tokens that cross chunk boundaries inside think tags.
    // Two think blocks + intervening visible text, all emitted across many deltas.
    const sseBody = [
      'event: session_started\ndata: {"session_id":"mock-m9","started_at":null}\n\n',
      // First think block — open tag split across two deltas
      'event: message_delta\ndata: {"text":"<thi"}\n\n',
      'event: message_delta\ndata: {"text":"nk>"}\n\n',
      // Think content emitted across three deltas
      'event: message_delta\ndata: {"text":"re"}\n\n',
      'event: message_delta\ndata: {"text":"as"}\n\n',
      'event: message_delta\ndata: {"text":"on"}\n\n',
      // Close tag split across two deltas
      'event: message_delta\ndata: {"text":"</"}\n\n',
      'event: message_delta\ndata: {"text":"think>"}\n\n',
      // Visible reply text across two deltas
      'event: message_delta\ndata: {"text":"hel"}\n\n',
      'event: message_delta\ndata: {"text":"lo"}\n\n',
      // Second think block — open + content + close all in one delta
      'event: message_delta\ndata: {"text":"<think>more reasoning</think>"}\n\n',
      // Trailing visible text (the " world" reply suffix)
      'event: message_delta\ndata: {"text":" world"}\n\n',
      // Final clean text
      'event: message_complete\ndata: {"text":"hello world","total_tokens":10,"elapsed_time":0.5}\n\n',
    ].join('')
    installFetchMock(streamResponse([sseBody]))

    // Act — collect every emitted event
    const events = await collectEvents(
      streamChat({ text: 'probe', apiBase: 'http://x', end_user: 'tester' }),
    )

    // Assert — every message_delta text is free of think-tag substrings
    const deltas = events.filter(
      (e): e is { type: 'message_delta'; text: string } => e.type === 'message_delta',
    )
    for (const d of deltas) {
      expect(d.text).not.toContain('<think>')
      expect(d.text).not.toContain('</think>')
    }

    // And the concatenated delta text equals the visible reply
    const joined = deltas.map((d) => d.text).join('')
    expect(joined).toBe('hello world')
  })

  it('emits residual safe suffix as final delta before yielding message_complete', async () => {
    // Arrange — final visible text arrives in a delta that also contains the
    // close tag, so the close lands in the same chunk as post-think content.
    const sseBody = [
      'event: session_started\ndata: {"session_id":"x","started_at":null}\n\n',
      'event: message_delta\ndata: {"text":"<think>reason</think>"}\n\n',
      'event: message_delta\ndata: {"text":"visible tail"}\n\n',
      'event: message_complete\ndata: {"text":"visible tail","total_tokens":1,"elapsed_time":0.1}\n\n',
    ].join('')
    installFetchMock(streamResponse([sseBody]))

    // Act
    const events = await collectEvents(
      streamChat({ text: 't', apiBase: 'http://x' }),
    )

    // Assert — the post-think tail delta is preserved and message_complete lands after
    const deltas = events.filter(
      (e): e is { type: 'message_delta'; text: string } => e.type === 'message_delta',
    )
    expect(deltas.map((d) => d.text).join('')).toBe('visible tail')

    const complete = events.find((e) => e.type === 'message_complete')
    expect(complete).toBeDefined()
  })
})