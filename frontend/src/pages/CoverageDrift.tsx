import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import { fetchDriftSurface, type DriftSurface, type DriftContext } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'

const HEAT: Record<string, string> = { urgent: 'bp-tol-urgent', high: 'bp-tol-high', medium: 'bp-tol-high', low: 'bp-tol-flat' }

// Drift watch = release/incident freshness loss that can force a governance path.
// Sourced from the drift-governance surface (release deltas, incident updates, rewrite clusters).
export default function CoverageDrift() {
  const { t } = useTranslation()
  const [data, setData] = useState<DriftSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchDriftSurface().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(() => {
    fetchDriftSurface().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }, [])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="bp-panel p-4">
        <div className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const rows = data.contexts
  const urgent = rows.filter((c) => c.urgency === 'urgent').length
  const surfaces = new Set(rows.flatMap((c) => c.affected_surfaces)).size
  const watched = new Set(rows.flatMap((c) => c.evidence_ids)).size
  const driftObjs = new Set(rows.map((c) => c.proposal_ref)).size
  const ok = Math.max(0, watched - driftObjs)

  return (
    <>
      <p className="mb-3 font-mono text-[12px] leading-relaxed text-muted-foreground">{data.summary}</p>

      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={rows.length} label={t('drift.statDrift')} dot="var(--high)" />
        <Stat n={urgent} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
        <Stat n={watched} label={t('drift.statWatched')} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((c) => (
          <DriftCard key={c.proposal_ref} ctx={c} command={data.available_commands[0]} />
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="bp-panel px-[18px] py-10 text-center font-mono text-sm text-muted-foreground">{t('drift.empty')}</div>
      ) : ok > 0 ? (
        <div className="mt-4 flex items-center gap-2 bp-panel px-4 py-3 font-mono text-[13px] text-muted-foreground">
          <Check size={16} style={{ color: 'var(--ok)' }} />
          {t('drift.okFmt', { n: ok })}
        </div>
      ) : null}
    </>
  )
}

function DriftCard({ ctx, command }: { ctx: DriftContext; command: string }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div className="bp-panel overflow-hidden">
      <div className="bp-dim flex items-center gap-2 px-4 py-3">
        <span className="h-2 w-2 rotate-45" style={{ background: 'var(--high)' }} />
        <span className="font-mono text-[11px] font-bold uppercase tracking-wide" style={{ color: 'var(--high)' }}>{t('drift.flag')}</span>
        <span className={`bp-tol ${HEAT[ctx.urgency] ?? 'bp-tol-flat'} ml-auto`}>{t(`urgency.${ctx.urgency}`)}</span>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <div>
          <div className="font-mono text-[13px] font-semibold leading-tight">{ctx.title}</div>
          <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{ctx.proposal_ref} · {v.objectType(ctx.suggested_object_type)}</div>
        </div>
        <p className="text-[12.5px] leading-relaxed text-muted-foreground">{ctx.why_now}</p>

        {ctx.trigger_signals.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {ctx.trigger_signals.map((s) => <span key={s} className="bp-tol bp-tol-high">{s.replace(/_/g, ' ')}</span>)}
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {ctx.affected_surfaces.map((s) => <span key={s} className="bp-tol bp-tol-flat">{v.surface(s)}</span>)}
        </div>

        <div className="bp-dim flex items-center gap-2 pt-3">
          <div className="font-mono text-[10px] text-faint">
            {ctx.event_types.map((e) => e.replace(/_/g, ' ')).join(' · ')}
          </div>
          {command && <CmdButton command={command} className="ml-auto" />}
        </div>
      </div>
    </div>
  )
}
