import { CircleCheck, CircleX, RadioTower } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { SurfaceObservation } from '@/lib/api'

const STATE_STYLE = {
  ready: { color: 'var(--ok)', tolerance: 'bp-tol-ok', Icon: CircleCheck },
  partial: { color: 'var(--high)', tolerance: 'bp-tol-high', Icon: RadioTower },
  unavailable: { color: 'var(--faint)', tolerance: 'bp-tol-flat', Icon: CircleX },
} as const

export function ObservationBanner({ observation }: { observation: SurfaceObservation }) {
  const { t } = useTranslation()
  const { color, tolerance, Icon } = STATE_STYLE[observation.state]
  const message = t(`observation.reason.${observation.reason}`)

  return (
    <section
      aria-live="polite"
      className="bp-panel mb-4 overflow-hidden"
      style={{ borderColor: `color-mix(in srgb, ${color} 52%, transparent)` }}
    >
      <div className="bp-dim flex flex-wrap items-center gap-2 px-4 py-2.5">
        <Icon aria-hidden="true" size={15} style={{ color }} />
        <span className="bp-label">{t('observation.label')}</span>
        <span className={`bp-tol ${tolerance}`}>{t(`observation.state.${observation.state}`)}</span>
        <span className="ml-auto font-mono text-[10px] text-faint">
          {t('observation.observed', { count: observation.observed_count })}
        </span>
      </div>
      <div className="space-y-3 px-4 py-3">
        <p className="font-mono text-[12px] leading-relaxed text-muted-foreground">{message}</p>
        <div className="grid gap-2 sm:grid-cols-2">
          <SignalList
            label={t('observation.covered')}
            signals={observation.covered_signals}
            tone="covered"
          />
          <SignalList
            label={t('observation.missing')}
            signals={observation.missing_signals}
            tone="missing"
          />
        </div>
      </div>
    </section>
  )
}

function SignalList({
  label,
  signals,
  tone,
}: {
  label: string
  signals: string[]
  tone: 'covered' | 'missing'
}) {
  const { t } = useTranslation()
  return (
    <div className="min-w-0">
      <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-faint">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {signals.length > 0 ? signals.map((signal) => (
          <span key={signal} className={`bp-tol ${tone === 'covered' ? 'bp-tol-ok' : 'bp-tol-high'} max-w-full whitespace-normal break-words text-left`}>
            {t(`observation.signal.${signal}`)}
          </span>
        )) : (
          <span className="font-mono text-[10px] text-faint">{t('observation.none')}</span>
        )}
      </div>
    </div>
  )
}
