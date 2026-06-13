/**
 * M5 — single-file upload helper for H5 widget streaming flow.
 *
 * The Dify v2 workflow requires files to be uploaded via /api/files/upload first,
 * yielding a file_id, which is then passed to /api/chat/stream as file_ids[].
 * This helper handles the first leg only — streaming call is in difyStream.ts.
 */

export interface UploadFileResult {
  file_id: string
}

export class FileUploadError extends Error {
  readonly status?: number

  constructor(message: string, status?: number) {
    super(message)
    this.name = 'FileUploadError'
    this.status = status
  }
}

const ENDPOINT = '/api/files/upload'

export async function uploadFile(
  file: File,
  apiBase = '',
  signal?: AbortSignal,
): Promise<UploadFileResult> {
  const fd = new FormData()
  fd.append('file', file)

  let response: Response
  try {
    response = await fetch(`${apiBase}${ENDPOINT}`, {
      method: 'POST',
      body: fd,
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new FileUploadError(networkMessage(e))
  }

  if (!response.ok) {
    let detail = ''
    try {
      detail = await response.text()
    } catch {
      // ignore — surface status only
    }
    throw new FileUploadError(
      `HTTP ${response.status}${detail ? `: ${detail.slice(0, 200)}` : ''}`,
      response.status,
    )
  }

  let parsed: unknown
  try {
    parsed = await response.json()
  } catch (e) {
    throw new FileUploadError(`Bad JSON: ${networkMessage(e)}`)
  }
  if (!isObject(parsed) || typeof parsed.file_id !== 'string') {
    throw new FileUploadError('Missing file_id in response')
  }
  return { file_id: parsed.file_id }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null
}

function networkMessage(e: unknown): string {
  if (e instanceof Error) return e.message
  return String(e)
}