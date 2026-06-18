import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import ForceGraph2D from 'react-force-graph-2d'
import { fetchCommandCenter, type CommandCenterSurface, type PriorityItem } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { useVocab } from '@/lib/vocab'

// three is heavy → only loaded when the user switches to 3D
const ForceGraph3D = lazy(() => import('react-force-graph-3d'))

const HEX: Record<string, string> = { urgent: '#e5484d', high: '#f76808', medium: '#e8930c', low: '#185ee0' }
const RANK: Record<string, number> = { urgent: 3, high: 2, medium: 1, low: 0 }
const OBJR: Record<string, number> = { urgent: 11, high: 9, medium: 8, low: 7 }
const C_AUD = '#7b828f'
const C_SURF = '#aab0bd'

type GNode = {
  id: string
  kind: 'object' | 'audience' | 'surface'
  name: string
  r: number
  color: string
  objType?: string
  urgency?: string
  item?: PriorityItem
  x?: number
  y?: number
}

export default function KnowledgeObjects() {
  const { t, i18n } = useTranslation()
  const v = useVocab()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<PriorityItem | null>(null)
  const [mode, setMode] = useState<'2d' | '3d'>('2d')

  const wrapRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  const [w, setW] = useState(0)
  const H = 540

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(load, [])
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth))
    ro.observe(el)
    setW(el.clientWidth)
    return () => ro.disconnect()
  }, [data])
  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setSelected(null) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected])

  const graph = useMemo(() => {
    if (!data) return { nodes: [] as GNode[], links: [] as { source: string; target: string }[] }
    const nodes = new Map<string, GNode>()
    const links: { source: string; target: string }[] = []
    const seen = new Set<string>()
    const objMost = new Map<string, PriorityItem>()
    for (const it of data.priority_stack) {
      const c = objMost.get(it.object_ref)
      if (!c || (RANK[it.urgency] ?? 0) > (RANK[c.urgency] ?? 0)) objMost.set(it.object_ref, it)
    }
    for (const it of data.priority_stack) {
      const oid = 'o:' + it.object_ref
      if (!nodes.has(oid)) {
        const top = objMost.get(it.object_ref)!
        nodes.set(oid, { id: oid, kind: 'object', name: it.object_ref, r: OBJR[top.urgency] ?? 5, color: HEX[top.urgency] ?? '#185ee0', objType: it.object_type, urgency: top.urgency, item: top })
      }
      it.audience_labels.forEach((lab, idx) => {
        const aid = 'a:' + lab
        if (!nodes.has(aid)) {
          const a = it.affected_audiences[idx]
          nodes.set(aid, { id: aid, kind: 'audience', name: a ? v.audienceFacets(a).join('·') || v.visibility(a.visibility) : lab, r: 6, color: C_AUD })
        }
        const k = oid + '>' + aid
        if (!seen.has(k)) { seen.add(k); links.push({ source: oid, target: aid }) }
      })
      it.affected_surfaces.forEach((s) => {
        const sid = 's:' + s
        if (!nodes.has(sid)) nodes.set(sid, { id: sid, kind: 'surface', name: v.surface(s), r: 5, color: C_SURF })
        const k = oid + '>' + sid
        if (!seen.has(k)) { seen.add(k); links.push({ source: oid, target: sid }) }
      })
    }
    return { nodes: [...nodes.values()], links }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, i18n.language])

  if (loading) return <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const drawNode = (node: any, ctx: CanvasRenderingContext2D, scale: number) => {
    const r = node.r ?? 5
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    ctx.fillStyle = node.color
    ctx.fill()
    if (node.kind === 'object') {
      ctx.lineWidth = 2 / scale
      ctx.strokeStyle = '#ffffff'
      ctx.stroke()
    }
    const fontSize = 11 / scale
    ctx.font = `${node.kind === 'object' ? 600 : 400} ${fontSize}px Inter, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillStyle = node.kind === 'object' ? '#1a1d24' : '#7b828f'
    ctx.fillText(node.name, node.x, node.y + r + 2 / scale)
  }
  const drawHit = (node: any, color: string, ctx: CanvasRenderingContext2D) => {
    ctx.beginPath()
    ctx.arc(node.x, node.y, (node.r ?? 5) + 2, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
  }

  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-4">
        <Legend color={HEX.urgent} ring label={t('kg.object')} extra={t('kg.objectNote')} />
        <Legend color={C_AUD} label={t('kg.audience')} />
        <Legend color={C_SURF} label={t('kg.surface')} />
        <div className="ml-auto flex items-center gap-3">
          <div className="flex rounded-full border border-border p-0.5 text-[12px] font-semibold">
            <button onClick={() => setMode('2d')} className={mode === '2d' ? 'rounded-full bg-accent px-3 py-1 text-primary' : 'px-3 py-1 text-muted-foreground'}>2D</button>
            <button onClick={() => setMode('3d')} className={mode === '3d' ? 'rounded-full bg-accent px-3 py-1 text-primary' : 'px-3 py-1 text-muted-foreground'}>3D</button>
          </div>
          <span className="font-mono text-[11px] text-faint">{t('kg.hint')}</span>
        </div>
      </div>

      <div ref={wrapRef} className="overflow-hidden rounded-xl border border-border bg-card shadow-soft" style={{ height: H }}>
        {w > 0 && mode === '2d' && (
          <ForceGraph2D
            ref={fgRef}
            width={w}
            height={H}
            graphData={graph}
            backgroundColor="rgba(0,0,0,0)"
            nodeLabel="name"
            nodeRelSize={6}
            linkColor={() => 'rgba(123,130,143,0.22)'}
            linkWidth={1}
            warmupTicks={120}
            cooldownTicks={0}
            onEngineStop={() => fgRef.current?.zoomToFit(0, 70)}
            nodeCanvasObject={drawNode}
            nodePointerAreaPaint={drawHit}
            onNodeClick={(node: any) => { if (node.kind === 'object' && node.item) setSelected(node.item) }}
          />
        )}
        {w > 0 && mode === '3d' && (
          <Suspense fallback={<div className="flex h-full items-center justify-center font-mono text-sm text-muted-foreground">{t('state.loading')}</div>}>
            <ForceGraph3D
              ref={fgRef}
              width={w}
              height={H}
              graphData={graph}
              backgroundColor="#f6f8fc"
              nodeLabel="name"
              nodeColor={(n: any) => n.color}
              nodeVal={(n: any) => n.r}
              nodeOpacity={0.95}
              linkColor={() => 'rgba(123,130,143,0.4)'}
              linkOpacity={0.5}
              warmupTicks={120}
              cooldownTicks={0}
              onEngineStop={() => fgRef.current?.zoomToFit(0, 90)}
              onNodeClick={(node: any) => { if (node.kind === 'object' && node.item) setSelected(node.item) }}
            />
          </Suspense>
        )}
      </div>

      {selected && <Drawer item={selected} onClose={() => setSelected(null)} />}
    </>
  )
}

function Legend({ color, label, ring, extra }: { color: string; label: string; ring?: boolean; extra?: string }) {
  return (
    <span className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
      <span className="h-3 w-3 rounded-full" style={{ background: color, boxShadow: ring ? '0 0 0 1.5px #fff inset' : undefined }} />
      {label}
      {extra && <span className="font-mono text-[10px] text-faint">{extra}</span>}
    </span>
  )
}

function Drawer({ item, onClose }: { item: PriorityItem; onClose: () => void }) {
  const { t } = useTranslation()
  const v = useVocab()
  const HEATCHIP: Record<string, string> = { urgent: 'chip-urgent', high: 'chip-high', medium: 'chip-medium', low: 'chip' }
  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/25" onClick={onClose} />
      <aside role="dialog" aria-modal="true" className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l border-border bg-card p-5 shadow-soft">
        <div className="flex items-center gap-2">
          <span className={`chip ${HEATCHIP[item.urgency]}`}>{t(`urgency.${item.urgency}`)}</span>
          <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{v.objectType(item.object_type)}</span>
          <button className="ml-auto flex h-8 w-8 items-center justify-center rounded-full border border-border text-muted-foreground hover:bg-muted" aria-label={t('detail.close')} onClick={onClose}><X size={15} /></button>
        </div>
        <h2 className="mt-3 text-lg font-bold leading-tight">{item.title}</h2>
        <div className="mt-1 font-mono text-[11px] text-faint">{item.object_ref} · {v.riskType(item.risk_type)}</div>
        <Section label={t('detail.whyNow')}><p className="text-sm leading-relaxed text-muted-foreground">{item.why_now_summary}</p></Section>
        <Section label={t('detail.audiences')}>
          <div className="flex flex-wrap gap-1.5">{item.affected_audiences.map((a, i) => <span key={i} className="chip">{v.audienceSegment(a)}</span>)}</div>
        </Section>
        <Section label={t('detail.surfaces')}>
          <div className="flex flex-wrap gap-1.5">{item.affected_surfaces.map((s) => <span key={s} className="chip">{v.surface(s)}</span>)}</div>
        </Section>
        <Section label={t('detail.commands')}>
          <div className="flex flex-wrap gap-2">{item.command_actions.map((c) => <button key={c} className="cmd">{v.command(c)}</button>)}</div>
          <p className="mt-2 font-mono text-[10px] leading-relaxed text-faint">{t('detail.commandNote')}</p>
        </Section>
      </aside>
    </>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 border-t border-border pt-4">
      <div className="mb-2 font-mono text-xs font-semibold uppercase tracking-widest text-muted-foreground">{label}</div>
      {children}
    </div>
  )
}
