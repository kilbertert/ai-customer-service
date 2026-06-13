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
  parseEvent,
  parseFields,
  streamChat,
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