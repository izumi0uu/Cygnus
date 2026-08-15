import { afterEach, describe, expect, it, vi } from 'vitest'
import { logoutPortalSession } from './authApi'

function installLocalStorage(token: string) {
  const getItem = vi.fn((key: string) => (key === 'cygnus_token' ? token : null))
  const removeItem = vi.fn()
  vi.stubGlobal('localStorage', {
    getItem,
    setItem: vi.fn(),
    removeItem,
  })
  return { getItem, removeItem }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('portal logout', () => {
  it('starts authenticated server revocation before clearing local auth state', async () => {
    const storage = installLocalStorage('portal-token')
    const fetchMock = vi.fn(
      async (...args: [RequestInfo | URL, RequestInit?]): Promise<Response> => {
        void args
        return new Response(null, { status: 204 })
      },
    )
    vi.stubGlobal('fetch', fetchMock)
    let localUser: object | null = { id: 'employee-1' }
    const clearAuthState = vi.fn(() => {
      localUser = null
    })

    const logout = logoutPortalSession(clearAuthState)

    expect(fetchMock).toHaveBeenCalledOnce()
    const [path, request] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/auth/logout')
    expect(request?.method).toBe('POST')
    expect((request?.headers as Record<string, string>).Authorization).toBe(
      'Bearer portal-token',
    )
    expect(fetchMock.mock.invocationCallOrder[0]).toBeLessThan(
      storage.removeItem.mock.invocationCallOrder[0],
    )
    expect(storage.removeItem).toHaveBeenCalledWith('cygnus_token')
    expect(clearAuthState).toHaveBeenCalledOnce()
    expect(localUser).toBeNull()
    await expect(logout).resolves.toBeUndefined()
  })

  it('always clears the token and provider state when revocation is unreachable', async () => {
    const storage = installLocalStorage('stale-portal-token')
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('network unavailable')
      }),
    )
    let localUser: object | null = { id: 'employee-2' }
    const clearAuthState = vi.fn(() => {
      localUser = null
    })

    await expect(logoutPortalSession(clearAuthState)).resolves.toBeUndefined()

    expect(storage.removeItem).toHaveBeenCalledWith('cygnus_token')
    expect(clearAuthState).toHaveBeenCalledOnce()
    expect(localUser).toBeNull()
  })
})
