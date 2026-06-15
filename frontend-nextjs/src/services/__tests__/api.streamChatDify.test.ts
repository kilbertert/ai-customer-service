/**
 * M10 PR4b — api.ts streamChat Dify delegation.
 *
 * Verifies the new `options.useDifyStream` flag routes to difyStream.ts consumer
 * instead of the inline LLM parser. LLM path (flag absent/false) is regression-
 * tested by api.ts's existing call sites; we don't duplicate those tests here.
 *
 * Coverage map (PR4b acceptance gate):
 *   - flag true, happy     → message_delta chunks → onContent, then
 *                            message_complete → onDone with session_id+usage
 *   - flag true, think     → difyStream stripper removes <think> mid-stream
 *   - flag true, error     → DifyStreamError surfaces via onError
 *   - flag true, headers   → Bearer token from localStorage passed through;
 *                            absent when no token.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../api'

const encoder = new TextEncoder()

function sseResponse(chunks: string[], status = 200): Response {
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

function installFetchMock(response: Response) {
  const fn = vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return response
  })
  globalThis.fetch = fn as unknown as typeof fetch
  return fn
}

const originalFetch = globalThis.fetch
const originalToken = localStorage.getItem('token')

beforeEach(() => {
  localStorage.setItem('token', 'test-bearer-abc')
})

afterEach(() => {
  globalThis.fetch = originalFetch
  if (originalToken === null) {
    localStorage.removeItem('token')
  } else {
    localStorage.setItem('token', originalToken)
  }
  vi.restoreAllMocks()
})

describe('api.streamChat — Dify delegation (PR4b)', () => {
  it('routes to difyStream.ts when useDifyStream:true and emits deltas + done', async () => {
    const sseBody =
      'event: session_started\ndata: {"session_id":"wf-99","started_at":null}\n\n' +
      'event: message_delta\ndata: {"text":"hello "}\n\n' +
      'event: message_delta\ndata: {"text":"world"}\n\n' +
      'event: message_complete\ndata: {"text":"hello world","total_tokens":42,"elapsed_time":0.3}\n\n'
    const mockFetch = installFetchMock(sseResponse([sseBody]))

    const chunks: string[] = []
    let doneMeta: unknown = null
    let errorMsg: string | null = null

    await api.streamChat(
      {
        agent_id: 'agent-1',
        message: 'hi',
        locale: 'zh-CN',
      },
      {
        onSources: () => {},
        onContent: (c) => chunks.push(c),
        onDone: (m) => {
          doneMeta = m
        },
        onError: (e) => {
          errorMsg = e
        },
      },
      { useDifyStream: true },
    )

    expect(errorMsg).toBeNull()
    expect(chunks.join('')).toBe('hello world')
    expect(doneMeta).toMatchObject({
      message_id: null,
      session_id: 'wf-99',
      usage: { prompt_tokens: 0, completion_tokens: 42, total_tokens: 42 },
      taken_over: false,
    })
    // Verify fetch was called with /api/v1/chat/stream + Bearer header
    const call = mockFetch.mock.calls[0]
    expect(call[0]).toBe('http://localhost:8000/api/v1/chat/stream')
    const headers = (call[1] as RequestInit).headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer test-bearer-abc')
    expect(headers.Accept).toBe('text/event-stream')
  })

  it('strips <think> blocks mid-stream (delegates to difyStream createThinkStripper)', async () => {
    const sseBody =
      'event: session_started\ndata: {"session_id":"s1","started_at":null}\n\n' +
      'event: message_delta\ndata: {"text":"<think>reasoning</think>clean answer"}\n\n' +
      'event: message_complete\ndata: {"text":"clean answer","total_tokens":0,"elapsed_time":0}\n\n'
    installFetchMock(sseResponse([sseBody]))

    const chunks: string[] = []

    await api.streamChat(
      { agent_id: 'a', message: 'x' },
      {
        onSources: () => {},
        onContent: (c) => chunks.push(c),
        onDone: () => {},
        onError: () => {},
      },
      { useDifyStream: true },
    )

    const concatenated = chunks.join('')
    expect(concatenated).not.toContain('<think>')
    expect(concatenated).not.toContain('reasoning')
    expect(concatenated).toContain('clean answer')
  })

  it('surfaces DifyStreamError via onError when fetch returns 4xx', async () => {
    installFetchMock(sseResponse(['bad'], 401))

    let errorMsg: string | null = null

    await api.streamChat(
      { agent_id: 'a', message: 'x' },
      {
        onSources: () => {},
        onContent: () => {},
        onDone: () => {},
        onError: (e) => {
          errorMsg = e
        },
      },
      { useDifyStream: true },
    )

    expect(errorMsg).toBeTruthy()
    expect(errorMsg).toMatch(/HTTP 401/)
  })

  it('omits Authorization header when no token in localStorage', async () => {
    localStorage.removeItem('token')
    const sseBody =
      'event: session_started\ndata: {"session_id":"s","started_at":null}\n\n' +
      'event: message_complete\ndata: {"text":"","total_tokens":0,"elapsed_time":0}\n\n'
    const mockFetch = installFetchMock(sseResponse([sseBody]))

    await api.streamChat(
      { agent_id: 'a', message: 'x' },
      {
        onSources: () => {},
        onContent: () => {},
        onDone: () => {},
        onError: () => {},
      },
      { useDifyStream: true },
    )

    const headers = (mockFetch.mock.calls[0][1] as RequestInit).headers as Record<
      string,
      string
    >
    expect(headers.Authorization).toBeUndefined()
  })
})
