import { AlertTriangle, KeyRound, LockKeyhole, ServerCrash, WifiOff } from 'lucide-react'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation } from 'react-router-dom'
import { ApiError } from '@/lib/authApi'
import { Button } from '@/components/ui/button'

type RequestErrorKind = 'reauth' | 'permission' | 'notFound' | 'server' | 'network' | 'request'

function classifyRequestError(error: unknown): RequestErrorKind {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'reauth'
    if (error.status === 403) return 'permission'
    if (error.status === 404) return 'notFound'
    if (error.status === 0) return 'network'
    if (error.status >= 500) return 'server'
  }
  if (error instanceof TypeError) return 'network'
  return 'request'
}

function requestErrorDetail(error: unknown): string {
  if (error instanceof Error && error.message.trim()) return error.message
  return String(error)
}

const ICON = {
  reauth: KeyRound,
  permission: LockKeyhole,
  notFound: AlertTriangle,
  server: ServerCrash,
  network: WifiOff,
  request: AlertTriangle,
} as const

export function RequestErrorState({
  error,
  onRetry,
  compact = false,
  stale = false,
}: {
  error: unknown
  onRetry?: () => void
  compact?: boolean
  stale?: boolean
}) {
  const { t } = useTranslation()
  const location = useLocation()
  const headingId = useId()
  const kind = classifyRequestError(error)
  const Icon = ICON[kind]
  const returnTo = `${location.pathname}${location.search}${location.hash}`

  return (
    <section
      aria-labelledby={headingId}
      aria-live={stale ? 'polite' : 'assertive'}
      className={`bp-panel ${compact ? 'px-4 py-3' : 'p-5'}`}
      style={{ borderColor: 'color-mix(in srgb, var(--urgent) 45%, transparent)' }}
    >
      <div className="flex items-start gap-3">
        <Icon aria-hidden="true" className="mt-0.5 shrink-0" size={17} style={{ color: 'var(--urgent)' }} />
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="font-mono text-sm font-bold">
            {t(`requestState.${stale ? 'staleTitle' : `${kind}Title`}`)}
          </h2>
          <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">
            {t(`requestState.${stale ? 'staleHint' : `${kind}Hint`}`)}
          </p>
          <div className="mt-2 border-l-2 border-border pl-3 font-mono text-[11px] leading-relaxed text-foreground break-words">
            <span className="sr-only">{t('requestState.detail')} </span>
            {requestErrorDetail(error)}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {kind === 'reauth' ? (
              <Link
                to="/login"
                state={{ from: returnTo }}
                className="inline-flex h-8 items-center justify-center rounded-full bg-primary px-3 font-semibold text-primary-foreground text-xs transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 focus-visible:ring-offset-background"
              >
                {t('requestState.reauthenticate')}
              </Link>
            ) : null}
            {onRetry ? (
              <Button type="button" variant="ghost" size="sm" onClick={onRetry}>
                {t('state.retry')}
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  )
}
