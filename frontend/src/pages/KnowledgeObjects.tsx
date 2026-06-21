import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { X } from 'lucide-react'
import ForceGraph2D from 'react-force-graph-2d'
import { fetchKnowledgeGraph, fetchTraceability, type KnowledgeGraph, type KnowledgeGraphNode, type TraceabilitySurface } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { useVocab } from '@/lib/vocab'
import { useTheme } from '@/lib/theme'
import { usePublishAction } from '@/lib/publishAction'
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
  const { resolvedTheme } = useTheme()
  const [data, setData] = useState<KnowledgeGraph | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()

  const wrapRef = useRef<HTMLDivElement>(null)
  const fgRef = useRef<any>(null)
  const [w, setW] = useState(0)
  const H = 540

  // Canvas can't read CSS variables directly; resolve the theme-dependent fill/stroke/text
  // colors from :root each time the resolved theme changes.
  const cv = useMemo(() => {
    const styles = getComputedStyle(document.documentElement)
    const get = (name: string) => styles.getPropertyValue(name).trim()
    return {
      card: get('--card') || '#ffffff',
      foreground: get('--foreground') || '#1a1d24',
      faint: get('--faint') || '#7b828f',
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedTheme])

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
      <div className="bp-panel p-4">
        <div className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
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
      ctx.fillStyle = cv.card; ctx.fill()
      ctx.lineWidth = 2 / scale; ctx.strokeStyle = node.color; ctx.stroke()
    } else {
      ctx.fillStyle = node.color; ctx.fill()
      if (node.kind === 'object') { ctx.lineWidth = 2 / scale; ctx.strokeStyle = cv.card; ctx.stroke() }
    }
    const fontSize = (node.kind === 'object' ? 11 : 10) / scale
    ctx.font = `${node.kind === 'object' ? 600 : 400} ${fontSize}px Inter, sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    ctx.fillStyle = node.kind === 'object' ? cv.foreground : node.kind === 'audience' ? node.color : cv.faint
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

      <div ref={wrapRef} className="bp-panel overflow-hidden" style={{ height: H }}>
        {w > 0 && (
          <ForceGraph2D
            key={resolvedTheme}
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
    <span className="flex items-center gap-2 font-mono text-[12.5px] text-muted-foreground">
      <span className="h-2.5 w-2.5 rotate-45" style={hollow ? { border: `2px solid ${color}`, background: 'var(--card)' } : { background: color, boxShadow: ring ? `0 0 0 1.5px var(--card) inset` : undefined }} />
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
  const LC: Record<string, string> = { published: 'bp-tol-ok', in_review: 'bp-tol-high', draft: 'bp-tol-flat' }
  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/25" onClick={onClose} />
      <aside ref={ref} role="dialog" aria-modal="true" aria-labelledby="ko-drawer-title" tabIndex={-1} className="bp-panel fixed right-0 top-0 z-50 flex h-full w-full max-w-[440px] flex-col overflow-y-auto p-5 outline-none">
        <div className="flex items-center gap-2">
          <span className="bp-tol bp-tol-flat">{v.objectType(node.object_type ?? '')}</span>
          <span className={`bp-tol ${LC[node.lifecycle_state ?? ''] ?? 'bp-tol-flat'}`}>{node.lifecycle_state}</span>
          <button className="ml-auto flex h-8 w-8 items-center justify-center bp-panel text-muted-foreground hover:bg-muted" aria-label={t('detail.close')} onClick={onClose}><X size={15} /></button>
        </div>
        <h2 id="ko-drawer-title" className="mt-3 font-mono text-lg font-bold leading-tight">{node.label}</h2>
        <div className="mt-1 font-mono text-[11px] text-faint">{node.id}</div>
        <Section label={t('detail.summary')}>
          <p className="font-mono text-[13px] leading-relaxed text-muted-foreground">{node.summary}</p>
        </Section>
        <Section label={t('detail.evidence')}>
          {citedEvidence.length ? (
            <ul className="space-y-2">
              {citedEvidence.map((e) => (
                <li key={e.id} className="flex items-start gap-2">
                  <span className="mt-1 h-2 w-2 shrink-0 rotate-45" style={{ background: EV_COLOR[e.source_type ?? ''] ?? '#aab0bd' }} />
                  <div>
                    <div className="font-mono text-sm font-medium">{e.label}</div>
                    <div className="font-mono text-[10px] text-faint">{e.source_type} · {e.freshness} · {e.source_ref}</div>
                  </div>
                </li>
              ))}
            </ul>
          ) : <p className="font-mono text-sm text-faint">{t('state.empty')}</p>}
        </Section>
        <Section label={t('detail.audiences')}>
          {audiences.length ? (
            <div className="flex flex-wrap gap-1.5">
              {audiences.map((a) => <span key={a.id} className="bp-tol bp-tol-flat">{v.visibility(a.visibility ?? '')}</span>)}
            </div>
          ) : <p className="font-mono text-sm text-faint">{t('state.empty')}</p>}
        </Section>
        {linkedObjects.length > 0 && (
          <Section label={t('detail.linkedObjects')}>
            <div className="flex flex-wrap gap-1.5">
              {linkedObjects.map((o) => <span key={o.id} className="bp-tol bp-tol-flat">{o.label}</span>)}
            </div>
          </Section>
        )}
        <TraceabilitySection objectId={node.id} />
      </aside>
    </>
  )
}

function TraceabilitySection({ objectId }: { objectId: string }) {
  const { t } = useTranslation()
  const v = useVocab()
  const { last: lastPublishAction } = usePublishAction()
  const [trace, setTrace] = useState<TraceabilitySurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchTraceability(objectId)
      .then(setTrace)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [objectId])

  const FRESH_COLOR: Record<string, string> = {
    fresh: 'var(--ok)',
    stale: 'var(--urgent)',
    unknown: 'var(--medium)',
  }
  const FRESH_TOL: Record<string, string> = {
    fresh: 'bp-tol-ok',
    stale: 'bp-tol-urgent',
    unknown: 'bp-tol-flat',
  }

  return (
    <Section label={t('trace.chain')}>
      {loading && <p className="font-mono text-sm text-faint">…</p>}
      {error && <p className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>{error}</p>}
      {trace && !loading && !error && (
        <div className="space-y-3">
          {/* freshness rollup + blind spots */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="bp-label-inline">{t('trace.freshness')}</span>
            <span className={`bp-tol ${FRESH_TOL[trace.trace.freshness] ?? 'bp-tol-flat'}`} style={{ color: FRESH_COLOR[trace.trace.freshness] ?? 'var(--faint)' }}>
              {trace.trace.freshness}
            </span>
          </div>
          {trace.trace.blind_spots.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="bp-label-inline">{t('trace.blindSpots')}</span>
              {trace.trace.blind_spots.map((b) => (
                <span key={b} className="bp-tol bp-tol-urgent">{b}</span>
              ))}
            </div>
          )}

          {/* what-if projection from the last APPLY on this object.
              persisted:false — the executor ran, but the fixture store did not
              change, so this is a projection of what the action WOULD do, not a
              claim that the trace changed. Tagged explicitly so it never reads
              as durable post-publish state. */}
          {lastPublishAction && lastPublishAction.objectRef === objectId && (
            <WhatIfProjection
              actionKey={lastPublishAction.result.selected_action}
              opened={lastPublishAction.result.opened_bindings}
              removed={lastPublishAction.result.removed_bindings}
              held={lastPublishAction.result.held_bindings}
              persisted={lastPublishAction.result.persisted}
            />
          )}

          {/* the evidence → source chain */}
          {trace.trace.evidence_refs.length === 0 ? (
            <p className="font-mono text-sm text-faint">{t('trace.noEvidence')}</p>
          ) : (
            <ul className="space-y-2">
              {trace.trace.evidence_refs.map((ref) => (
                <li key={ref.evidence_id} className="flex items-start gap-2">
                  <span className="mt-1 h-2 w-2 shrink-0 rotate-45" style={{ background: FRESH_COLOR[ref.freshness] ?? 'var(--faint)' }} />
                  <div className="min-w-0">
                    <div className="font-mono text-sm font-medium">{ref.title}</div>
                    <div className="font-mono text-[10px] text-faint">
                      {v.surface(ref.source_type)} · {ref.freshness} · {t('trace.sourceRef')}: {ref.source_ref}
                    </div>
                    <div className="mt-0.5 font-mono text-[10px] leading-relaxed text-muted-foreground">{t('trace.excerpt')}: {ref.excerpt_ref}</div>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* publish targets + review history */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="bp-label-inline">{t('trace.publishTargets')}</span>
            {trace.object.publish_targets.length > 0 ? (
              trace.object.publish_targets.map((c) => <span key={c} className="bp-tol bp-tol-flat">{v.surface(c)}</span>)
            ) : <span className="font-mono text-[11px] text-faint">{t('trace.none')}</span>}
          </div>
          {trace.trace.review_history_summary.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="bp-label-inline">{t('trace.reviewHistory')}</span>
              {trace.trace.review_history_summary.map((h, i) => (
                <span key={i} className="bp-tol bp-tol-flat">{h.stage}: {h.status}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </Section>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="bp-dim mt-5 pt-4">
      <div className="mb-2 bp-label">{label}</div>
      {children}
    </div>
  )
}

// Post-apply what-if projection. The apply ran (opened/removed/held bindings
// are real executor output) but persisted:false — the fixture store did not
// change. So this is labelled PROJECTION, never "published". When there is
// nothing to project (no bindings moved), we still render the stamp so the
// user sees the apply was a no-op on bindings, not silently swallowed.
function WhatIfProjection({
  actionKey,
  opened,
  removed,
  held,
  persisted,
}: {
  actionKey: string
  opened: { audience_label: string; channel: string }[]
  removed: { audience_label: string; channel: string }[]
  held: { audience_label: string; channel: string }[]
  persisted: boolean
}) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div className="bp-panel px-3 py-2.5">
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span className="bp-stamp" style={{ color: 'var(--high)', borderColor: 'color-mix(in srgb, var(--high) 45%, transparent)' }}>
          {t('trace.projection')}
        </span>
        <span className="bp-label-inline">{v.command(actionKey)}</span>
        <span className="bp-label-inline" style={{ color: 'var(--medium)', opacity: 0.7 }}>
          {persisted ? t('trace.persisted') : t('trace.notPersisted')}
        </span>
      </div>
      <ProjectionGroup label={t('trace.wouldOpen')} bindings={opened} tol="bp-tol-high" dot="var(--high)" />
      <ProjectionGroup label={t('trace.wouldRemove')} bindings={removed} tol="bp-tol-flat" dot="var(--medium)" />
      <ProjectionGroup label={t('trace.wouldHold')} bindings={held} tol="bp-tol-urgent" dot="var(--urgent)" />
      <p className="mt-2 font-mono text-[10px] leading-relaxed text-faint">{t('trace.projectionNote')}</p>
    </div>
  )
}

function ProjectionGroup({
  label,
  bindings,
  tol,
  dot,
}: {
  label: string
  bindings: { audience_label: string; channel: string }[]
  tol: string
  dot: string
}) {
  const v = useVocab()
  return (
    <div className="mb-1.5 last:mb-0">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-widest text-faint">
        {label} · {bindings.length}
      </div>
      {bindings.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {bindings.map((b, i) => (
            <span key={i} className={`bp-tol ${tol}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: dot }} />
              {b.audience_label} · {v.surface(b.channel)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
