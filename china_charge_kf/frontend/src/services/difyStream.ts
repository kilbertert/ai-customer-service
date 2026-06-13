/**
 * M5 — Dify SSE stream consumer for H5 widget.
 *
 * Why hand-rolled: native EventSource only does GET; /api/chat/stream is POST + JSON body.
 * Why no deps: half-packet / sticky buffer / abort are ~30 lines — pulling in eventsource-parser
 * or rxjs for one POST endpoint is overkill (CLAUDE.md "no new heavy deps").
 *
 * Wire format (M3 SseProxyLayer + M4 main.py wrapper, see docs/api-contract-dify.md §4.2.1):
 *   event: session_started\ndata: {"session_id":"...","started_at":null}\n\n
 *   event: message_delta\ndata: {"text":"..."}\n\n     (0..N times)
 *   event: message_complete\ndata: {"text":"...","total_tokens":int,"elapsed_time":float}\n\n
 *   event: error\ndata: {"code":"DIFY_AUTH|DIFY_BAD_REQUEST|DIFY_UPSTREAM|DIFY_UNKNOWN","message":"..."}\n\n
 *   event: end\ndata: {}\n\n                            (error path terminator only)
 *
 * Buffering rules:
 *   - accumulator holds UTF-8 bytes-to-string across chunks (sticky / half-packet)
 *   - split on the FIRST `\n\n` boundary; remaining text stays in buffer for next chunk
 *   - within one event, lines may be split by `\r\n` or `\n`; tolerate both
 *   - lines starting with `:` are SSE comments — ignored
 *   - on stream end, flush any final event without trailing blank line
 */

export type DifyErrorCode =
  | 'DIFY_AUTH'
  | 'DIFY_BAD_REQUEST'
  | 'DIFY_UPSTREAM'
  | 'DIFY_UNKNOWN'

export type DifyStreamEvent =
  | { type: 'session_started'; session_id: string; started_at: string | null }
  | { type: 'message_delta'; text: string }
  | {
      type: 'message_complete'
      text: string
      total_tokens: number
      elapsed_time: number
    }
  | { type: 'error'; code: DifyErrorCode; message: string }
  | { type: 'end' }

export interface ChatStreamParams {
  text: string
  file_ids?: string[]
  language?: string
  end_user?: string
  apiBase?: string
  signal?: AbortSignal
}

interface RawSseFields {
  event?: string
  data?: string
}

const ENDPOINT = '/api/chat/stream'

export class DifyStreamError extends Error {
  readonly code: DifyErrorCode | 'NETWORK' | 'BAD_HTTP' | 'BAD_JSON'
  readonly status?: number

  constructor(
    message: string,
    code: DifyStreamError['code'],
    status?: number,
  ) {
    super(message)
    this.name = 'DifyStreamError'
    this.code = code
    this.status = status
  }
}

export async function* streamChat(
  params: ChatStreamParams,
): AsyncGenerator<DifyStreamEvent, void, void> {
  const {
    text,
    file_ids = [],
    language,
    end_user,
    apiBase = '',
    signal,
  } = params

  const body: Record<string, unknown> = { text, file_ids }
  if (language !== undefined) body.language = language
  if (end_user !== undefined) body.end_user = end_user

  let response: Response
  try {
    response = await fetch(`${apiBase}${ENDPOINT}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    if (isAbortError(e)) throw e
    throw new DifyStreamError(networkMessage(e), 'NETWORK')
  }

  if (!response.ok) {
    let detail = ''
    try {
      detail = await response.text()
    } catch {
      // ignore — surface status only
    }
    throw new DifyStreamError(
      `HTTP ${response.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`,
      'BAD_HTTP',
      response.status,
    )
  }

  if (!response.body) {
    throw new DifyStreamError('Response body is empty', 'BAD_HTTP', response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      let sepIndex: number
      while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, sepIndex)
        buffer = buffer.slice(sepIndex + 2)
        const event = parseEvent(raw)
        if (event) yield event
      }
    }

    buffer += decoder.decode()
    const tail = buffer.trim()
    if (tail) {
      const event = parseEvent(tail)
      if (event) yield event
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // reader may already be released by AbortSignal — ignore
    }
  }
}

export function parseEvent(rawBlock: string): DifyStreamEvent | null {
  const fields = parseFields(rawBlock)
  if (!fields.event || !fields.data) return null

  const event = fields.event
  const dataText = fields.data

  if (event === 'end') {
    return { type: 'end' }
  }

  let parsed: unknown
  try {
    parsed = JSON.parse(dataText)
  } catch {
    return null
  }
  if (!isObject(parsed)) return null

  switch (event) {
    case 'session_started':
      return {
        type: 'session_started',
        session_id: stringOrEmpty(parsed.session_id),
        started_at: parsed.started_at == null ? null : String(parsed.started_at),
      }
    case 'message_delta':
      return {
        type: 'message_delta',
        text: stringOrEmpty(parsed.text),
      }
    case 'message_complete':
      return {
        type: 'message_complete',
        text: stringOrEmpty(parsed.text),
        total_tokens: numberOrZero(parsed.total_tokens),
        elapsed_time: numberOrZero(parsed.elapsed_time),
      }
    case 'error':
      return {
        type: 'error',
        code: normalizeErrorCode(parsed.code),
        message: stringOrEmpty(parsed.message),
      }
    default:
      return null
  }
}

export function parseFields(rawBlock: string): RawSseFields {
  const fields: RawSseFields = {}
  const lines = rawBlock.split(/\r?\n/)
  for (const line of lines) {
    if (!line || line.startsWith(':')) continue
    const colonAt = line.indexOf(':')
    if (colonAt === -1) {
      fields.event = fields.event ?? line
      continue
    }
    const name = line.slice(0, colonAt)
    const value = line.slice(colonAt + 1).replace(/^ /, '')
    if (name === 'event') fields.event = value
    else if (name === 'data') fields.data = fields.data ? `${fields.data}\n${value}` : value
  }
  return fields
}

function normalizeErrorCode(raw: unknown): DifyErrorCode {
  if (
    raw === 'DIFY_AUTH' ||
    raw === 'DIFY_BAD_REQUEST' ||
    raw === 'DIFY_UPSTREAM' ||
    raw === 'DIFY_UNKNOWN'
  ) {
    return raw
  }
  return 'DIFY_UNKNOWN'
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function stringOrEmpty(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

function numberOrZero(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : 0
}

function networkMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}

function isAbortError(e: unknown): boolean {
  return (
    typeof DOMException !== 'undefined' &&
    e instanceof DOMException &&
    e.name === 'AbortError'
  )
}