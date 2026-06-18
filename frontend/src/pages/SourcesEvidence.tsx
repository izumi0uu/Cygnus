import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import { fetchCommandCenter, type CommandCenterSurface } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'

const HEAT: Record<string, string> = { urgent: 'chip-urgent', high: 'chip-high', medium: 'chip-medium', low: 'chip' }

// Source/evidence integrity health board — source_blindness risks as status cards.
export default function SourcesEvidence() {
  const { t } = useTranslation()
  const v = useVocab()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(load, [])

  if (loading) return <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const rows = data.priority_stack.filter((it) => it.risk_type === 'source_blindness')
  const urgent = rows.filter((it) => it.urgency === 'urgent').length
  const surfaces = new Set(rows.flatMap((it) => it.affected_surfaces)).size
  const watched = new Set(data.priority_stack.map((it) => it.object_ref)).size
  const blindObjs = new Set(rows.map((it) => it.object_ref)).size
  const ok = Math.max(0, watched - blindObjs)

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={rows.length} label={t('src.statSources')} dot="var(--urgent)" />
        <Stat n={urgent} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
        <Stat n={watched} label={t('src.statWatched')} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((it) => (
          <div key={it.risk_id} className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
            <div
              className="flex items-center gap-2 border-b border-border px-4 py-3"
              style={{ background: 'color-mix(in srgb, var(--urgent) 8%, transparent)' }}
            >
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: 'var(--urgent)' }} />
              <span className="text-[13px] font-bold" style={{ color: 'var(--urgent)' }}>{t('src.blind')}</span>
              <span className={`chip ${HEAT[it.urgency]} ml-auto`}>{t(`urgency.${it.urgency}`)}</span>
            </div>
            <div className="flex flex-col gap-3 p-4">
              <div>
                <div className="font-mono text-[12.5px] font-semibold">{it.object_ref}</div>
                <div className="font-mono text-[10px] text-muted-foreground">{v.objectType(it.object_type)}</div>
              </div>
              <p className="text-[12.5px] leading-relaxed text-muted-foreground">{it.why_now_summary}</p>
              <div className="flex flex-wrap gap-1.5">
                {it.affected_surfaces.map((s) => <span key={s} className="chip">{v.surface(s)}</span>)}
              </div>
              <div className="flex items-center gap-2 border-t border-border pt-3">
                {it.owner_state === 'unassigned'
                  ? <span className="chip chip-gap">{t('owner.gap')}</span>
                  : <span className="font-mono text-[11.5px] text-muted-foreground">@{it.queue_owner}</span>}
                <button className="cmd ml-auto">{v.command('refresh_sources')} →</button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="rounded-xl border border-border bg-card px-[18px] py-10 text-center text-sm text-muted-foreground">{t('src.empty')}</div>
      ) : ok > 0 ? (
        <div className="mt-4 flex items-center gap-2 rounded-xl border border-border bg-card px-4 py-3 text-[13px] text-muted-foreground shadow-card">
          <Check size={16} style={{ color: 'var(--ok)' }} />
          {t('src.okFmt', { n: ok })}
        </div>
      ) : null}
    </>
  )
}
