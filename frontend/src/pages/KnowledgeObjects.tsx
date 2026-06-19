import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { X } from 'lucide-react'
import ForceGraph2D from 'react-force-graph-2d'
import { fetchKnowledgeGraph, type KnowledgeGraph, type KnowledgeGraphNode } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { useVocab } from '@/lib/vocab'
import { PageSkeleton } from '@/components/Skeleton'
import { useFocusTrap } from '@/lib/useFocusTrap'

// Object-type → node color (stays within the Blue DNA palette).
const OBJ_COLOR: Record<string, string> = {
  answer_card: '#185ee0',
  policy_rule: '#30a46c',
  known_issue_page: '#e5484d',
  troubleshooting_flow: '#f76808',
  escalation_route: '#e8930c',
}
// Evidence source-type → node color.
const EV_COLOR: Record<string, string> = {
  help_center: '#185ee0',
  internal_sop: '#30a46c',
  release_note: '#e8930c',
  incident_update: '#e5484d',
  resolved_ticket: '#7b828f',
  chat_transcript: '#aab0bd',
}
const C_AUD = '#7b828f'
// Edge styling per relationship kind.
const EDGE_STYLE: Record<string, { color: string; width: number; dashed?: boolean }> = {
  cites: { color: 'rgba(24,94,224,0.35)', width: 1 },
  serves: { color: 'rgba(123,130,143,0.28)', width: 1, dashed: true },
  escalates_to: { color: 'rgba(231,72,77,0.5)', width: 2 },
}

type GNode = {
  id: string
  kind: 'object' | 'evidence' | 'audience'
  name: string
  r: number
  color: string
  node?: KnowledgeGraphNode
  x?: number
  y?: number
}

export default function KnowledgeObjects() {
  const { t, i18n } = useTranslation()
  const [data, setData] = useState<KnowledgeGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()

  const wrapRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  const [w, setW] = useState(0)
  const H = 540

  const load = () => {
    setLoading(true)
    setError(null)
    fetchKnowledgeGraph().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
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

  const openObject = (id: string) =>
    setSearchParams((p) => { const n = new URLSearchParams(p); n.set('object', id); return n })
  const closeObject = () =>
    setSearchParams((p) => { const n = new URLSearchParams(p); n.delete('object'); return n }, { replace: true })

  const graph = useMemo(() => {
    if (!data) return { nodes: [] as GNode[], links: [] as { source: string; target: string; kind: string }[] }
    const nodes: GNode[] = data.nodes.map((n) => {
      if (n.kind === 'object') {
        return { id: n.id, kind: 'object', name: n.label, r: 9, color: OBJ_COLOR[n.object_type ?? ''] ?? '#185ee0', node: n }
      }
      if (n.kind === 'evidence') {
        return { id: n.id, kind: 'evidence', name: n.label, r: 6, color: EV_COLOR[n.source_type ?? ''] ?? '#aab0bd', node: n }
      }
      return { id: n.id, kind: 'audience', name: n.visibility === 'external' ? 'EXT' : 'INT', r: 5, color: C_AUD, node: n }
    })
    const links = data.edges.map((e) => ({ source: e.source, target: e.target, kind: e.kind }))
    return { nodes, links }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, i18n.language])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const selectedId = searchParams.get('object')
  const selected = selectedId ? data.nodes.find((n) => n.id === selectedId && n.kind === 'object') ?? null : null

  const drawNode = (node: any, ctx: CanvasRenderingContext2D, scale: number) => {
    const r = node.r ?? 5
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, 2 * Math.PI)
    if (node.kind === 'audience') {
      ctx.fillStyle = '#ffffff'; ctx.fill()
      ctx.lineWidth = 2 / scale; ctx.strokeStyle = node.color; ctx.stroke()
    } else {
      ctx.fillStyle = node.color; ctx.fill()
      if (node.kind === 'object') { ctx.lineWidth = 2 / scale; ctx.strokeStyle = '#ffffff'; ctx.stroke() }
    }
    const fontSize = (node.kind === 'object' ? 11 : 10) / scale
    ctx.font = `${node.kind === 'object' ? 600 : 400} ${fontSize}px Inter, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillStyle = node.kind === 'object' ? '#1a1d24' : node.kind === 'audience' ? node.color : '#7b828f'
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
        <Legend color="#185ee0" ring label={t('kg.object')} extra={t('kg.objectNote')} />
        <Legend color="#30a46c" label={t('kg.evidence')} />
        <Legend color={C_AUD} hollow label={t('kg.audience')} />
        <span className="ml-auto font-mono text-[11px] text-faint">{t('kg.hint')}</span>
      </div>

      <div ref={wrapRef} className="overflow-hidden rounded-xl border border-border bg-card shadow-soft" style={{ height: H }}>
        {w > 0 && (
          <ForceGraph2D
            ref={fgRef}
            width={w}
            height={H}
            graphData={graph}
            backgroundColor="rgba(0,0,0,0)"
            nodeLabel="name"
            nodeRelSize={5}
            linkColor={(l: any) => EDGE_STYLE[l.kind]?.color ?? 'rgba(123,130,143,0.22)'}
            linkWidth={(l: any) => EDGE_STYLE[l.kind]?.width ?? 1}
            linkLineDash={(l: any) => (EDGE_STYLE[l.kind]?.dashed ? [4, 3] : null)}
            cooldownTicks={120}
            onEngineStop={() => fgRef.current?.zoomToFit(400, 60)}
            nodeCanvasObject={drawNode}
            nodePointerAreaPaint={drawHit}
            onNodeClick={(node: any) => { if (node.kind === 'object' && node.node) openObject(node.node.id) }}
          />
        )}
      </div>

      {selected && <Drawer node={selected} edges={data.edges} nodes={data.nodes} onClose={closeObject} />}
    </>
  )
}

function Legend({ color, label, ring, hollow, extra }: { color: string; label: string; ring?: boolean; hollow?: boolean; extra?: string }) {
  return (
    <span className="flex items-center gap-2 text-[12.5px] text-muted-foreground">
      <span className="h-3 w-3 rounded-full" style={hollow ? { border: `2px solid ${color}`, background: '#fff' } : { background: color, boxShadow: ring ? '0 0 0 1.5px #fff inset' : undefined }} />
      {label}
      {extra && <span className="font-mono text-[10px] text-faint">{extra}</span>}
    </span>
  )
}

function Drawer({ node, edges, nodes, onClose }: { node: KnowledgeGraphNode; edges: KnowledgeGraph['edges']; nodes: KnowledgeGraphNode[]; onClose: () => void }) {
  const { t } = useTranslation()
  const v = useVocab()
  const ref = useRef<HTMLElement>(null)
  useFocusTrap(ref, true, onClose)
  // Resolve this object's neighbours via its edges (both directions).
  const neighbourIds = new Set<string>()
  for (const e of edges) {
    if (e.source === node.id) neighbourIds.add(e.target)
    if (e.target === node.id) neighbourIds.add(e.source)
  }
  const neighbours = nodes.filter((n) => neighbourIds.has(n.id))
  const citedEvidence = neighbours.filter((n) => n.kind === 'evidence')
  const audiences = neighbours.filter((n) => n.kind === 'audience')
  const linkedObjects = neighbours.filter((n) => n.kind === 'object')
  const LC: Record<string, string> = { published: 'chip', in_review: 'chip-high', draft: 'chip-medium' }
  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/25" onClick={onClose} />
      <aside ref={ref} role="dialog" aria-modal="true" aria-labelledby="ko-drawer-title" tabIndex={-1} className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l border-border bg-card p-5 shadow-soft outline-none">
        <div className="flex items-center gap-2">
          <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{v.objectType(node.object_type ?? '')}</span>
          <span className={`chip ${LC[node.lifecycle_state ?? ''] ?? 'chip'}`}>{node.lifecycle_state}</span>
          <button className="ml-auto flex h-8 w-8 items-center justify-center rounded-full border border-border text-muted-foreground hover:bg-muted" aria-label={t('detail.close')} onClick={onClose}><X size={15} /></button>
        </div>
        <h2 id="ko-drawer-title" className="mt-3 text-lg font-bold leading-tight">{node.label}</h2>
        <div className="mt-1 font-mono text-[11px] text-faint">{node.id}</div>
        <Section label={t('detail.summary')}>
          <p className="text-sm leading-relaxed text-muted-foreground">{node.summary}</p>
        </Section>
        <Section label={t('detail.evidence')}>
          {citedEvidence.length ? (
            <ul className="space-y-2">
              {citedEvidence.map((e) => (
                <li key={e.id} className="flex items-start gap-2">
                  <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: EV_COLOR[e.source_type ?? ''] ?? '#aab0bd' }} />
                  <div>
                    <div className="text-sm font-medium">{e.label}</div>
                    <div className="font-mono text-[10px] text-faint">{e.source_type} · {e.freshness} · {e.source_ref}</div>
                  </div>
                </li>
              ))}
            </ul>
          ) : <p className="text-sm text-faint">{t('state.empty')}</p>}
        </Section>
        <Section label={t('detail.audiences')}>
          {audiences.length ? (
            <div className="flex flex-wrap gap-1.5">
              {audiences.map((a) => <span key={a.id} className="chip">{v.visibility(a.visibility ?? '')}</span>)}
            </div>
          ) : <p className="text-sm text-faint">{t('state.empty')}</p>}
        </Section>
        {linkedObjects.length > 0 && (
          <Section label={t('detail.linkedObjects')}>
            <div className="flex flex-wrap gap-1.5">
              {linkedObjects.map((o) => <span key={o.id} className="chip">{o.label}</span>)}
            </div>
          </Section>
        )}
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
