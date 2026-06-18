import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchCommandCenter, type CommandCenterSurface } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'

const HEAT: Record<string, string> = { urgent: 'chip-urgent', high: 'chip-high', medium: 'chip-medium', low: 'chip' }

// Source/evidence integrity = the source_blindness risks, reframed as a health list.
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
  const gaps = rows.filter((it) => it.owner_state === 'unassigned').length
  const surfaces = new Set(rows.flatMap((it) => it.affected_surfaces)).size

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={rows.length} label={t('src.statSources')} dot="var(--urgent)" />
        <Stat n={urgent} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={gaps} label={t('frame.ownerGaps')} dot="var(--high)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
        <div className="grid grid-cols-[200px_1fr_170px_120px_140px] gap-3.5 border-b border-border px-[18px] py-2.5 font-mono text-[10px] uppercase tracking-[1px] text-faint">
          <span>{t('src.thObject')}</span>
          <span>{t('src.thWhy')}</span>
          <span>{t('src.thSurf')}</span>
          <span>{t('src.thOwner')}</span>
          <span>{t('src.thAct')}</span>
        </div>
        {rows.map((it) => (
          <div key={it.risk_id} className="grid grid-cols-[200px_1fr_170px_120px_140px] items-center gap-3.5 border-b border-border px-[18px] py-[14px] last:border-b-0">
            <span className="min-w-0">
              <span className={`chip ${HEAT[it.urgency]}`}>{t(`urgency.${it.urgency}`)}</span>
              <div className="mt-1.5 font-mono text-[12px] text-foreground">{it.object_ref}</div>
              <div className="font-mono text-[10px] text-muted-foreground">{v.objectType(it.object_type)}</div>
            </span>
            <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{it.why_now_summary}</span>
            <span className="flex flex-wrap gap-1.5">
              {it.affected_surfaces.map((s) => <span key={s} className="chip">{v.surface(s)}</span>)}
            </span>
            <span>
              {it.owner_state === 'unassigned' ? (
                <span className="chip chip-gap">{t('owner.gap')}</span>
              ) : (
                <span className="font-mono text-[11.5px] text-muted-foreground">@{it.queue_owner}</span>
              )}
            </span>
            <span><button className="cmd">{v.command('refresh_sources')} →</button></span>
          </div>
        ))}
        {rows.length === 0 && <div className="px-[18px] py-10 text-center text-sm text-muted-foreground">{t('src.empty')}</div>}
      </div>
    </>
  )
}
