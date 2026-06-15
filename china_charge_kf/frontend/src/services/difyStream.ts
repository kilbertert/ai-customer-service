/**
 * M5 — Dify SSE stream consumer for H5 widget.
 *
 * > **FROZEN-DEPRECATED 2026-06-15** — M10 G4 PR3 物理合并完成。本文件已在
 * > basjoo 仓 `frontend-nextjs/src/services/difyStream.ts` 落地 (commit
 * > `fc7bc4a`)。新改动请在 basjoo 仓提交,本目录保留只读。
 * > 详见 `china_charge_kf/M10-FROZEN-README.md`。
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
      // M6.1 — text is nullable: backend `extract_output_text` may yield None on
      // U2/U7/U10 paths (see backend/app_dify/dify_client.py extract_output_text).
      // Frontend distinguishes "no reply" (null) from "empty reply" ('').
      text: string | null
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
  // M9.1 — strip <think>...</think> blocks across chunk boundaries so raw
  // reasoning never enters the bubble DOM. See createThinkStripper() below.
  const stripper = createThinkStripper()

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
        if (!event) continue
        for (const out of routeEvent(event, stripper)) yield out
      }
    }

    buffer += decoder.decode()
    const tail = buffer.trim()
    if (tail) {
      const event = parseEvent(tail)
      if (event) for (const out of routeEvent(event, stripper)) yield out
    }

    // Stream done — release any trailing residual that never reached a non-delta event
    const residual = stripper.flush()
    if (residual) yield { type: 'message_delta', text: residual }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      // reader may already be released by AbortSignal — ignore
    }
  }
}

/**
 * M9.1 — Route a parsed SSE event through the <think> stripper.
 *
 * - message_delta: feed the text through the stripper; yield the safe-to-emit prefix
 *   (may be empty if the chunk is entirely inside a think block).
 * - any other event (session_started / message_complete / error / end):
 *   flush the stripper first so any buffered safe-to-emit suffix lands as a final
 *   delta BEFORE downstream consumers see the terminator event. M8.2
 *   stripThinkTags still runs on message_complete.text as an idempotent final
 *   safeguard — M9.1 + M8.2 form a defense-in-depth pair, not a replacement.
 */
function routeEvent(
  event: DifyStreamEvent,
  stripper: ThinkStripper,
): DifyStreamEvent[] {
  if (event.type === 'message_delta') {
    const safeText = stripper.feed(event.text)
    return safeText ? [{ type: 'message_delta', text: safeText }] : []
  }
  const flushed = stripper.flush()
  const out: DifyStreamEvent[] = []
  if (flushed) out.push({ type: 'message_delta', text: flushed })
  out.push(event)
  return out
}

export function parseEvent(rawBlock: string): DifyStreamEvent | null {
  const fields = parseFields(rawBlock)
  // M10 §6.2 #5: dual-source event type parsing. data JSON 可独立提供
  // event (Dify v2 真实部署 124.243.178.156:8501 不写 SSE event 字段),
  // 所以这里只要求 data 存在 — event 由下面 dual-source 解析兜底。
  if (!fields.data) return null

  let parsed: unknown
  try {
    parsed = JSON.parse(fields.data)
  } catch {
    return null
  }
  if (!isObject(parsed)) return null

  // M10 §6.2 #5: data JSON `event` 字段优先于 SSE `event:` 行。
  // - 真实 Dify v2 (M7.5) 只写 inner event 键,SSE `event:` 为空
  // - 真实 Dify v1 只写 SSE `event:` 行,inner 键不存在
  // - 部分中间路径会同时写两者但内容可能不一致 → 以 data 为准
  // Pre-M10 我们只读 SSE,导致 v2 事件被静默丢成 null(SseProxyLayer
  // 当作未知类型过滤掉),前端看到 0 事件 — 静默失败。
  const innerEvent =
    typeof parsed.event === 'string' && parsed.event.trim()
      ? parsed.event.trim()
      : ''
  const event = innerEvent || fields.event || ''

  if (event === 'end') {
    return { type: 'end' }
  }
  if (!event) return null  // SSE/data 都没有 event → 真无效

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
        // M6.1 — preserve null vs '' distinction: null = backend yielded None,
        // '' = backend yielded empty string. stringOrEmpty() would collapse both.
        text: parsed.text === null ? null : stringOrEmpty(parsed.text),
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

// ============== M8.2 — defense-in-depth <think> strip ==============

/**
 * Strip `<think>...</think>` blocks (lazy / multi-line / case-insensitive).
 *
 * Why duplicated with backend `extract_output_text` (PR9 U7): backend strips
 * thinking on workflow_finished.data.output extraction. This frontend pass is
 * defense-in-depth for two paths backend cannot cover:
 *   1) accumulated message_delta text (backend strips per-chunk only inside
 *      Dify's text_chunk emitter — partial `<think>` straddling chunks slips through)
 *   2) message_complete.text values produced by non-`output` fallback keys not
 *      yet routed through extract_output_text (M8.2 surface area)
 *
 * Lazy `[\s\S]*?` matches across newlines without grabbing past the first `</think>`.
 * `gi` flag — strip all occurrences, tolerate `<Think>` / `<THINK>`.
 */
const THINK_TAG_RE = /<think>[\s\S]*?<\/think>/gi

export function stripThinkTags(text: string): string {
  if (!text) return text
  return text.replace(THINK_TAG_RE, '')
}

// ============== M8.1 — abort state decision ==============

export interface AbortStatePatch {
  stopped: boolean
  noResponse: boolean
}

/**
 * Decide how to render an assistant message that was aborted mid-stream.
 *
 * Two distinct UX states (M6.1 + M6.3 semantics, unified here):
 *   - `noResponse: true` — user clicked stop BEFORE any text_chunk arrived
 *     (assistant bubble is empty → render as "(no response)" placeholder,
 *     consistent with M6.1 backend-None handling)
 *   - `stopped: true`    — user clicked stop AFTER partial text arrived
 *     (assistant bubble has content → render with "(stopped)" suffix tag,
 *     existing M6.3 behavior)
 *
 * Caller spreads the returned patch onto the ChatMessage. Both fields are
 * always set (not undefined) so a previous `stopped` state from another
 * abort cannot leak through.
 */
export function abortStatePatch(currentText: string | null | undefined): AbortStatePatch {
  if (!currentText) return { stopped: false, noResponse: true }
  return { stopped: true, noResponse: false }
}

// ============== M9.1 — stream-level <think> buffer ==============

/**
 * Strip <think>...</think> blocks across SSE chunk boundaries.
 *
 * Why hand-rolled vs per-chunk regex: real Dify v2 emits character-level tokens
 * (~1-3 chars per chunk). The per-chunk regex `<think>[\s\S]*?</think>` only
 * matches open+close in the SAME string. Across chunks the open and close
 * never coexist, so per-chunk strip is a complete no-op on real Dify
 * (see M9-PROMPT §1 / real-dify-per-chunk-strip-noop memory).
 *
 * Algorithm — three rules (M9-PROMPT §2):
 *   1. Accumulate chunks into internal buffer
 *   2. While NOT inside a think block:
 *      - No `<think>` → emit all, clear buffer
 *      - `<think>` found → emit prefix before it, set state to inside-think
 *   3. While inside a think block:
 *      - No `</think>` → hold all (wait for close)
 *      - `</think>` found → skip past it, exit inside-think
 *   4. Edge case — chunk boundary inside the tag characters: hold back any
 *      trailing `<` (could be start of partial open or close tag) until next
 *      chunk disambiguates it. The lookahead window is `len(tag) - 1` chars.
 *
 * flush() at stream end drops any unclosed think residue (model anomaly)
 * plus releases any safe-to-emit suffix that drain() retained due to a
 * trailing-`<` lookahead at end-of-stream.
 */
export interface ThinkStripper {
  /**
   * Feed a delta chunk; return the safe-to-emit prefix.
   * Empty string means "hold everything; nothing to emit yet".
   */
  feed(chunk: string): string
  /**
   * Flush remaining buffered text at stream end.
   * Drops any unclosed think residue. Returns any safe-to-emit suffix.
   */
  flush(): string
}

const THINK_OPEN_TAG = '<think>'
const THINK_CLOSE_TAG = '</think>'

export function createThinkStripper(): ThinkStripper {
  let buffer = ''
  let insideThink = false

  function drain(): string {
    let emit = ''
    // Loop because one buffer may contain multiple think blocks + intervening text
    // (M9-PROMPT §1.5 baseline shows 3 think blocks per real Dify response).
    while (true) {
      if (insideThink) {
        const closeIdx = buffer.indexOf(THINK_CLOSE_TAG)
        if (closeIdx === -1) {
          // Inside think block, waiting for close. Hold ENTIRE buffer — we
          // never emit anything from inside a think block, including any
          // text that appears before a trailing partial-close prefix.
          // The hold includes the partial close prefix so the next chunk can
          // either confirm `</think>` (we then resume emitting) or override
          // it as literal content (we drop it on flush).
          const lastLt = buffer.lastIndexOf('<')
          if (lastLt !== -1 && buffer.length - lastLt < THINK_CLOSE_TAG.length) {
            buffer = buffer.slice(lastLt)
          } else {
            buffer = ''
          }
          return emit
        }
        // Skip past close tag, exit think mode, continue loop to drain remainder
        buffer = buffer.slice(closeIdx + THINK_CLOSE_TAG.length)
        insideThink = false
      } else {
        const openIdx = buffer.indexOf(THINK_OPEN_TAG)
        if (openIdx === -1) {
          // No open tag — hold trailing partial-open prefix (e.g. "<thi")
          // so the next chunk can confirm or reject it as a real think tag.
          const lastLt = buffer.lastIndexOf('<')
          if (lastLt !== -1 && buffer.length - lastLt < THINK_OPEN_TAG.length) {
            emit += buffer.slice(0, lastLt)
            buffer = buffer.slice(lastLt)
          } else {
            emit += buffer
            buffer = ''
          }
          return emit
        }
        // Found open tag — emit prefix before it, enter think mode
        emit += buffer.slice(0, openIdx)
        buffer = buffer.slice(openIdx + THINK_OPEN_TAG.length)
        insideThink = true
      }
    }
  }

  return {
    feed(chunk: string): string {
      buffer += chunk
      return drain()
    },
    flush(): string {
      const rest = drain()
      // Drop any leftover buffer residue — partial tag or unclosed think block.
      // Per spec §2, unclosed `<think>` is treated as a model anomaly and discarded.
      buffer = ''
      insideThink = false
      return rest
    },
  }
}