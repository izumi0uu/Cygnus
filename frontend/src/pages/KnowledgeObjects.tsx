import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchCommandCenter, type CommandCenterSurface, type PriorityItem } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/Segmented'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'

const HEAT: Record<string, string> = { urgent: 'chip-urgent', high: 'chip-high', medium: 'chip-medium', low: 'chip' }
const RANK: Record<string, number> = { urgent: 3, high: 2, medium: 1, low: 0 }

type Filter = 'all' | 'urgent' | 'unassigned'
type Obj = { ref: string; type: string; risk: PriorityItem }

// Distinct knowledge objects currently under governance attention, keyed by object_ref,
// surfaced with their most-urgent risk. Derived from the existing command-center payload.
function aggregate(data: CommandCenterSurface): Obj[] {
  const map = new Map<string, Obj>()
  for (const it of data.priority_stack) {
    const cur = map.get(it.object_ref)
    if (!cur || (RANK[it.urgency] ?? 0) > (RANK[cur.risk.urgency] ?? 0)) {
      map.set(it.object_ref, { ref: it.object_ref, type: it.object_type, risk: it })
    }
  }
  return [...map.values()].sort((a, b) => (RANK[b.risk.urgency] ?? 0) - (RANK[a.risk.urgency] ?? 0))
}

export default function KnowledgeObjects() {
  const { t } = useTranslation()
  const v = useVocab()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const objs = useMemo(() => (data ? aggregate(data) : []), [data])

  if (loading) return <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const types = new Set(objs.map((o) => o.type)).size
  const urgent = objs.filter((o) => o.risk.urgency === 'urgent').length
  const gaps = objs.filter((o) => o.risk.owner_state === 'unassigned').length
  const rows = objs.filter((o) =>
    filter === 'all' ? true : filter === 'urgent' ? o.risk.urgency === 'urgent' : o.risk.owner_state === 'unassigned',
  )

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={objs.length} label={t('obj.statObjects')} />
        <Stat n={types} label={t('obj.statTypes')} />
        <Stat n={urgent} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={gaps} label={t('frame.ownerGaps')} dot="var(--high)" />
      </div>

      <div className="mb-3.5 flex items-center gap-3">
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: t('queue.all') },
            { value: 'urgent', label: t('queue.urgent') },
            { value: 'unassigned', label: t('queue.unassigned') },
          ]}
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
        <div className="grid grid-cols-[160px_1fr_220px_140px_150px] gap-3.5 border-b border-border px-[18px] py-2.5 font-mono text-[10px] uppercase tracking-[1px] text-faint">
          <span>{t('obj.thType')}</span>
          <span>{t('obj.thRef')}</span>
          <span>{t('obj.thRisk')}</span>
          <span>{t('obj.thOwner')}</span>
          <span>{t('obj.thAct')}</span>
        </div>
        {rows.map((o) => (
          <div key={o.ref} className="grid grid-cols-[160px_1fr_220px_140px_150px] items-center gap-3.5 border-b border-border px-[18px] py-[14px] last:border-b-0">
            <span><span className="chip">{v.objectType(o.type)}</span></span>
            <span className="font-mono text-[12px] text-foreground">{o.ref}</span>
            <span className="flex items-center gap-1.5">
              <span className={`chip ${HEAT[o.risk.urgency]}`}>{t(`urgency.${o.risk.urgency}`)}</span>
              <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{v.riskType(o.risk.risk_type)}</span>
            </span>
            <span>
              {o.risk.owner_state === 'unassigned' ? (
                <span className="chip chip-gap">{t('owner.gap')}</span>
              ) : (
                <span className="font-mono text-[11.5px] text-muted-foreground">@{o.risk.queue_owner}</span>
              )}
            </span>
            <span><button className="cmd">{v.command(o.risk.primary_command)} →</button></span>
          </div>
        ))}
        {rows.length === 0 && <div className="px-[18px] py-10 text-center text-sm text-muted-foreground">{t('state.empty')}</div>}
      </div>
    </>
  )
}
