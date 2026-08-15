import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Search } from 'lucide-react'
import {
  fetchPublishPropagation,
  type PublishPropagationSurface,
  type SurfacePropagationRecord,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'
import { ApiError } from '@/lib/authApi'
import { RequestErrorState } from '@/components/RequestState'

const STATUS_DOT: Record<string, string> = {
  synced: 'var(--ok)',
  pending: 'var(--medium)',
  failed: 'var(--urgent)',
  manual_action_required: 'var(--high)',
}
const STATUS_CHIP: Record<string, string> = {
  synced: 'bp-tol-ok',
  pending: 'bp-tol-high',
  failed: 'bp-tol-urgent',
  manual_action_required: 'bp-tol-high',
}
const STATUS_LANE_STYLE: Record<string, string> = {
  synced: 'var(--ok)',
  pending: 'var(--medium)',
  failed: 'var(--urgent)',
  manual_action_required: 'var(--high)',
}

export default function Propagation() {
  const { t } = useTranslation()
  const v = useVocab()
  const [searchParams, setSearchParams] = useSearchParams()
  const objectRef = searchParams.get('object_ref') || undefined
  const publicationId = searchParams.get('publication_id') || undefined
  const [lookupRef, setLookupRef] = useState(objectRef ?? '')
  const [data, setData] = useState<PublishPropagationSurface | null>(null)
  const [loading, setLoading] = useState(Boolean(objectRef || publicationId))
  const [error, setError] = useState<unknown>(null)
  const requestKey = useRef(0)

  const load = useCallback(() => {
    if (!objectRef && !publicationId) {
      requestKey.current += 1
      setLoading(false)
      setData(null)
      setError(null)
      return
    }
    const key = ++requestKey.current
    setLoading(true)
    setData(null)
    setError(null)
    fetchPublishPropagation(objectRef, publicationId)
      .then((next) => {
        if (key === requestKey.current) setData(next)
      })
      .catch((nextError: unknown) => {
        if (key === requestKey.current) setError(nextError)
      })
      .finally(() => {
        if (key === requestKey.current) setLoading(false)
      })
  }, [objectRef, publicationId])

  useEffect(() => {
    let active = true
    queueMicrotask(() => {
      if (!active) return
      setLookupRef(objectRef ?? '')
      load()
    })
    return () => {
      active = false
      requestKey.current += 1
    }
  }, [load, objectRef])

  // Prev/next walks objects, not publications: drop any publication_id so the
  // new object_ref resolves its own latest durable publication.
  const gotoObject = (ref: string) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('object_ref', ref)
      next.delete('publication_id')
      return next
    }, { replace: true })
  }

  const handleLookup = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const ref = lookupRef.trim()
    if (ref) gotoObject(ref)
  }

  const ledger = data?.propagation_ledger ?? null
  const summary = ledger?.summary ?? null
  const emptyLedgerError = error instanceof ApiError && error.status === 404

  return (
    <div className="space-y-4">
      <header className="bp-panel p-5">
        <div className="bp-label">{t('prop.eyebrow')}</div>
        <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('prop.title')}</h1>
        <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">{t('prop.summary')}</p>
      </header>

      <form onSubmit={handleLookup} className="bp-panel p-4" aria-label={t('prop.lookupLabel')}>
        <label htmlFor="propagation-object-ref" className="mb-1.5 block font-mono text-xs font-semibold">{t('prop.objectRef')}</label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="propagation-object-ref"
            value={lookupRef}
            onChange={(event) => setLookupRef(event.target.value)}
            required
            className="h-10 min-w-0 flex-1 rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none placeholder:text-faint focus-visible:ring-2 focus-visible:ring-ring"
            placeholder={t('prop.objectRefPlaceholder')}
          />
          <Button type="submit" disabled={!lookupRef.trim()}>
            <Search aria-hidden="true" size={14} /> {t('prop.openLedger')}
          </Button>
        </div>
        <p className="mt-2 font-mono text-xs text-faint">{t('prop.lookupHint')}</p>
      </form>

      {!objectRef && !publicationId ? (
        <section aria-labelledby="prop-empty-observation-heading" className="bp-panel p-5">
          <h2 id="prop-empty-observation-heading" className="font-mono text-base font-bold">{t('prop.emptyObservationTitle')}</h2>
          <p className="mt-2 font-mono text-xs leading-relaxed text-muted-foreground">{t('prop.emptyObservationNote')}</p>
        </section>
      ) : null}

      {loading ? <PageSkeleton /> : null}
      {!loading && emptyLedgerError ? (
        <section aria-labelledby="prop-empty-ledger-heading" className="bp-panel p-5" aria-live="polite">
          <h2 id="prop-empty-ledger-heading" className="font-mono text-base font-bold">{t('prop.emptyLedgerTitle')}</h2>
          <p className="mt-2 font-mono text-xs leading-relaxed text-muted-foreground">{t('prop.emptyLedgerNote')}</p>
          <p className="mt-3 border-l-2 border-border pl-3 font-mono text-xs leading-relaxed">{error.message}</p>
          <Button type="button" variant="ghost" className="mt-4" onClick={load}>{t('state.retry')}</Button>
        </section>
      ) : null}
      {!loading && error && !emptyLedgerError ? <RequestErrorState error={error} onRetry={load} /> : null}

      {!loading && data && ledger && summary ? (
        <>
          <section className="bp-panel p-4" aria-labelledby="prop-selected-heading">
            <div className="flex flex-wrap items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="bp-label">{t('prop.selectedPublication')}</div>
                <h2 id="prop-selected-heading" className="mt-1 font-mono text-base font-bold break-words">{ledger.title}</h2>
                <p className="mt-1 break-all font-mono text-xs text-faint">{ledger.object_id}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span className={`bp-tol ${data.persisted && !data.rehearsal ? 'bp-tol-ok' : 'bp-tol-urgent'}`}>
                  {data.persisted && !data.rehearsal ? t('prop.persisted') : t('prop.notDurable')}
                </span>
                {data.publication_record_id ? <span className="bp-tol bp-tol-flat">{data.publication_record_id}</span> : null}
              </div>
            </div>
            <p className="mt-3 font-mono text-xs leading-relaxed text-muted-foreground">{data.summary}</p>
            {data.command_id ? <p className="mt-2 break-all font-mono text-xs text-faint">{t('prop.commandId')}: {data.command_id}</p> : null}
          </section>

          <div className="flex flex-wrap gap-2.5">
            <Stat n={summary.synced} label={t('prop.statusSynced')} dot="var(--ok)" />
            <Stat n={summary.pending} label={t('prop.statusPending')} dot="var(--medium)" />
            <Stat n={summary.failed} label={t('prop.statusFailed')} dot="var(--urgent)" />
            <Stat n={summary.manual_action_required} label={t('prop.statusManual')} dot="var(--high)" />
          </div>

          <section aria-labelledby="prop-lanes-heading">
            <h2 id="prop-lanes-heading" className="mb-2 bp-label">{t('prop.lanes')}</h2>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
              {data.status_lanes.map((lane) => (
                <div
                  key={lane.status}
                  className="bp-panel p-4"
                  style={{ borderTopColor: STATUS_LANE_STYLE[lane.status], borderTopWidth: 2 }}
                >
                  <div className="flex items-center gap-2">
                    <span className="h-2 w-2 rotate-45" style={{ background: STATUS_LANE_STYLE[lane.status] }} />
                    <span className="font-mono text-sm font-bold">{v.propStatus(lane.status)}</span>
                    <span className="ml-auto font-mono text-lg font-bold" style={{ color: STATUS_LANE_STYLE[lane.status] }}>{lane.count}</span>
                  </div>
                  <p className="mt-1.5 font-mono text-xs leading-relaxed text-muted-foreground">{lane.note}</p>
                  {lane.surface_ids.length > 0 ? (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {lane.surface_ids.map((surface) => <span key={surface} className="bp-tol bp-tol-flat">{v.surface(surface)}</span>)}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
          </section>

          <div className="grid gap-4 lg:grid-cols-3">
            <section className="bp-panel overflow-hidden lg:col-span-2" aria-labelledby="prop-ledger-heading">
              <div className="flex flex-wrap items-baseline gap-2 px-4 pt-3.5">
                <h2 id="prop-ledger-heading" className="bp-label">{t('prop.ledger')}</h2>
                <span className="font-mono text-xs text-faint">{ledger.object_id}</span>
              </div>
              <div className="mt-1.5">
                {ledger.records.map((record) => <RecordRow key={record.surface_id} record={record} />)}
                {ledger.records.length === 0 ? (
                  <div className="px-4 py-8">
                    <h3 className="font-mono text-sm font-bold">{t('prop.noRecordsTitle')}</h3>
                    <p className="mt-2 font-mono text-xs leading-relaxed text-muted-foreground">{t('prop.noRecordsNote')}</p>
                  </div>
                ) : null}
              </div>
            </section>

            <aside className="flex flex-col gap-4" aria-label={t('prop.ledgerContext')}>
              {data.action_echo ? (
                <div className="bp-panel p-4">
                  <div className="mb-2 bp-label">{t('prop.actionEcho')}</div>
                  <span className="bp-tol bp-tol-high">{v.command(data.action_echo.selected_action)}</span>
                  <p className="mt-2 font-mono text-xs leading-relaxed text-muted-foreground">{data.action_echo.summary}</p>
                  {data.action_echo.action_log.length > 0 ? (
                    <ul className="mt-2 space-y-1">
                      {data.action_echo.action_log.map((log, index) => <li key={index} className="font-mono text-xs leading-relaxed text-faint">• {log}</li>)}
                    </ul>
                  ) : null}
                </div>
              ) : null}

              <div className="bp-panel p-4">
                <div className="mb-2 bp-label">{t('prop.unresolved')}</div>
                {ledger.unresolved_surfaces.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5">
                    {ledger.unresolved_surfaces.map((surface) => <span key={surface} className="bp-tol bp-tol-high">{v.surface(surface)}</span>)}
                  </div>
                ) : <p className="font-mono text-xs text-muted-foreground">{t('prop.noUnresolved')}</p>}
              </div>

              {ledger.continue_commands.length > 0 ? (
                <div className="bp-panel p-4">
                  <div className="mb-2 bp-label">{t('prop.continueCmds')}</div>
                  <div className="flex flex-wrap gap-2">
                    {ledger.continue_commands.map((command) => <CmdButton key={command} command={command} />)}
                  </div>
                </div>
              ) : null}

              {data.context_notes.length > 0 ? (
                <div className="bp-panel p-4">
                  <div className="mb-1.5 bp-label">{t('publish.contextNotes')}</div>
                  <ul className="space-y-1">
                    {data.context_notes.map((note, index) => <li key={index} className="font-mono text-xs leading-relaxed text-muted-foreground">{note}</li>)}
                  </ul>
                </div>
              ) : null}
            </aside>
          </div>

          <nav aria-label={t('prop.candidateNavigation')} className="bp-dim flex flex-wrap items-center gap-2 pt-4">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!data.previous_object_ref}
              onClick={() => data.previous_object_ref && gotoObject(data.previous_object_ref)}
            >
              <ArrowLeft aria-hidden="true" size={14} /> {t('prop.prev')}
            </Button>
            <span className="font-mono text-xs text-faint sm:mx-auto">{data.selected_position + 1} / {data.total_items}</span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!data.next_object_ref}
              onClick={() => data.next_object_ref && gotoObject(data.next_object_ref)}
            >
              {t('prop.next')} <ArrowRight aria-hidden="true" size={14} />
            </Button>
          </nav>
        </>
      ) : null}
    </div>
  )
}

function RecordRow({ record }: { record: SurfacePropagationRecord }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div className="bp-anno flex flex-col gap-1.5 !items-stretch px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rotate-45" style={{ background: STATUS_DOT[record.status] ?? 'var(--faint)' }} />
        <span className="font-mono text-[13px] font-semibold">{v.surface(record.surface_id)}</span>
        <span className={`bp-tol ${STATUS_CHIP[record.status] ?? 'bp-tol-flat'} ml-auto`}>{v.propStatus(record.status)}</span>
      </div>
      <p className="font-mono text-[12px] leading-relaxed text-muted-foreground">{record.reason}</p>
      {record.channel_refs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {record.channel_refs.map((ch) => <span key={ch} className="bp-tol bp-tol-flat">{v.surface(ch)}</span>)}
        </div>
      )}
      {record.follow_up_commands.length > 0 && (
        <div className="bp-dim mt-2 flex flex-wrap items-center gap-2 pt-2">
          <span className="font-mono text-[10px] uppercase text-faint">{t('prop.followUp')}</span>
          {record.follow_up_commands.map((cmd) => <CmdButton key={cmd} command={cmd} className="text-[10px]" />)}
        </div>
      )}
    </div>
  )
}
