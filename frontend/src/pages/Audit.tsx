import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, TriangleAlert } from 'lucide-react'
import {
  fetchGovernanceAudit,
  fetchGovernanceAuditEvent,
  type GovernanceAuditEvent,
  type GovernanceAuditPage,
  type GovernanceAuditPhase,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { Segmented } from '@/components/Segmented'
import { ObservationBanner } from '@/components/ObservationBanner'
import { PageSkeleton } from '@/components/Skeleton'
import AdminDialog from '@/components/AdminDialog'
import { RequestErrorState } from '@/components/RequestState'
import { auditEventRoute, governedObjectRoute } from '@/lib/adminRoutes'

const PAGE_SIZE = 20

type PhaseFilter = GovernanceAuditPhase | 'all'
const PHASE_FILTERS: PhaseFilter[] = ['all', 'review', 'approval', 'publish', 'recovery']

// Phase lane marker colors — diamond leading each ledger row.
const PHASE_DOT: Record<GovernanceAuditPhase, string> = {
  review: 'var(--medium)',
  approval: 'var(--high)',
  publish: 'var(--ok)',
  recovery: 'var(--urgent)',
}

// One in-flight/resolved request per phase+page coordinate. Rendering only
// honors the request whose key matches the current coordinate, so a slow
// response for a stale phase/page can never overwrite newer state.
type RequestState = {
  key: string
  data: GovernanceAuditPage | null
  error: string | null
}
type DetailRequestState = {
  eventId: string
  data: GovernanceAuditEvent | null
  error: unknown
}
function compactLedgerTimestamp(value: string): string {
  return value
    .replace('T', ' ')
    .replace(/\.\d+(?=Z$|[+-]\d{2}:\d{2}$)/, '')
}

export default function Audit() {
  const { t } = useTranslation()
  const [phase, setPhase] = useState<PhaseFilter>('all')
  const [page, setPage] = useState(1)
  const [reloadTick, setReloadTick] = useState(0)
  const [request, setRequest] = useState<RequestState | null>(null)
  const [searchParams, setSearchParams] = useSearchParams()
  const [detailRequest, setDetailRequest] = useState<DetailRequestState | null>(null)
  const [detailReloadTick, setDetailReloadTick] = useState(0)

  const requestKey = `${phase}:${page}`
  const active = request?.key === requestKey ? request : null
  const data = active?.data ?? null
  const error = active?.error ?? null
  const loading = active === null

  useEffect(() => {
    let cancelled = false
    fetchGovernanceAudit(phase === 'all' ? undefined : phase, page, PAGE_SIZE)
      .then((d) => { if (!cancelled) setRequest({ key: requestKey, data: d, error: null }) })
      .catch((e) => { if (!cancelled) setRequest({ key: requestKey, data: null, error: String(e) }) })
    return () => { cancelled = true }
  }, [phase, page, reloadTick, requestKey])

  const selectedEventId = searchParams.get('event')
  useEffect(() => {
    if (!selectedEventId) return
    let cancelled = false
    fetchGovernanceAuditEvent(selectedEventId)
      .then((event) => {
        if (!cancelled) setDetailRequest({ eventId: selectedEventId, data: event, error: null })
      })
      .catch((nextError: unknown) => {
        if (!cancelled) setDetailRequest({ eventId: selectedEventId, data: null, error: nextError })
      })
    return () => { cancelled = true }
  }, [detailReloadTick, selectedEventId])

  // Phase filtering always restarts the ledger at page 1.
  const changePhase = (p: PhaseFilter) => {
    setPhase(p)
    setPage(1)
  }

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="bp-panel p-4">
        <div className="flex items-center gap-1.5 font-mono text-sm" style={{ color: 'var(--urgent)' }}><TriangleAlert size={15} aria-hidden="true" /> {t('state.error')}</div>
        <Button
          variant="ghost"
          className="mt-3"
          onClick={() => {
            setRequest(null)
            setReloadTick((n) => n + 1)
          }}
        >
          {t('state.retry')}
        </Button>
      </div>
    )
  if (!data) return null

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size))
  const canPrev = page > 1
  const canNext = page < totalPages

  return (
    <>
      <h1 className="sr-only">{t('nav.audit')}</h1>
      <ObservationBanner observation={data.observation} />

      <p className="mb-3 font-mono text-[12px] leading-relaxed text-muted-foreground">{t('audit.summary')}</p>

      {/* durable-truth strip: persisted only proves the ledger event committed */}
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <span
          className="bp-stamp"
          style={{ color: 'var(--ok)', borderColor: 'color-mix(in srgb, var(--ok) 45%, transparent)' }}
        >
          {t('audit.durable')}
        </span>
        <span className="font-mono text-[10px] leading-relaxed text-faint">{t('audit.persistedNote')}</span>
      </div>

      {/* stat row */}
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={data.total} label={t('audit.statEvents')} dot="var(--primary)" />
        <Stat n={data.items.length} label={t('audit.statShown')} />
        <Stat n={totalPages} label={t('audit.statPages')} />
      </div>

      {/* phase tabs */}
      <div className="mb-4">
        <Segmented
          options={PHASE_FILTERS.map((p) => ({ value: p, label: t(`audit.phase.${p}`) }))}
          value={phase}
          onChange={changePhase}
        />
      </div>

      {/* event ledger */}
      <div className="bp-panel overflow-hidden">
        <div className="flex flex-wrap items-baseline gap-2 px-4 pt-3.5">
          <div className="bp-label">{t('audit.ledger')}</div>
          <span className="ml-auto font-mono text-[11px] text-faint">
            {t('audit.pageFmt', { page: data.page, total: totalPages })} · {t('audit.totalFmt', { count: data.total })}
          </span>
        </div>
        {data.items.length === 0 ? (
          <div className="px-4 py-10 text-center">
            <div className="font-mono text-[13px] font-semibold">{t('audit.empty')}</div>
            <p className="mt-2 font-mono text-[11px] leading-relaxed text-faint">{t('audit.emptyNote')}</p>
          </div>
        ) : (
          <div className="mt-1.5">
            {data.items.map((event) => (
              <EventRow key={event.event_id} event={event} />
            ))}
          </div>
        )}
      </div>

      {/* bounded prev/next pagination */}
      <div className="bp-dim mt-5 flex items-center justify-between pt-4">
        <Button
          variant="ghost"
          size="sm"
          disabled={!canPrev}
          onClick={() => setPage((p) => Math.max(1, p - 1))}
        >
          <ArrowLeft size={14} />{t('audit.prev')}
        </Button>
        <span className="font-mono text-[11px] text-faint">
          {t('audit.pageFmt', { page, total: totalPages })}
        </span>
        <Button
          variant="ghost"
          size="sm"
          disabled={!canNext}
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
        >
          {t('audit.next')}<ArrowRight size={14} />
        </Button>
      </div>

      {selectedEventId ? (
        <AuditEventDetailDialog
          eventId={selectedEventId}
          request={detailRequest?.eventId === selectedEventId ? detailRequest : null}
          onRetry={() => setDetailReloadTick((value) => value + 1)}
          onClose={() => setSearchParams((current) => {
            const next = new URLSearchParams(current)
            next.delete('event')
            return next
          }, { replace: true })}
        />
      ) : null}
    </>
  )
}

function EventRow({ event }: { event: GovernanceAuditEvent }) {
  const { t } = useTranslation()
  const resource = event.resource
  // Primary resource label: first non-null of title/slug/object_ref; secondary
  // refs keep the remaining identifiers visible without inventing fields.
  const primary = resource.title ?? resource.slug ?? resource.object_ref ?? '—'
  const secondary = [resource.slug, resource.object_ref].filter(
    (r): r is string => r !== null && r !== primary,
  )
  const scope = resource.scope_id ? `${resource.scope_type} · ${resource.scope_id}` : resource.scope_type
  const actor = event.actor ? (event.actor.name ?? event.actor.actor_id) : '—'
  const detailEntries = Object.entries(event.details)
  // Preserve the recorded timezone while dropping only sub-second precision.
  const occurred = compactLedgerTimestamp(event.occurred_at)
  const recorded = compactLedgerTimestamp(event.recorded_at)

  return (
    <div className="bp-anno cursor-default !items-stretch py-3">
      <span className="bp-anno-idx">{String(event.sequence).padStart(2, '0')}</span>
      <div className="min-w-0 flex-1">
        {/* line 1 — phase lane + event + occurred time */}
        <div className="flex flex-wrap items-center gap-2">
          <span
            className="h-2 w-2 shrink-0 rotate-45"
            style={{ background: PHASE_DOT[event.phase] ?? 'var(--faint)' }}
          />
          <span className="bp-tol bp-tol-flat">{t(`audit.phase.${event.phase}`)}</span>
          <Link
            to={auditEventRoute(event.event_id)}
            className="font-mono text-[13px] font-semibold underline-offset-4 hover:text-primary hover:underline"
            aria-label={t('audit.openEvent', { event: t(`audit.event.${event.event_type}`, { defaultValue: event.event_type }) })}
          >
            {t(`audit.event.${event.event_type}`, { defaultValue: event.event_type })}
          </Link>
          <span className="ml-auto font-mono text-[11px] text-faint">{occurred}</span>
        </div>

        {/* line 2 — state transition + actor + scope */}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] text-muted-foreground">
          <span>
            <span className="text-faint">
              {event.from_state ? t(`audit.state.${event.from_state}`, { defaultValue: event.from_state }) : '—'}
            </span>
            {' → '}
            <span className="font-semibold text-foreground">
              {t(`audit.state.${event.to_state}`, { defaultValue: event.to_state })}
            </span>
          </span>
          <span>{t('audit.actor')}: {actor}</span>
          <span className="bp-tol bp-tol-flat">{scope}</span>
        </div>

        {/* line 3 — governed resource */}
        <div className="mt-1 flex flex-wrap items-baseline gap-x-2 font-mono text-[11.5px]">
          <span className="font-semibold">{primary}</span>
          {secondary.map((r) => (
            <span key={r} className="break-all text-faint">{r}</span>
          ))}
        </div>

        {/* line 4 — recorded reason (nullable stays honest) */}
        <p className="mt-1 font-mono text-[11.5px] leading-relaxed text-muted-foreground">
          {event.reason ?? <span className="text-faint">{t('audit.noReason')}</span>}
        </p>

        {/* line 5 — provenance + whitelisted details */}
        <div className="bp-dim mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 pt-2 font-mono text-[10px] text-faint">
          <span className="break-all">{t('audit.trace')}: {event.trace_ref}</span>
          <span>{t('audit.recorded')}: {recorded}</span>
          {detailEntries.length > 0 ? detailEntries.map(([k, v]) => (
            <span key={k} className="bp-tol bp-tol-flat max-w-full whitespace-normal break-all">
              {k}: {Array.isArray(v) ? v.join(' · ') : String(v)}
            </span>
          )) : (
            <span>{t('audit.noDetails')}</span>
          )}
        </div>
      </div>
    </div>
  )
}

function AuditEventDetailDialog({
  eventId,
  request,
  onRetry,
  onClose,
}: {
  eventId: string
  request: DetailRequestState | null
  onRetry: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const event = request?.data ?? null
  const resource = event?.resource

  return (
    <AdminDialog
      titleId="audit-event-detail-title"
      descriptionId="audit-event-detail-description"
      title={event ? t(`audit.event.${event.event_type}`, { defaultValue: event.event_type }) : t('audit.detailTitle')}
      description={t('audit.detailDescription', { id: eventId })}
      onClose={onClose}
    >
      {!request ? (
        <div className="mt-5 py-8 text-center font-mono text-sm text-muted-foreground" role="status">
          {t('audit.detailLoading')}
        </div>
      ) : request.error ? (
        <div className="mt-5">
          <RequestErrorState error={request.error} onRetry={onRetry} compact />
        </div>
      ) : event && resource ? (
        <div className="mt-5 space-y-4">
          <div className="grid gap-3 border border-border bg-muted p-3 font-mono text-[11px] sm:grid-cols-2">
            <DetailValue label={t('audit.phaseLabel')} value={t(`audit.phase.${event.phase}`)} />
            <DetailValue label={t('audit.occurred')} value={compactLedgerTimestamp(event.occurred_at)} />
            <DetailValue label={t('audit.transition')} value={`${event.from_state ?? '—'} → ${event.to_state}`} />
            <DetailValue label={t('audit.actor')} value={event.actor?.name ?? event.actor?.actor_id ?? '—'} />
            <DetailValue label={t('audit.scope')} value={resource.scope_id ? `${resource.scope_type} · ${resource.scope_id}` : resource.scope_type} />
            <DetailValue label={t('audit.draft')} value={event.draft_id} breakValue />
          </div>
          <section aria-labelledby="audit-event-resource-title" className="border border-border p-3">
            <h3 id="audit-event-resource-title" className="bp-label">{t('audit.resource')}</h3>
            <div className="mt-2 font-mono text-sm font-semibold">{resource.title ?? resource.slug ?? resource.object_ref ?? '—'}</div>
            {resource.object_ref ? (
              <Link to={governedObjectRoute(resource.object_ref)} className="mt-3 inline-flex min-h-11 items-center text-xs font-semibold text-primary underline-offset-4 hover:underline">
                {t('audit.openObject')}
              </Link>
            ) : null}
          </section>
          <section aria-labelledby="audit-event-reason-title" className="border border-border p-3">
            <h3 id="audit-event-reason-title" className="bp-label">{t('audit.reason')}</h3>
            <p className="mt-2 font-mono text-[11px] leading-relaxed text-muted-foreground">{event.reason ?? t('audit.noReason')}</p>
          </section>
          <section aria-labelledby="audit-event-trace-title" className="border border-border p-3">
            <h3 id="audit-event-trace-title" className="bp-label">{t('audit.trace')}</h3>
            <p className="mt-2 break-all font-mono text-[10px] text-muted-foreground">{event.trace_ref}</p>
            <dl className="mt-3 space-y-2">
              {Object.entries(event.details).map(([key, value]) => (
                <div key={key} className="grid gap-1 font-mono text-[10px] sm:grid-cols-[160px_1fr]">
                  <dt className="text-faint">{key}</dt>
                  <dd className="break-all text-foreground">{Array.isArray(value) ? value.join(' · ') : String(value)}</dd>
                </div>
              ))}
            </dl>
          </section>
        </div>
      ) : null}
    </AdminDialog>
  )
}

function DetailValue({ label, value, breakValue = false }: { label: string; value: string; breakValue?: boolean }) {
  return (
    <div>
      <div className="text-[9px] uppercase tracking-wide text-faint">{label}</div>
      <div className={`mt-1 text-foreground ${breakValue ? 'break-all' : ''}`}>{value}</div>
    </div>
  )
}
