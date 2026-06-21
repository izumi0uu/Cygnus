import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { authApi, setToken, clearToken, getToken, ApiError } from '@/lib/authApi'

export type WorkspaceMembership = { workspace_id: string; workspace_name: string; role: string }

export type User = {
  id: string
  name: string
  email: string
  role: 'admin' | 'employee'
  department_ids: string[]
  department_names: string[]
  permissions: string[]
  workspace_memberships: WorkspaceMembership[]
}

type AuthState = {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
  hasPermission: (perm: string) => boolean
  canAccess: (resource: string, action: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(() => getToken() !== null)

  const refresh = useCallback(async () => {
    try {
      const data = await authApi<User>('/api/auth/me')
      setUser(data)
    } catch (err) {
      setUser(null)
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) clearToken()
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!getToken()) return
    void authApi<User>('/api/auth/me')
      .then((data) => {
        setUser(data)
      })
      .catch((err) => {
        setUser(null)
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) clearToken()
      })
      .finally(() => setLoading(false))
  }, [])

  const login = async (email: string, password: string) => {
    const data = await authApi<{ access_token: string; user: User }>('/api/auth/login', {
      method: 'POST',
      body: { email, password },
    })
    setToken(data.access_token)
    setUser(data.user)
  }

  const logout = () => {
    clearToken()
    setUser(null)
  }

  const hasPermission = useCallback(
    (perm: string) => {
      if (!user) return false
      if (user.role === 'admin') return true
      return user.permissions?.includes(perm) ?? false
    },
    [user],
  )

  const canAccess = useCallback(
    (resource: string, action: string) => {
      if (!user) return false
      if (user.role === 'admin') return true
      const all = `${resource}:${action}:all`
      const own = `${resource}:${action}:own_dept`
      return (user.permissions?.includes(all) ?? false) || (user.permissions?.includes(own) ?? false)
    },
    [user],
  )

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh, hasPermission, canAccess }}>
      {children}
    </AuthContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
