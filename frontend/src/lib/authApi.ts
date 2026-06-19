// Auth client for the ported Arkon backend (app.main) — a SEPARATE server from the
// command-center API (cygnus.api.app on /api via Vite proxy). Auth therefore uses an
// absolute base URL so it bypasses the /api → :8077 proxy.
const AUTH_BASE = import.meta.env.VITE_AUTH_API_URL ?? 'http://localhost:8000'
const TOKEN_KEY = 'cygnus_token'
const REQUEST_TIMEOUT_MS = 30_000

export class ApiError extends Error {
  status: number
  data: unknown
  constructor(status: number, message: string, data?: unknown) {
    super(message)
    this.status = status
    this.data = data
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

type RequestOptions = { method?: string; body?: unknown; headers?: Record<string, string>; timeoutMs?: number }

export async function authApi<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, headers = {}, timeoutMs = REQUEST_TIMEOUT_MS } = options
  const token = getToken()
  const controller = new AbortController()
  const timerId = setTimeout(() => controller.abort(), timeoutMs)

  const config: RequestInit = {
    method,
    signal: controller.signal,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
  }
  if (body && method !== 'GET') config.body = JSON.stringify(body)

  let res: Response
  try {
    res = await fetch(`${AUTH_BASE}${path}`, config)
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw new ApiError(0, 'Request timed out')
    throw err
  } finally {
    clearTimeout(timerId)
  }

  if (!res.ok) {
    let data: unknown = null
    try { data = await res.json() } catch { data = null }
    const message = (data as { detail?: string })?.detail || `API Error ${res.status}`
    throw new ApiError(res.status, message, data)
  }

  const text = await res.text()
  if (!text) return {} as T
  return JSON.parse(text)
}
