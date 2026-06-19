import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/lib/auth'

export default function RequireAuth() {
  const { user, loading } = useAuth()
  const { t } = useTranslation()
  const location = useLocation()

  if (loading)
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>
      </div>
    )

  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />

  return <Outlet />
}
