import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { RotateCw, X } from 'lucide-react'
import {
  fetchReviewIntake,
  type ReviewIntakeSurface,
  type ReviewIntakeBundle,
  type PriorityItem,
  type ReviewAssignmentCommandResult,
} from '@/lib/api'
import { Segmented } from '@/components/Segmented'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'
import { useFocusTrap } from '@/lib/useFocusTrap'
import { PlotterPanel } from '@/components/PlotterPanel'
import { ObservationBanner } from '@/components/ObservationBanner'
import { SourceFailureCard } from '@/components/SourceFailureCard'
import { RequestErrorState } from '@/components/RequestState'

const HEAT: Record<string, string> = { urgent: 'bp-tol-urgent', high: 'bp-tol-high', medium: 'bp-tol-high', low: 'bp-tol-flat' }
const DOT: Record<string, string> = { urgent: 'var(--urgent)', high: 'var(--high)', medium: 'var(--medium)', low: 'var(--faint)' }
const EVIDENCE_LABEL_KEY: Record<string, string> = {
  sufficient: 'queue.evidence.sufficient',
  partial: 'queue.evidence.partial',
  insufficient: 'queue.evidence.insufficient',
}

type Filter = 'all' | 'urgent' | 'unassigned'

export default function ReviewQueue() {
  const { t } = useTranslation()
  const [data, setData] = useState<ReviewIntakeSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState<unknown>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const filterParam = searchParams.get('filter')
  const filter: Filter = filterParam === 'urgent' || filterParam === 'unassigned' ? filterParam : 'all'
  const setFilter = (nextFilter: Filter) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      if (nextFilter === 'all') next.delete('filter')
      else next.set('filter', nextFilter)
      return next
    }, { replace: true })
  }
  const requestKey = useRef(0)

  const load = useCallback((background = false) => {
    const key = ++requestKey.current
    if (background) {
      setRefreshing(true)
      setRefreshError(null)
    } else {
      setLoading(true)
      setError(null)
    }
    fetchReviewIntake()
      .then((next) => {
        if (key === requestKey.current) setData(next)
      })
      .catch((nextError: unknown) => {
        if (key !== requestKey.current) return
        if (background) setRefreshError(nextError)
        else setError(nextError)
      })
      .finally(() => {
        if (key !== requestKey.current) return
        if (background) setRefreshing(false)
        else setLoading(false)
      })
  }, [])

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) load() })
    return () => {
      active = false
      requestKey.current += 1
    }
  }, [load])

  // Durable evidence and audience-impact projections are keyed by object ref;
  // rendering code does not derive either fact from counts or local heuristics.
  const bundlesByRef = useMemo(() => {
    const next = new Map<string, ReviewIntakeBundle>()
    data?.bundles.forEach((bundle) => next.set(bundle.proposal_id, bundle))
    return next
  }, [data])
  const pressureByRef = useMemo(() => {
    const next = new Map<string, NonNullable<ReviewIntakeSurface['pressure_surface']>['pressure_lines'][number]>()
    data?.pressure_surface?.pressure_lines.forEach((line) => next.set(line.proposal_ref, line))
    return next
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
  if (error) return <RequestErrorState error={error} onRetry={() => load()} />
  if (!data) return null

  const home = data.review_home
  const sf = home.situation_frame
  const selectedId = searchParams.get('risk')
  const sourceFailures = data.source_blindness_surface?.source_observations ?? []
  const selected = selectedId
    ? home.priority_stack.find((item) => item.risk_id === selectedId || item.object_ref === selectedId || item.signal_ref === selectedId) ?? null
    : null
  const rows = home.priority_stack.filter((it) =>
    filter === 'all' ? true : filter === 'urgent' ? it.urgency === 'urgent' : it.owner_state === 'unassigned',
  )
  const emptyCopyKey = home.observation.state === 'ready'
    ? `queue.empty.${filter}`
    : `queue.emptyPartial.${filter}`

  return (
    <div className="space-y-4">
      <header className="bp-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="bp-label">{t('queue.subtitle')}</div>
            <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('queue.title')}</h1>
            <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">{sf.briefing_note}</p>
          </div>
          {refreshing ? (
            <span role="status" className="bp-tol bp-tol-flat inline-flex items-center gap-1.5">
              <RotateCw aria-hidden="true" size={12} className="animate-spin" /> {t('queue.refreshing')}
            </span>
          ) : null}
        </div>
      </header>

      {refreshError ? <RequestErrorState error={refreshError} onRetry={() => load(true)} compact stale /> : null}
      <ObservationBanner observation={home.observation} />

      <div className="flex flex-wrap gap-2.5">
        <Stat n={home.priority_stack.length} label={t('observation.completeRisks')} />
        <Stat n={sourceFailures.length} label={t('observation.sourceFacts')} dot="var(--high)" />
        <Stat n={sf.urgent_items} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={sf.owner_gaps} label={t('frame.ownerGaps')} dot="var(--high)" />
        <Stat n={sf.affected_surfaces?.length ?? 0} label={t('queue.statSurfaces')} />
      </div>

      {sourceFailures.length > 0 ? (
        <section aria-labelledby="review-source-facts-heading">
          <h2 id="review-source-facts-heading" className="mb-2 bp-label">{t('observation.sourceFacts')}</h2>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {sourceFailures.map((failure) => <SourceFailureCard key={failure.source_id} failure={failure} />)}
          </div>
        </section>
      ) : null}

      <section aria-labelledby="review-list-heading">
        <div className="mb-3 flex flex-wrap items-center gap-3">
          <h2 id="review-list-heading" className="sr-only">{t('queue.listHeading')}</h2>
          <Segmented
            value={filter}
            onChange={setFilter}
            ariaLabel={t('queue.filterLabel')}
            options={[
              { value: 'all', label: t('queue.all') },
              { value: 'urgent', label: t('queue.urgent') },
              { value: 'unassigned', label: t('queue.unassigned') },
            ]}
          />
        </div>

        <div className="overflow-hidden bp-panel">
          <div className="hidden gap-4 bp-dim px-4 py-2.5 font-mono text-xs uppercase tracking-wide text-faint xl:grid xl:grid-cols-[6rem_minmax(0,1.2fr)_minmax(0,1fr)_8rem_8rem_9rem]">
            <span>{t('queue.thUrgency')}</span>
            <span>{t('queue.thRisk')}</span>
            <span>{t('queue.thEvidenceImpact')}</span>
            <span>{t('queue.thScope')}</span>
            <span>{t('queue.thOwner')}</span>
            <span>{t('queue.thCommand')}</span>
          </div>
          {rows.map((item) => {
            const bundle = bundlesByRef.get(item.object_ref)
            const pressure = pressureByRef.get(item.object_ref)
            return (
              <QueueRow
                key={item.risk_id}
                item={item}
                evidenceSufficiency={bundle?.evidence_sufficiency ?? pressure?.evidence_sufficiency ?? null}
                audienceImpact={pressure?.impact_summary ?? bundle?.audience_notes[0] ?? null}
                onOpen={() => openRisk(item.risk_id)}
              />
            )
          })}
          {rows.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <h3 className="font-mono text-sm font-bold">{t(emptyCopyKey)}</h3>
              <p className="mx-auto mt-2 max-w-xl font-mono text-xs leading-relaxed text-muted-foreground">{t(`queue.emptyHint.${filter}`)}</p>
            </div>
          ) : null}
        </div>
      </section>

      {selected ? (
        <Drawer
          key={selected.risk_id}
          item={selected}
          bundle={bundlesByRef.get(selected.object_ref) ?? null}
          refreshError={refreshError}
          onClose={closeRisk}
          onChanged={() => load(true)}
        />
      ) : null}
    </div>
  )
}

function QueueRow({
  item,
  evidenceSufficiency,
  audienceImpact,
  onOpen,
}: {
  item: PriorityItem
  evidenceSufficiency: string | null
  audienceImpact: string | null
  onOpen: () => void
}) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <article className="bp-anno grid cursor-default gap-3 px-4 py-4 xl:grid-cols-[6rem_minmax(0,1.2fr)_minmax(0,1fr)_8rem_8rem_9rem] xl:items-center">
      <div>
        <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('queue.thUrgency')}</span>
        <span className={`bp-tol ${HEAT[item.urgency]}`}>
          <span aria-hidden="true" className="h-1.5 w-1.5 rotate-45" style={{ background: DOT[item.urgency] }} />
          {t(`urgency.${item.urgency}`)}
        </span>
      </div>
      <div className="min-w-0">
        <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('queue.thRisk')}</span>
        <button
          type="button"
          onClick={onOpen}
          className="block min-h-11 w-full text-left font-mono text-sm font-semibold leading-snug underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={t('queue.openRisk', { title: item.title })}
        >
          {item.title}
        </button>
        <p className="mt-1 line-clamp-2 font-mono text-xs leading-relaxed text-muted-foreground">{item.why_now_summary}</p>
        <span className="mt-2 inline-flex bp-tol bp-tol-flat">{v.riskType(item.risk_type)}</span>
      </div>
      <div className="min-w-0">
        <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('queue.thEvidenceImpact')}</span>
        {evidenceSufficiency && EVIDENCE_LABEL_KEY[evidenceSufficiency] ? (
          <span className={`bp-tol ${evidenceSufficiency === 'sufficient' ? 'bp-tol-ok' : 'bp-tol-high'}`}>{t(EVIDENCE_LABEL_KEY[evidenceSufficiency])}</span>
        ) : <span className="bp-tol bp-tol-flat">{t('queue.notObserved')}</span>}
        <p className="mt-2 line-clamp-2 font-mono text-xs leading-relaxed text-muted-foreground">
          {audienceImpact ?? t('queue.noAudienceImpact')}
        </p>
      </div>
      <div>
        <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('queue.thScope')}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {t('queue.scopeFmt', { a: item.audience_labels.length, s: item.affected_surfaces.length })}
        </span>
      </div>
      <div>
        <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('queue.thOwner')}</span>
        {item.owner_state === 'unassigned' ? (
          <span className="bp-tol bp-tol-high">{t('owner.gap')}</span>
        ) : item.owner_state === 'escalated' ? (
          <span className="bp-tol bp-tol-urgent">{t('owner.escalatedFmt', { owner: item.queue_owner ?? '—' })}</span>
        ) : (
          <span className="font-mono text-xs text-muted-foreground">@{item.queue_owner}</span>
        )}
      </div>
      <div>
        <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('queue.thCommand')}</span>
        <button type="button" className="bp-cmd min-h-11" onClick={onOpen}>
          {item.primary_command === 'create_draft' ? t('commands.createDraft') : v.command(item.primary_command)} →
        </button>
      </div>
    </article>
  )
}

function Drawer({
  item,
  bundle,
  refreshError,
  onClose,
  onChanged,
}: {
  item: PriorityItem
  bundle: ReviewIntakeBundle | null
  refreshError: unknown
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
        aria-describedby="rq-drawer-summary"
        tabIndex={-1}
        replayKey={item.risk_id}
        lapDuration={0.4}
        className="thin-scroll fixed inset-y-0 right-0 z-50 flex h-dvh w-full max-w-[440px] flex-col overflow-y-auto border-l-0 p-4 outline-none sm:p-5"
      >
        <div className="flex items-center gap-2">
          <span className={`bp-tol ${HEAT[item.urgency]}`}>{t(`urgency.${item.urgency}`)}</span>
          <span className="bp-tol bp-tol-flat">{v.riskType(item.risk_type)}</span>
          <button
            type="button"
            className="ml-auto flex h-11 w-11 items-center justify-center bp-panel text-muted-foreground hover:bg-muted"
            aria-label={t('detail.close')}
            onClick={onClose}
          >
            <X size={15} aria-hidden="true" />
          </button>
        </div>
        <h2 id="rq-drawer-title" className="mt-3 font-mono text-lg font-bold leading-tight">{item.title}</h2>
        <div className="mt-1 font-mono text-[11px] text-faint">{item.object_ref} · {v.objectType(item.object_type)}</div>
        {refreshError ? <RequestErrorState error={refreshError} onRetry={onChanged} compact stale /> : null}

        <Section label={t('detail.whyNow')}>
          <p id="rq-drawer-summary" className="font-mono text-[13px] leading-relaxed text-muted-foreground">{item.why_now_summary}</p>
        </Section>
        {bundle && (
          <Section label={t('detail.intake')}>
            <div className="space-y-2.5">
              <div className="flex items-center gap-2 text-[12.5px]">
                <span className="font-mono text-[10px] uppercase text-faint">{t('detail.evidenceSufficiency')}</span>
                <span className={`bp-tol ${bundle.evidence_sufficiency === 'sufficient' ? 'bp-tol-ok' : 'bp-tol-high'}`}>
                  {t(EVIDENCE_LABEL_KEY[bundle.evidence_sufficiency] ?? 'queue.notObserved')}
                </span>
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
      <h3 className="mb-2 bp-label">{label}</h3>
      {children}
    </div>
  )
}
