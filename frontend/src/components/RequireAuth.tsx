import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/lib/auth'
import { NotificationProvider } from '@/lib/notification-state'

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

  // Preserve the full deep link (pathname + search + hash) through the login
  // round-trip so authenticated redirects land on the exact target — e.g. a
  // shared notification URL like /console/queue?risk=…#top stays intact.
  const from = location.pathname + location.search + location.hash

  if (!user) return <Navigate to="/login" replace state={{ from }} />

  return (
    <NotificationProvider>
      <Outlet />
    </NotificationProvider>
  )
}
