import { Navigate, Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/lib/auth'
import { isSystemAdmin } from '@/lib/adminRoutes'

export default function RequireAdmin() {
  const { user, loading } = useAuth()
  const { t } = useTranslation()

  if (loading) {
    return (
      <div className="flex min-h-48 items-center justify-center" role="status">
        <span className="font-mono text-sm text-muted-foreground">{t('state.loading')}</span>
      </div>
    )
  }

  if (!isSystemAdmin(user)) return <Navigate to="/console" replace />
  return <Outlet />
}
