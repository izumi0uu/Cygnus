import { useEffect, useRef, useState } from 'react'
import { useNavigate, useLocation, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { PlotterPanel } from '@/components/PlotterPanel'
import { ApiError } from '@/lib/authApi'

// DWG-000 — the access control sheet. Login is the gate before the drawing set,
// so it gets the same engineering-drawing treatment as the console: grid paper,
// thin lines, a title block, and no rounded SaaS card.
export default function Login() {
  const { t } = useTranslation()
  const { login, user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const requestedFrom = (location.state as { from?: string } | null)?.from
  const from = requestedFrom?.startsWith('/') && !requestedFrom.startsWith('//') ? requestedFrom : '/console'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const errorRef = useRef<HTMLParagraphElement>(null)

  useEffect(() => {
    if (error) errorRef.current?.focus()
  }, [error])
  useEffect(() => {
    document.title = `${t('auth.signIn')} · Cygnus`
    return () => { document.title = t('document.baseTitle') }
  }, [t])

  if (authLoading) {
    return (
      <main className="bp-grid flex min-h-dvh items-center justify-center px-4" aria-busy="true">
        <div role="status" aria-live="polite" className="bp-panel flex items-center gap-2 p-4 font-mono text-sm text-muted-foreground">
          <Loader2 size={16} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
          {t('auth.checkingSession')}
        </div>
      </main>
    )
  }
  if (user) return <Navigate to={from} replace />

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate(from, { replace: true })
    } catch (err) {
      const invalidCredentials = err instanceof ApiError && err.status > 0 && err.status < 500
      setError(t(invalidCredentials ? 'auth.invalidCredentials' : 'auth.unavailable'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="bp-grid relative flex min-h-dvh items-center justify-center overflow-x-hidden overflow-y-auto px-4 py-8 sm:px-6">
      {/* corner registration marks on the whole sheet */}
      <span className="pointer-events-none absolute left-3 top-3 h-3 w-3 border-l border-t border-primary opacity-40" />
      <span className="pointer-events-none absolute right-3 top-3 h-3 w-3 border-r border-t border-primary opacity-40" />
      <span className="pointer-events-none absolute bottom-3 left-3 h-3 w-3 border-b border-l border-primary opacity-40" />
      <span className="pointer-events-none absolute bottom-3 right-3 h-3 w-3 border-b border-r border-primary opacity-40" />

      <div className="w-full max-w-md">
        {/* drawing number + title */}
        <div className="mb-4 flex items-baseline justify-between">
          <span className="bp-label">{t('auth.drawingId')}</span>
          <span className="bp-label">{t('auth.securitySection')}</span>
        </div>

        <h1 className="mb-1 text-2xl font-bold tracking-tight">Cygnus</h1>
        <p className="mb-5 bp-label">{t('landing.eyebrow')}</p>

        {/* title block — session / environment parameters */}
        <div className="bp-title-block mb-5">
          <div className="bp-tb-row">
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('auth.sessionLabel')}</div>
              <div className="bp-tb-val text-[13px]">{t('auth.signIn')}</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('auth.environmentLabel')}</div>
              <div className="bp-tb-val text-[13px] text-faint">{t('auth.environmentNeutral')}</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">{t('auth.statusLabel')}</div>
              <div className="bp-tb-val text-[13px]" style={{ color: error ? 'var(--urgent)' : 'var(--faint)' }}>
                {error ? t('auth.statusBlocked') : t('auth.statusAwaiting')}
              </div>
            </div>
          </div>
        </div>

        {/* The form reveal stays decorative; initial focus must not land in hidden content. */}
        <PlotterPanel className="p-4 sm:p-6" lapDuration={1.05}>
          <form onSubmit={handleSubmit} aria-busy={loading} aria-describedby="login-form-description" className="flex flex-col gap-4">
            <p id="login-form-description" className="sr-only">{t('auth.formDescription')}</p>
            <label className="flex flex-col gap-1.5">
              <span className="bp-label-inline">SEC-A · {t('auth.email')}</span>
              <input
                id="login-email"
                name="email"
                type="email"
                autoComplete="username"
                inputMode="email"
                required
                value={email}
                onChange={(e) => { setEmail(e.target.value); if (error) setError('') }}
                placeholder={t('auth.emailPlaceholder')}
                autoCapitalize="none"
                spellCheck={false}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'login-error' : undefined}
                className="min-h-11 border border-[color-mix(in_srgb,var(--primary)_30%,transparent)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none transition-colors focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="bp-label-inline">SEC-B · {t('auth.password')}</span>
              <input
                id="login-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => { setPassword(e.target.value); if (error) setError('') }}
                placeholder={t('auth.passwordPlaceholder')}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'login-error' : undefined}
                className="min-h-11 border border-[color-mix(in_srgb,var(--primary)_30%,transparent)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none transition-colors focus:border-primary"
              />
            </label>

            {error && (
              <p
                id="login-error"
                ref={errorRef}
                tabIndex={-1}
                role="alert"
                aria-live="assertive"
                className="border px-3 py-2 font-mono text-[12px] leading-relaxed"
                style={{ color: 'var(--urgent)', borderColor: 'color-mix(in srgb, var(--urgent) 40%, transparent)' }}
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              aria-busy={loading}
              className="bp-cmd mt-1 min-h-11 w-full justify-center py-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 size={13} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
                  {t('auth.signingIn')}
                </span>
              ) : (
                <>{t('auth.signIn')} →</>
              )}
            </button>
          </form>
        </PlotterPanel>

        {/* drawing footer — like the sheet scale/info line */}
        <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
          <span className="bp-label">{t('auth.deployNote')}</span>
          <span className="bp-label">{t('auth.sheetScale')}</span>
        </div>
      </div>
    </main>
  )
}
