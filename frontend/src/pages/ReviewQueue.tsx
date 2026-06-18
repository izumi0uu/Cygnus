import { type ReactNode, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { SlidersHorizontal, Plus, X } from 'lucide-react'
import { fetchCommandCenter, type CommandCenterSurface, type PriorityItem } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/Segmented'
import { Stat } from '@/components/Stat'

const HEAT: Record<string, string> = { urgent: 'chip-urgent', high: 'chip-high', medium: 'chip-medium', low: 'chip' }
const DOT: Record<string, string> = { urgent: 'var(--urgent)', high: 'var(--high)', medium: 'var(--medium)', low: 'var(--faint)' }

type Filter = 'all' | 'urgent' | 'unassigned'

export default function ReviewQueue() {
  const { t } = useTranslation()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [selected, setSelected] = useState<PriorityItem | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(load, [])
  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelected(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected])

  if (loading) return <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const sf = data.situation_frame
  const rows = data.priority_stack.filter((it) =>
    filter === 'all' ? true : filter === 'urgent' ? it.urgency === 'urgent' : it.owner_state === 'unassigned',
  )

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={data.priority_stack.length} label={t('queue.statRisks')} />
        <Stat n={sf.urgent_items} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={sf.owner_gaps} label={t('frame.ownerGaps')} dot="var(--high)" />
        <Stat n={sf.affected_surfaces?.length ?? 0} label={t('queue.statSurfaces')} />
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
        <Button variant="ghost" size="sm" className="ml-auto"><SlidersHorizontal size={14} /> {t('queue.sort')}</Button>
        <Button size="sm"><Plus size={14} /> {t('queue.command')}</Button>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
        <div className="grid grid-cols-[96px_1fr_140px_140px_150px] gap-3.5 border-b border-border px-[18px] py-2.5 font-mono text-[10px] uppercase tracking-[1px] text-faint">
          <span>{t('queue.thUrgency')}</span>
          <span>{t('queue.thRisk')}</span>
          <span>{t('queue.thScope')}</span>
          <span>{t('queue.thOwner')}</span>
          <span>{t('queue.thCommand')}</span>
        </div>
        {rows.map((it) => (
          <div
            key={it.risk_id}
            role="button"
            tabIndex={0}
            onClick={() => setSelected(it)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(it) } }}
            className="grid cursor-pointer grid-cols-[96px_1fr_140px_140px_150px] items-center gap-3.5 border-b border-border px-[18px] py-[15px] transition-colors last:border-b-0 hover:bg-accent/50"
          >
            <span>
              <span className={`chip ${HEAT[it.urgency]}`}>
                <span className="h-1.5 w-1.5 rounded-full" style={{ background: DOT[it.urgency] }} />
                {t(`urgency.${it.urgency}`)}
              </span>
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold leading-snug">{it.title}</div>
              <div className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">{it.why_now_summary}</div>
              <div className="mt-1.5">
                <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{it.risk_type}</span>
              </div>
            </div>
            <span className="font-mono text-[11px] text-muted-foreground">
              {t('queue.scopeFmt', { a: it.audience_labels.length, s: it.affected_surfaces.length })}
            </span>
            <span>
              {it.owner_state === 'unassigned' ? (
                <span className="chip chip-gap">{t('owner.gap')}</span>
              ) : (
                <span className="font-mono text-[11.5px] text-muted-foreground">@{it.queue_owner}</span>
              )}
            </span>
            <span>
              <button className="cmd" onClick={(e) => { e.stopPropagation(); setSelected(it) }}>{it.primary_command} →</button>
            </span>
          </div>
        ))}
        {rows.length === 0 && <div className="px-[18px] py-10 text-center text-sm text-muted-foreground">{t('state.empty')}</div>}
      </div>

      {selected && <Drawer item={selected} onClose={() => setSelected(null)} />}
    </>
  )
}

function Drawer({ item, onClose }: { item: PriorityItem; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/25" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l border-border bg-card p-5 shadow-soft"
      >
        <div className="flex items-center gap-2">
          <span className={`chip ${HEAT[item.urgency]}`}>{t(`urgency.${item.urgency}`)}</span>
          <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{item.risk_type}</span>
          <button
            className="ml-auto flex h-8 w-8 items-center justify-center rounded-full border border-border text-muted-foreground hover:bg-muted"
            aria-label={t('detail.close')}
            onClick={onClose}
          >
            <X size={15} />
          </button>
        </div>
        <h2 className="mt-3 text-lg font-bold leading-tight">{item.title}</h2>
        <div className="mt-1 font-mono text-[11px] text-faint">{item.object_ref} · {item.object_type}</div>

        <Section label={t('detail.whyNow')}>
          <p className="text-sm leading-relaxed text-muted-foreground">{item.why_now_summary}</p>
        </Section>
        <Section label={t('detail.scope')}>
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-faint">{t('detail.audiences')}</div>
          <div className="flex flex-wrap gap-1.5">{item.audience_labels.map((a) => <span key={a} className="chip">{a}</span>)}</div>
          <div className="mb-1.5 mt-3 font-mono text-[10px] uppercase tracking-wide text-faint">{t('detail.surfaces')}</div>
          <div className="flex flex-wrap gap-1.5">{item.affected_surfaces.map((s) => <span key={s} className="chip">{s}</span>)}</div>
        </Section>
        <Section label={t('detail.owner')}>
          {item.owner_state === 'unassigned'
            ? <span className="chip chip-gap">{t('detail.unassigned')}</span>
            : <span className="chip">@{item.queue_owner}</span>}
        </Section>
        <Section label={t('detail.commands')}>
          <div className="flex flex-wrap gap-2">{item.command_actions.map((c) => <button key={c} className="cmd">{c}</button>)}</div>
          <p className="mt-2 font-mono text-[10px] leading-relaxed text-faint">{t('detail.commandNote')}</p>
        </Section>
      </aside>
    </>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="mt-5 border-t border-border pt-4">
      <div className="mb-2 font-mono text-xs font-semibold uppercase tracking-widest text-muted-foreground">{label}</div>
      {children}
    </div>
  )
}
