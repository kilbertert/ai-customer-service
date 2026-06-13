/**
 * M6.2 — unit tests for fileUpload helper (H5 widget streaming flow).
 *
 * Coverage map:
 *   - success          → mock fetch returns {file_id: "abc"}
 *   - 401              → throws FileUploadError with status=401
 *   - 4xx with body    → message includes status + trimmed detail
 *   - 5xx              → throws FileUploadError with status=500
 *   - network failure  → throws FileUploadError (no status)
 *   - malformed JSON   → throws FileUploadError with "Bad JSON"
 *   - missing file_id  → throws FileUploadError with "Missing file_id"
 *   - AbortSignal      → AbortError propagates (NOT wrapped)
 *   - FormData shape   → posts multipart with "file" field, no Content-Type (browser sets boundary)
 */
import { describe, expect, it, vi, afterEach } from 'vitest'

import { uploadFile, FileUploadError } from '../fileUpload'

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  })
}

function installFetchMock(response: Response | Error | (() => Response | Error)) {
  // Wrap static Response in a factory so each call gets a fresh body
  // (single Response objects get their body consumed after first .text()/.json()).
  const factory = typeof response === 'function'
    ? response
    : () => response
  const fn = vi.fn(async (_url: unknown, init?: RequestInit) => {
    if (init?.signal?.aborted) {
      throw new DOMException('Aborted', 'AbortError')
    }
    const r = factory()
    if (r instanceof Error) throw r
    return r
  })
  globalThis.fetch = fn as unknown as typeof fetch
  return fn
}

function makeFile(name: string, content: string, type: string): File {
  return new File([content], name, { type })
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('uploadFile — happy path', () => {
  it('returns {file_id} on 200', async () => {
    installFetchMock(jsonResponse({ file_id: 'file-abc-123' }))
    const file = makeFile('test.png', 'png-binary', 'image/png')
    const result = await uploadFile(file)
    expect(result).toEqual({ file_id: 'file-abc-123' })
  })

  it('POSTs to /api/files/upload with FormData and "file" field', async () => {
    const fn = installFetchMock(jsonResponse({ file_id: 'f1' }))
    const file = makeFile('photo.jpg', 'jpeg-data', 'image/jpeg')
    await uploadFile(file, 'https://example.test')

    expect(fn).toHaveBeenCalledOnce()
    const [url, init] = fn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('https://example.test/api/files/upload')
    expect(init.method).toBe('POST')
    // FormData must be present (browser sets multipart boundary — we don't set Content-Type)
    expect(init.body).toBeInstanceOf(FormData)
    const fd = init.body as FormData
    expect(fd.get('file')).toBeInstanceOf(File)
    expect((fd.get('file') as File).name).toBe('photo.jpg')
    // Browser sets multipart boundary automatically — we must NOT set Content-Type.
    expect((init.headers as Record<string, string> | undefined)?.['Content-Type']).toBeUndefined()
  })

  it('appends apiBase correctly when provided', async () => {
    const fn = installFetchMock(jsonResponse({ file_id: 'x' }))
    await uploadFile(makeFile('a.png', 'x', 'image/png'), 'https://api.example.com')
    const [url] = fn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('https://api.example.com/api/files/upload')
  })

  it('uses empty apiBase by default (relative URL)', async () => {
    const fn = installFetchMock(jsonResponse({ file_id: 'x' }))
    await uploadFile(makeFile('a.png', 'x', 'image/png'))
    const [url] = fn.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/files/upload')
  })
})

describe('uploadFile — HTTP errors', () => {
  it('throws FileUploadError with status=401 on auth failure', async () => {
    installFetchMock(jsonResponse({ detail: 'unauthorized' }, 401))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      status: 401,
    })
  })

  it('includes server detail (truncated) in error message on 4xx', async () => {
    installFetchMock(new Response('bad request body detail', { status: 422 }))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      status: 422,
      message: 'HTTP 422: bad request body detail',
    })
  })

  it('truncates detail to 200 chars', async () => {
    const longDetail = 'x'.repeat(300)
    installFetchMock(new Response(longDetail, { status: 422 }))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      message: `HTTP 422: ${'x'.repeat(200)}`,
    })
  })

  it('throws FileUploadError with status=500 on upstream failure', async () => {
    installFetchMock(jsonResponse({ detail: 'oops' }, 500))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      status: 500,
    })
  })
})

describe('uploadFile — response body errors', () => {
  it('throws FileUploadError "Bad JSON" when body is not JSON', async () => {
    installFetchMock(new Response('not json at all', { status: 200 }))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      message: expect.stringContaining('Bad JSON'),
    })
  })

  it('throws FileUploadError "Missing file_id" when JSON omits file_id', async () => {
    installFetchMock(jsonResponse({ id: 'wrong-key' }, 200))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      message: expect.stringContaining('Missing file_id'),
    })
  })

  it('throws FileUploadError "Missing file_id" when file_id is non-string', async () => {
    installFetchMock(jsonResponse({ file_id: 12345 }, 200))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      message: expect.stringContaining('Missing file_id'),
    })
  })

  it('throws FileUploadError when top-level is array (not object)', async () => {
    installFetchMock(jsonResponse(['file_id', 'f1'], 200))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
    })
  })
})

describe('uploadFile — network + abort', () => {
  it('throws FileUploadError (no status) when fetch itself rejects', async () => {
    installFetchMock(new TypeError('Failed to fetch'))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toBeInstanceOf(FileUploadError)
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      message: 'Failed to fetch',
    })
  })

  it('throws FileUploadError on ECONNRESET-style error', async () => {
    installFetchMock(new Error('network timeout'))
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file)).rejects.toMatchObject({
      name: 'FileUploadError',
      message: 'network timeout',
    })
  })

  it('re-throws AbortError without wrapping in FileUploadError', async () => {
    installFetchMock(jsonResponse({ file_id: 'never-reached' }))
    const ctrl = new AbortController()
    ctrl.abort()
    const file = makeFile('a.png', 'x', 'image/png')
    await expect(uploadFile(file, '', ctrl.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
    await expect(uploadFile(file, '', ctrl.signal)).rejects.not.toBeInstanceOf(FileUploadError)
  })

  it('passes signal to fetch', async () => {
    const fn = installFetchMock(jsonResponse({ file_id: 'f1' }))
    const ctrl = new AbortController()
    const file = makeFile('a.png', 'x', 'image/png')
    await uploadFile(file, '', ctrl.signal)
    expect(fn).toHaveBeenCalledOnce()
    const [, init] = fn.mock.calls[0] as [string, RequestInit]
    expect(init.signal).toBe(ctrl.signal)
  })
})