import { useState } from 'react'
import { useNavigate, useLocation, Navigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Loader2 } from 'lucide-react'
import { useAuth } from '@/lib/auth'

// DWG-000 — the access control sheet. Login is the gate before the drawing set,
// so it gets the same engineering-drawing treatment as the console: grid paper,
// thin lines, a title block, and no rounded SaaS card.
export default function Login() {
  const { t } = useTranslation()
  const { login, user, loading: authLoading } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const from = (location.state as { from?: string } | null)?.from ?? '/console'

  const [email, setEmail] = useState('admin@cygnus.local')
  const [password, setPassword] = useState('admin123')
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
    <div className="bp-grid relative flex min-h-screen items-center justify-center overflow-hidden px-4">
      {/* corner registration marks on the whole sheet */}
      <span className="pointer-events-none absolute left-3 top-3 h-3 w-3 border-l border-t border-primary opacity-40" />
      <span className="pointer-events-none absolute right-3 top-3 h-3 w-3 border-r border-t border-primary opacity-40" />
      <span className="pointer-events-none absolute bottom-3 left-3 h-3 w-3 border-b border-l border-primary opacity-40" />
      <span className="pointer-events-none absolute bottom-3 right-3 h-3 w-3 border-b border-r border-primary opacity-40" />

      <div className="w-full max-w-md">
        {/* drawing number + title */}
        <div className="mb-4 flex items-baseline justify-between">
          <span className="bp-label">DWG-000 · ACCESS CONTROL</span>
          <span className="bp-label" style={{ opacity: 0.4 }}>SEC-A · AUTH</span>
        </div>

        <h1 className="mb-1 text-2xl font-bold tracking-tight">Cygnus</h1>
        <p className="mb-5 bp-label" style={{ opacity: 0.55 }}>{t('landing.eyebrow')}</p>

        {/* title block — session / environment parameters */}
        <div className="bp-title-block mb-5">
          <div className="bp-tb-row">
            <div className="bp-tb-cell">
              <div className="bp-tb-key">SESSION</div>
              <div className="bp-tb-val" style={{ fontSize: 13 }}>{t('auth.signIn')}</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">ENV</div>
              <div className="bp-tb-val" style={{ fontSize: 13, color: 'var(--faint)' }}>ON-PREM</div>
            </div>
            <div className="bp-tb-cell">
              <div className="bp-tb-key">STATUS</div>
              <div className="bp-tb-val" style={{ fontSize: 13, color: error ? 'var(--urgent)' : 'var(--ok)' }}>
                {error ? 'BLOCKED' : 'READY'}
              </div>
            </div>
          </div>
        </div>

        {/* the form itself — a panel, no rounding, no shadow */}
        <div className="bp-panel p-6">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <label className="flex flex-col gap-1.5">
              <span className="bp-label-inline">SEC-A · {t('auth.email')}</span>
              <input
                type="email"
                autoFocus
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@cygnus.local"
                className="border border-[color-mix(in_srgb,var(--primary)_30%,transparent)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none transition-colors focus:border-primary"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="bp-label-inline">SEC-B · {t('auth.password')}</span>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t('auth.passwordPlaceholder')}
                className="border border-[color-mix(in_srgb,var(--primary)_30%,transparent)] bg-transparent px-3 py-2 font-mono text-[13px] outline-none transition-colors focus:border-primary"
              />
            </label>

            {error && (
              <p
                className="border px-3 py-2 font-mono text-[11px]"
                style={{ color: 'var(--urgent)', borderColor: 'color-mix(in srgb, var(--urgent) 40%, transparent)' }}
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="bp-cmd mt-1 w-full justify-center py-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 size={13} className="animate-spin" />
                  {t('auth.signingIn')}
                </span>
              ) : (
                <>{t('auth.signIn')} →</>
              )}
            </button>
          </form>
        </div>

        {/* drawing footer — like the sheet scale/info line */}
        <div className="mt-5 flex items-center justify-between">
          <span className="bp-label" style={{ opacity: 0.4 }}>{t('auth.deployNote')}</span>
          <span className="bp-label" style={{ opacity: 0.4 }}>SCALE 1:1 · DWG-000</span>
        </div>
      </div>
    </div>
  )
}
