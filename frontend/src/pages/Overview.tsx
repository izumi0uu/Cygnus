import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ListTodo, Bell, Users, Share2, Database } from 'lucide-react'
import { fetchCommandCenter, type CommandCenterSurface } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'
import { PieChart } from '@/components/charts/pie-chart'
import { PieSlice } from '@/components/charts/pie-slice'

const HEX: Record<string, string> = { urgent: '#e5484d', high: '#f76808', medium: '#e8930c', low: '#185ee0' }
const RANK: Record<string, number> = { urgent: 3, high: 2, medium: 1, low: 0 }

export default function Overview() {
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

  const d = useMemo(() => {
    if (!data) return null
    const stack = data.priority_stack
    const by = (u: string) => stack.filter((it) => it.urgency === u).length
    const surfCount: Record<string, number> = {}
    stack.forEach((it) => it.affected_surfaces.forEach((s) => (surfCount[s] = (surfCount[s] || 0) + 1)))
    const surfaces = Object.entries(surfCount).sort((a, b) => b[1] - a[1]).slice(0, 5)
    const top = [...stack].sort((a, b) => (RANK[b.urgency] ?? 0) - (RANK[a.urgency] ?? 0)).slice(0, 4)
    const pie = (['urgent', 'high', 'medium', 'low'] as const)
      .map((u) => ({ label: t(`urgency.${u}`), value: by(u), color: HEX[u] }))
      .filter((p) => p.value > 0)
    return {
      total: stack.length,
      urgent: by('urgent'),
      ownerGaps: data.situation_frame.owner_gaps,
      surfacesTotal: data.situation_frame.affected_surfaces?.length ?? 0,
      watched: new Set(stack.map((it) => it.object_ref)).size,
      surfaces,
      surfMax: surfaces[0]?.[1] ?? 1,
      top,
      pie,
    }
  }, [data, t])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data || !d) return null
  const sf = data.situation_frame

  const tiles = [
    { icon: ListTodo, n: d.total, label: t('overview.statRisks') },
    { icon: Bell, n: d.urgent, label: t('frame.urgent'), tint: HEX.urgent },
    { icon: Users, n: d.ownerGaps, label: t('frame.ownerGaps'), tint: HEX.high },
    { icon: Share2, n: d.surfacesTotal, label: t('queue.statSurfaces') },
    { icon: Database, n: d.watched, label: t('overview.statWatched') },
  ]

  return (
    <>
      {/* hero — tinted briefing banner */}
      <section
        className="relative mb-4 overflow-hidden rounded-xl border border-border p-5 pl-[22px] shadow-soft"
        style={{ background: 'linear-gradient(110deg, color-mix(in srgb, var(--accent) 55%, var(--card)), var(--card) 60%)' }}
      >
        <span className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
        <div className="flex items-start gap-4">
          <span className="chip chip-urgent mt-0.5 shrink-0">{t('frame.label')}</span>
          <div className="min-w-0">
            <h2 className="text-[19px] font-bold leading-tight">{data.headline}</h2>
            <p className="mt-1.5 max-w-[80ch] text-[13px] leading-relaxed text-muted-foreground">{sf.primary_tension}</p>
          </div>
          <div className="ml-auto hidden shrink-0 gap-5 sm:flex">
            <div><div className="font-mono text-2xl font-bold" style={{ color: HEX.urgent }}>{sf.urgent_items}</div><div className="font-mono text-[10px] uppercase text-muted-foreground">{t('frame.urgent')}</div></div>
            <div><div className="font-mono text-2xl font-bold" style={{ color: HEX.high }}>{sf.owner_gaps}</div><div className="font-mono text-[10px] uppercase text-muted-foreground">{t('frame.ownerGaps')}</div></div>
          </div>
        </div>
      </section>

      {/* stat tiles */}
      <div className="mb-4 flex flex-wrap gap-3">
        {tiles.map((tl) => (
          <div key={tl.label} className="min-w-[130px] flex-1 rounded-xl border border-border bg-card p-4 shadow-card transition-transform hover:-translate-y-px">
            <div
              className="mb-2.5 flex h-[30px] w-[30px] items-center justify-center rounded-lg"
              style={{ background: tl.tint ? `color-mix(in srgb, ${tl.tint} 10%, transparent)` : 'var(--muted)', color: tl.tint ?? 'var(--muted-foreground)' }}
            >
              <tl.icon size={16} />
            </div>
            <div className="font-mono text-[26px] font-bold tracking-tight" style={tl.tint ? { color: tl.tint } : undefined}>{tl.n}</div>
            <div className="mt-0.5 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">{tl.label}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* left: risk composition donut + surfaces bars */}
        <div className="rounded-xl border border-border bg-card shadow-soft">
          <div className="px-4 pt-3.5"><div className="text-[13px] font-bold">{t('overview.composition')}</div><div className="text-[11px] text-faint">{t('overview.byUrgency')}</div></div>
          <div className="flex items-center gap-3 px-5 pb-5 pt-4">
            <div className="relative shrink-0" style={{ width: 140, height: 140 }}>
              <PieChart data={d.pie} size={140} innerRadius={46} cornerRadius={3} padAngle={0.04}>
                {d.pie.map((_, i) => <PieSlice key={i} index={i} />)}
              </PieChart>
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="font-mono text-[26px] font-bold leading-none">{d.total}</span>
                <span className="font-mono text-[11px] text-muted-foreground">{t('overview.risks')}</span>
              </div>
            </div>
            <div className="flex-1">
              {d.pie.map((p) => (
                <div key={p.label} className="flex items-center gap-2 border-b border-dashed border-border py-1.5 text-[12.5px] last:border-b-0">
                  <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
                  {p.label}
                  <span className="ml-auto font-mono font-bold">{p.value}</span>
                  <span className="w-[42px] text-right font-mono text-[11px] text-faint">{Math.round((p.value / d.total) * 100)}%</span>
                </div>
              ))}
            </div>
          </div>
          <div className="border-t border-border px-5 pb-4 pt-3.5">
            <div className="flex items-baseline"><div className="text-[13px] font-bold">{t('overview.surfaces')}</div><Link to="/console/audience" className="ml-auto font-mono text-[11px] font-semibold text-primary">{t('overview.view')}</Link></div>
            <div className="mt-2.5 flex flex-col gap-2.5">
              {d.surfaces.map(([s, c]) => (
                <div key={s} className="flex items-center gap-2.5 text-[12.5px]">
                  <span className="w-[84px] shrink-0 text-muted-foreground">{v.surface(s)}</span>
                  <span className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                    <span className="block h-full rounded-full" style={{ width: `${(c / d.surfMax) * 100}%`, background: 'linear-gradient(90deg, var(--primary), #4f86ec)' }} />
                  </span>
                  <span className="w-[18px] text-right font-mono text-[11px] text-muted-foreground">{c}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* right: top risks + recovery ghost */}
        <div className="flex flex-col rounded-xl border border-border bg-card shadow-soft">
          <div className="flex items-baseline px-4 pt-3.5"><div className="text-[13px] font-bold">{t('overview.top')}</div><Link to="/console/queue" className="ml-auto font-mono text-[11px] font-semibold text-primary">{t('overview.viewQueue')}</Link></div>
          <div className="mt-1.5">
            {d.top.map((it, i) => (
              <div key={it.risk_id} className="flex items-start gap-2.5 border-b border-border px-4 py-3 transition-colors last:border-b-0 hover:bg-muted">
                <span className="mt-0.5 w-3.5 shrink-0 font-mono text-[11px] text-faint">{String(i + 1).padStart(2, '0')}</span>
                <div className="min-w-0">
                  <div className="text-[13px] font-semibold leading-snug">{it.title}</div>
                  <div className="mt-1 flex items-center gap-1.5">
                    <span className="h-2 w-2 rounded-full" style={{ background: HEX[it.urgency] }} />
                    <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{v.riskType(it.risk_type)}</span>
                    <CmdButton command={it.primary_command} />
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-auto border-t border-border px-5 pb-4 pt-3.5">
            <div className="flex items-baseline"><div className="text-[13px] font-bold">{t('overview.recovery')}</div><span className="ml-auto font-mono text-[11px] text-faint">{t('overview.pending')}</span></div>
            <div className="relative mt-2.5 flex h-[90px] items-center justify-center overflow-hidden rounded-lg bg-muted">
              <svg width="100%" height="90" viewBox="0 0 400 90" preserveAspectRatio="none" className="absolute inset-0">
                <defs>
                  <linearGradient id="recoveryFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="var(--primary)" stopOpacity="0.16" />
                    <stop offset="100%" stopColor="var(--primary)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path d="M0,70 60,60 120,64 180,48 240,52 300,34 360,38 400,24 L400,90 L0,90 Z" fill="url(#recoveryFill)" />
                <polyline points="0,70 60,60 120,64 180,48 240,52 300,34 360,38 400,24" fill="none" stroke="var(--faint)" strokeWidth="2" strokeDasharray="5 5" opacity="0.55" />
              </svg>
              <span className="z-10 font-mono text-[11px] uppercase tracking-wide text-faint">{t('overview.pendingNote')}</span>
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
