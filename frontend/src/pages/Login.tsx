import { useState } from 'react'
import { useNavigate, useLocation, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'

export default function Login() {
  const { t } = useTranslation()
  const { login, user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/console'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  if (!authLoading && user) return <Navigate to={from} replace />

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('auth.failed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-[10px] bg-primary text-lg font-extrabold text-primary-foreground">C</div>
          <h1 className="text-2xl font-bold tracking-tight">Cygnus</h1>
          <p className="mt-1 font-mono text-[11px] uppercase tracking-widest text-faint">{t('landing.eyebrow')}</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-7 shadow-soft">
          <h2 className="mb-5 text-lg font-bold">{t('auth.signIn')}</h2>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-muted-foreground">{t('auth.email')}</span>
              <input
                type="email"
                autoFocus
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@arkon.local"
                className="rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm outline-none transition-shadow focus:border-primary focus:ring-2 focus:ring-primary/25"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[13px] font-medium text-muted-foreground">{t('auth.password')}</span>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('auth.passwordPlaceholder')}
                className="rounded-lg border border-border bg-background px-3.5 py-2.5 text-sm outline-none transition-shadow focus:border-primary focus:ring-2 focus:ring-primary/25"
              />
            </label>

            {error && (
              <p className="rounded-lg px-3 py-2 text-[13px]" style={{ color: 'var(--urgent)', background: 'color-mix(in srgb, var(--urgent) 10%, transparent)' }}>
                {error}
              </p>
            )}

            <Button type="submit" disabled={loading} className="mt-1 w-full">
              {loading ? (
                <span className="flex items-center justify-center gap-2"><Loader2 size={15} className="animate-spin" />{t('auth.signingIn')}</span>
              ) : (
                t('auth.signIn')
              )}
            </Button>
          </form>
        </div>

        <p className="mt-5 text-center font-mono text-[10px] text-faint">{t('auth.deployNote')}</p>
      </div>
    </div>
  )
}
