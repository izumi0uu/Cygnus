import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { SlidersHorizontal, Plus, X } from 'lucide-react'
import {
  fetchReviewIntake,
  type ReviewIntakeSurface,
  type ReviewIntakeBundle,
  type PriorityItem,
  type ReviewAssignmentCommandResult,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/Segmented'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'
import { useFocusTrap } from '@/lib/useFocusTrap'
import { PlotterPanel } from '@/components/PlotterPanel'
import { ObservationBanner } from '@/components/ObservationBanner'
import { SourceFailureCard } from '@/components/SourceFailureCard'

const HEAT: Record<string, string> = { urgent: 'bp-tol-urgent', high: 'bp-tol-high', medium: 'bp-tol-high', low: 'bp-tol-flat' }
const DOT: Record<string, string> = { urgent: 'var(--urgent)', high: 'var(--high)', medium: 'var(--medium)', low: 'var(--faint)' }

type Filter = 'all' | 'urgent' | 'unassigned'

export default function ReviewQueue() {
  const { t } = useTranslation()
  const v = useVocab()
  const [data, setData] = useState<ReviewIntakeSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [searchParams, setSearchParams] = useSearchParams()

  const load = (background = false) => {
    // Background re-reads (after a durable queue command) must not flip
    // the page into the skeleton or tear down the open drawer/modal; on
    // failure the stale surface stays and the durable receipt still carries
    // the authoritative server response.
    if (!background) {
      setLoading(true)
      setError(null)
    }
    fetchReviewIntake()
      .then(setData)
      .catch((e) => {
        if (!background) setError(String(e))
      })
      .finally(() => setLoading(false))
  }
  useEffect(() => {
    fetchReviewIntake().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }, [])

  // bundle lookup by object_ref (proposal_id === object_ref)
  const bundlesByRef = useMemo(() => {
    const m = new Map<string, ReviewIntakeBundle>()
    data?.bundles.forEach((b) => m.set(b.proposal_id, b))
    return m
  }, [data])

  const openRisk = (id: string) =>
    setSearchParams((p) => { const n = new URLSearchParams(p); n.set('risk', id); return n })
  // Stable identity: the drawer's focus trap re-runs (stealing focus back to
  // the drawer) whenever this changes — including after background reloads.
  const closeRisk = useCallback(
    () => setSearchParams((p) => { const n = new URLSearchParams(p); n.delete('risk'); return n }, { replace: true }),
    [setSearchParams],
  )

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="bp-panel p-4">
        <div className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={() => load()}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const home = data.review_home
  const sf = home.situation_frame
  const selectedId = searchParams.get('risk')
  const sourceFailures = data.source_blindness_surface?.source_observations ?? []
  const selected = selectedId ? home.priority_stack.find((it) => it.risk_id === selectedId) ?? null : null
  const rows = home.priority_stack.filter((it) =>
    filter === 'all' ? true : filter === 'urgent' ? it.urgency === 'urgent' : it.owner_state === 'unassigned',
  )

  return (
    <>
      <ObservationBanner observation={home.observation} />
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={home.priority_stack.length} label={t('observation.completeRisks')} />
        <Stat n={sourceFailures.length} label={t('observation.sourceFacts')} dot="var(--high)" />
        <Stat n={sf.urgent_items} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={sf.owner_gaps} label={t('frame.ownerGaps')} dot="var(--high)" />
        <Stat n={sf.affected_surfaces?.length ?? 0} label={t('queue.statSurfaces')} />
      </div>

      {sourceFailures.length > 0 && (
        <section className="mb-5" aria-labelledby="review-source-facts-heading">
          <div id="review-source-facts-heading" className="mb-2 bp-label">{t('observation.sourceFacts')}</div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sourceFailures.map((failure) => <SourceFailureCard key={failure.source_id} failure={failure} />)}
          </div>
        </section>
      )}

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

      <div className="overflow-hidden bp-panel">
        <div className="grid grid-cols-[96px_1fr_140px_140px_150px] gap-3.5 bp-dim px-[18px] py-2.5 font-mono text-[10px] uppercase tracking-[1px] text-faint">
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
            onClick={() => openRisk(it.risk_id)}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openRisk(it.risk_id) } }}
            className="bp-anno grid cursor-pointer grid-cols-[96px_1fr_140px_140px_150px] items-center gap-3.5 px-[18px] py-[15px]"
          >
            <span>
              <span className={`bp-tol ${HEAT[it.urgency]}`}>
                <span className="h-1.5 w-1.5 rotate-45" style={{ background: DOT[it.urgency] }} />
                {t(`urgency.${it.urgency}`)}
              </span>
            </span>
            <div className="min-w-0">
              <div className="font-mono text-sm font-semibold leading-snug">{it.title}</div>
              <div className="mt-0.5 line-clamp-1 font-mono text-xs text-muted-foreground">{it.why_now_summary}</div>
              <div className="mt-1.5">
                <span className="bp-tol bp-tol-flat">{v.riskType(it.risk_type)}</span>
              </div>
            </div>
            <span className="font-mono text-[11px] text-muted-foreground">
              {t('queue.scopeFmt', { a: it.audience_labels.length, s: it.affected_surfaces.length })}
            </span>
            <span>
              {it.owner_state === 'unassigned' ? (
                <span className="bp-tol bp-tol-high">{t('owner.gap')}</span>
              ) : it.owner_state === 'escalated' ? (
                <span className="bp-tol bp-tol-urgent">{t('owner.escalatedFmt', { owner: it.queue_owner ?? '—' })}</span>
              ) : (
                <span className="font-mono text-[11.5px] text-muted-foreground">@{it.queue_owner}</span>
              )}
            </span>
            <span>
              <button className="bp-cmd" onClick={(e) => { e.stopPropagation(); openRisk(it.risk_id) }}>
                {it.primary_command === 'create_draft' ? t('commands.createDraft') : v.command(it.primary_command)} →
              </button>
            </span>
          </div>
        ))}
        {rows.length === 0 && (
          <div className="px-[18px] py-10 text-center font-mono text-sm text-muted-foreground">
            {home.observation.state === 'ready' ? t('state.empty') : t('observation.queueEmptyPartial')}
          </div>
        )}
      </div>

      {selected && (
        <Drawer
          key={selected.risk_id}
          item={selected}
          bundle={bundlesByRef.get(selected.object_ref) ?? null}
          onClose={closeRisk}
          onChanged={() => load(true)}
        />
      )}
    </>
  )
}

function Drawer({
  item,
  bundle,
  onClose,
  onChanged,
}: {
  item: PriorityItem
  bundle: ReviewIntakeBundle | null
  onClose: () => void
  /** Re-read the queue after a durable assignment or ticket-draft mutation. */
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const ref = useRef<HTMLElement>(null)
  useFocusTrap(ref, true, onClose)
  // The durable receipt of the last assignment command executed from this
  // drawer — rendered as a drawing stamp until another risk is opened. It is
  // populated only from a real server response, never optimistically.
  const [receipt, setReceipt] = useState<ReviewAssignmentCommandResult | null>(null)
  const handleExecuted = (result: ReviewAssignmentCommandResult) => {
    setReceipt(result)
    onChanged()
  }
  return (
    <>
      <div className="fixed inset-0 z-40 bg-foreground/25" onClick={onClose} />
      <PlotterPanel
        as="aside"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="rq-drawer-title"
        tabIndex={-1}
        replayKey={item.risk_id}
        lapDuration={0.4}
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l-0 p-5 outline-none"
      >
        <div className="flex items-center gap-2">
          <span className={`bp-tol ${HEAT[item.urgency]}`}>{t(`urgency.${item.urgency}`)}</span>
          <span className="bp-tol bp-tol-flat">{v.riskType(item.risk_type)}</span>
          <button
            className="ml-auto flex h-8 w-8 items-center justify-center bp-panel text-muted-foreground hover:bg-muted"
            aria-label={t('detail.close')}
            onClick={onClose}
          >
            <X size={15} />
          </button>
        </div>
        <h2 id="rq-drawer-title" className="mt-3 font-mono text-lg font-bold leading-tight">{item.title}</h2>
        <div className="mt-1 font-mono text-[11px] text-faint">{item.object_ref} · {v.objectType(item.object_type)}</div>

        <Section label={t('detail.whyNow')}>
          <p className="font-mono text-[13px] leading-relaxed text-muted-foreground">{item.why_now_summary}</p>
        </Section>
        {bundle && (
          <Section label={t('detail.intake')}>
            <div className="space-y-2.5">
              <div className="flex items-center gap-2 text-[12.5px]">
                <span className="font-mono text-[10px] uppercase text-faint">{t('detail.evidenceSufficiency')}</span>
                <span className={`bp-tol ${bundle.evidence_sufficiency === 'sufficient' ? 'bp-tol-ok' : 'bp-tol-high'}`}>{bundle.evidence_sufficiency}</span>
              </div>
              <div className="flex items-center gap-2 text-[12.5px]">
                <span className="font-mono text-[10px] uppercase text-faint">{t('detail.suggestedReviewOwner')}</span>
                <span className="font-mono text-[11.5px] text-muted-foreground">@{bundle.review_owner}</span>
              </div>
              {bundle.audience_notes.length > 0 && (
                <div>
                  <div className="mb-1 font-mono text-[10px] uppercase text-faint">{t('detail.audienceNotes')}</div>
                  <ul className="space-y-1">
                    {bundle.audience_notes.map((note, i) => (
                      <li key={i} className="font-mono text-[10.5px] leading-relaxed text-muted-foreground">{note}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Section>
        )}
        <Section label={t('detail.scope')}>
          <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wide text-faint">{t('detail.audiences')}</div>
          <div className="flex flex-wrap gap-1.5">{item.affected_audiences.map((a, i) => <span key={i} className="bp-tol bp-tol-flat">{v.audienceSegment(a)}</span>)}</div>
          <div className="mb-1.5 mt-3 font-mono text-[10px] uppercase tracking-wide text-faint">{t('detail.surfaces')}</div>
          <div className="flex flex-wrap gap-1.5">{item.affected_surfaces.map((s) => <span key={s} className="bp-tol bp-tol-flat">{v.surface(s)}</span>)}</div>
        </Section>
        <Section label={t('detail.owner')}>
          {item.owner_state === 'unassigned' ? (
            <span className="bp-tol bp-tol-high">{t('detail.unassigned')}</span>
          ) : item.owner_state === 'escalated' ? (
            <span className="bp-tol bp-tol-urgent">{t('owner.escalatedFmt', { owner: item.queue_owner ?? '—' })}</span>
          ) : (
            <span className="bp-tol bp-tol-flat">@{item.queue_owner}</span>
          )}
          {item.assignment_trace_ref && (
            <div className="mt-1.5 font-mono text-[10px] text-faint">
              {item.assignment_trace_ref} · {t('assign.version')} {item.assignment_version}
            </div>
          )}
          {receipt && (
            <div
              className="mt-3 border px-3 py-2.5"
              style={{
                borderColor: 'color-mix(in srgb, var(--ok) 40%, transparent)',
                background: 'color-mix(in srgb, var(--ok) 6%, transparent)',
              }}
            >
              <div className="flex items-center gap-2">
                <span className="bp-stamp" style={{ color: 'var(--ok)' }}>{t('assign.persisted')}</span>
                {receipt.replayed && <span className="bp-tol bp-tol-flat">{t('assign.replayed')}</span>}
              </div>
              <dl className="mt-2 space-y-1 font-mono text-[10.5px] leading-relaxed text-muted-foreground">
                <div className="flex justify-between gap-3">
                  <dt className="text-faint">{t('assign.transition')}</dt>
                  <dd>
                    {receipt.event.from_state ? v.assignmentState(receipt.event.from_state) : '—'} →{' '}
                    {v.assignmentState(receipt.event.to_state)}
                  </dd>
                </div>
                {receipt.assignment.owner_ref && (
                  <div className="flex justify-between gap-3">
                    <dt className="text-faint">{t('assign.owner')}</dt>
                    <dd>@{receipt.assignment.owner_ref}</dd>
                  </div>
                )}
                <div className="flex justify-between gap-3">
                  <dt className="text-faint">{t('assign.version')}</dt>
                  <dd>
                    {receipt.assignment.version} · #{receipt.event.sequence}
                  </dd>
                </div>
                <div className="flex justify-between gap-3">
                  <dt className="text-faint">{t('assign.trace')}</dt>
                  <dd className="break-all text-right">{receipt.assignment.trace_ref}</dd>
                </div>
              </dl>
            </div>
          )}
        </Section>
        <Section label={t('detail.commands')}>
          <div className="flex flex-wrap gap-2">
            {item.command_actions.map((c) => (
              <CmdButton
                key={c}
                command={c}
                objectRef={item.object_ref}
                assignment={{
                  signalRef: item.signal_ref,
                  version: item.assignment_version,
                  owner: item.queue_owner,
                  state: item.owner_state,
                  onExecuted: handleExecuted,
                  onRefresh: onChanged,
                }}
                draftPromotion={c === 'create_draft' ? {
                  signalRef: item.signal_ref,
                  objectRef: item.object_ref,
                  assignmentVersion: item.assignment_version,
                  onRefresh: onChanged,
                } : undefined}
              />
            ))}
          </div>
          <p className="mt-2 font-mono text-[10px] leading-relaxed text-faint">{t('detail.commandNote')}</p>
        </Section>
      </PlotterPanel>
    </>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="bp-dim mt-5 pt-4">
      <div className="mb-2 bp-label">{label}</div>
      {children}
    </div>
  )
}
