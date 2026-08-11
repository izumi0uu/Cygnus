import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { AlertTriangle, Check, Loader2, RefreshCw, ShieldCheck, Upload } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import {
  fetchReadySources,
  fetchTicketPilotFunnel,
  importResolvedTicketExport,
  type ReadySourceOption,
  type TicketClusterCandidate,
  type TicketExportFormat,
  type TicketImportResult,
  type TicketPilotDurationSummary,
  type TicketPilotFunnelReport,
  type TicketPilotItem,
  type ImportedGovernanceSignal,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { ObservationBanner } from '@/components/ObservationBanner'
import { PageSkeleton } from '@/components/Skeleton'
import { Stat } from '@/components/Stat'
import { useAuth } from '@/lib/auth'
import { useVocab } from '@/lib/vocab'

const ACCEPT: Record<TicketExportFormat, string> = {
  csv: '.csv,text/csv',
  jsonl: '.jsonl,.json,application/json,application/x-ndjson',
}

type FieldErrorKey = 'source' | 'sourceRef' | 'minimumClusterSize' | 'file' | 'acknowledge'
type FieldErrors = Partial<Record<FieldErrorKey, string>>

type FunnelRequest = { id: number; sourceRef: string }

function formatDate(value: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function formatRate(value: number | null): string {
  if (value === null) return '—'
  return `${(value * 100).toFixed(value * 100 % 1 === 0 ? 0 : 1)}%`
}

function formatDuration(value: number | null, secondsLabel: string): string {
  if (value === null) return '—'
  const rounded = Number.isInteger(value) ? String(value) : value.toFixed(1)
  return `${rounded}${secondsLabel}`
}

function statusLabel(t: TFunction, status: string | null): string {
  if (!status) return t('ticketInsights.notObserved')
  const key = `ticketInsights.statusValue.${status}`
  const translated = t(key)
  return translated === key ? status.replace(/_/g, ' ') : translated
}

function queueHref(signalRef: string): string {
  return `/console/queue?risk=ticket_pressure:${encodeURIComponent(signalRef)}`
}

function fieldClass(hasError: boolean): string {
  return `mt-1.5 w-full border bg-transparent px-2.5 py-2 font-mono text-[12.5px] outline-none transition-colors focus:border-primary ${hasError ? 'border-[color-mix(in_srgb,var(--urgent)_60%,transparent)]' : 'border-[color-mix(in_srgb,var(--primary)_30%,transparent)]'}`
}

function ErrorNotice({
  title,
  message,
  retryLabel,
  onRetry,
}: {
  title: string
  message: string
  retryLabel?: string
  onRetry?: () => void
}) {
  return (
    <div
      className="border px-3 py-2.5 font-mono text-[11px] leading-relaxed"
      role="alert"
      style={{ color: 'var(--urgent)', borderColor: 'color-mix(in srgb, var(--urgent) 42%, transparent)' }}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="font-semibold">{title}</div>
          <div className="mt-1 break-words text-muted-foreground">{message}</div>
          {onRetry && retryLabel && (
            <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={onRetry}>
              <RefreshCw aria-hidden="true" size={13} />
              {retryLabel}
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

function ForbiddenState() {
  const { t } = useTranslation()
  return (
    <div className="min-h-full p-4 pb-10 pt-5 sm:p-6">
      <div className="mb-5 flex flex-wrap items-end gap-3">
        <div>
          <div className="bp-label mb-1">DWG-126 · TICKET CLUSTER INSIGHTS</div>
          <h1 className="font-mono text-[22px] font-bold leading-tight tracking-tight">{t('ticketInsights.forbiddenTitle')}</h1>
        </div>
        <span className="bp-stamp ml-auto" style={{ color: 'var(--urgent)' }}>{t('ticketInsights.eyebrow')}</span>
      </div>
      <section className="bp-panel max-w-2xl p-5" aria-labelledby="ticket-insights-forbidden-title">
        <div className="flex items-start gap-3">
          <ShieldCheck aria-hidden="true" size={18} style={{ color: 'var(--urgent)' }} />
          <div>
            <h2 id="ticket-insights-forbidden-title" className="font-mono text-sm font-semibold">{t('ticketInsights.forbiddenTitle')}</h2>
            <p className="mt-2 font-mono text-[12px] leading-relaxed text-muted-foreground">{t('ticketInsights.forbiddenBody')}</p>
            <div className="mt-4 bp-tol bp-tol-urgent">{t('ticketInsights.adminOnly')}</div>
          </div>
        </div>
      </section>
    </div>
  )
}

export default function TicketInsights() {
  const { user } = useAuth()
  // Keep the permission branch outside the data-owning component. The admin
  // component (and therefore every pilot effect) is never mounted for others.
  if (user?.role !== 'admin') return <ForbiddenState />
  return <AdminTicketInsights />
}

function AdminTicketInsights() {
  const { t } = useTranslation()
  const [sources, setSources] = useState<ReadySourceOption[]>([])
  const [sourcesLoading, setSourcesLoading] = useState(true)
  const [sourcesError, setSourcesError] = useState<string | null>(null)
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [sourceRef, setSourceRef] = useState('')
  const [exportFormat, setExportFormat] = useState<TicketExportFormat>('csv')
  const [minimumClusterSize, setMinimumClusterSize] = useState('3')
  const [file, setFile] = useState<File | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState<string | null>(null)
  const [importResult, setImportResult] = useState<TicketImportResult | null>(null)
  const [funnel, setFunnel] = useState<TicketPilotFunnelReport | null>(null)
  const [funnelLoading, setFunnelLoading] = useState(false)
  const [funnelError, setFunnelError] = useState<string | null>(null)
  const sourceRefInput = useRef<HTMLInputElement>(null)
  const sourceSelect = useRef<HTMLSelectElement>(null)
  const minimumInput = useRef<HTMLInputElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const acknowledgeInput = useRef<HTMLInputElement>(null)
  const funnelRequest = useRef<FunnelRequest>({ id: 0, sourceRef: '' })

  const loadSources = useCallback(async () => {
    try {
      const page = await fetchReadySources()
      setSources(page.items)
      setSelectedSourceId((current) => page.items.some((source) => source.id === current) ? current : '')
    } catch (error) {
      setSourcesError(error instanceof Error ? error.message : String(error))
    } finally {
      setSourcesLoading(false)
    }
  }, [])

  const retrySources = useCallback(() => {
    setSourcesLoading(true)
    setSourcesError(null)
    void loadSources()
  }, [loadSources])

  useEffect(() => {
    let cancelled = false
    fetchReadySources()
      .then((page) => {
        if (cancelled) return
        setSources(page.items)
        setSelectedSourceId((current) => page.items.some((source) => source.id === current) ? current : '')
      })
      .catch((error: unknown) => {
        if (!cancelled) setSourcesError(error instanceof Error ? error.message : String(error))
      })
      .finally(() => {
        if (!cancelled) setSourcesLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const selectedSource = sources.find((source) => source.id === selectedSourceId) ?? null

  const clearFieldError = useCallback((key: FieldErrorKey) => {
    setFieldErrors((current) => {
      if (!current[key]) return current
      const next = { ...current }
      delete next[key]
      return next
    })
  }, [])
  const updateSourceRef = (value: string) => {
    setSourceRef(value)
    funnelRequest.current = { id: funnelRequest.current.id + 1, sourceRef: value.trim() }
    setFunnelLoading(false)
    setFunnel((current) => current && current.source_ref === value.trim() ? current : null)
    setFunnelError(null)
    clearFieldError('sourceRef')
  }

  const loadFunnel = useCallback(async (requestedSourceRef: string) => {
    const scope = requestedSourceRef.trim()
    if (!scope) {
      setFunnel(null)
      setFunnelError(t('ticketInsights.sourceRefRequired'))
      return
    }
    const requestId = funnelRequest.current.id + 1
    funnelRequest.current = { id: requestId, sourceRef: scope }
    setFunnelLoading(true)
    setFunnelError(null)
    setFunnel(null)
    try {
      const next = await fetchTicketPilotFunnel(scope)
      if (funnelRequest.current.id === requestId && funnelRequest.current.sourceRef === scope) setFunnel(next)
    } catch (error) {
      if (funnelRequest.current.id === requestId) setFunnelError(error instanceof Error ? error.message : String(error))
    } finally {
      if (funnelRequest.current.id === requestId) setFunnelLoading(false)
    }
  }, [t])

  const validate = (): { normalizedSourceRef: string; threshold: number } | null => {
    const next: FieldErrors = {}
    const normalizedSourceRef = sourceRef.trim()
    if (!selectedSourceId) next.source = t('ticketInsights.sourceRequired')
    if (!normalizedSourceRef) next.sourceRef = t('ticketInsights.sourceRefRequired')
    else if (normalizedSourceRef.length > 300 || Array.from(normalizedSourceRef).some((character) => character.charCodeAt(0) < 32)) next.sourceRef = t('ticketInsights.sourceRefInvalid')
    const threshold = Number(minimumClusterSize)
    if (!Number.isInteger(threshold) || threshold < 2 || threshold > 100) next.minimumClusterSize = t('ticketInsights.minimumClusterSizeError')
    if (!file) next.file = t('ticketInsights.fileRequired')
    else {
      const extension = file.name.toLowerCase().split('.').pop()
      if ((exportFormat === 'csv' && extension !== 'csv') || (exportFormat === 'jsonl' && extension !== 'jsonl' && extension !== 'json')) {
        next.file = t('ticketInsights.fileFormatError')
      }
    }
    if (!acknowledged) next.acknowledge = t('ticketInsights.acknowledgeRequired')
    setFieldErrors(next)
    const firstError = (Object.keys(next) as FieldErrorKey[])[0]
    if (firstError === 'source') sourceSelect.current?.focus()
    else if (firstError === 'sourceRef') sourceRefInput.current?.focus()
    else if (firstError === 'minimumClusterSize') minimumInput.current?.focus()
    else if (firstError === 'file') fileInput.current?.focus()
    else if (firstError === 'acknowledge') acknowledgeInput.current?.focus()
    return firstError ? null : { normalizedSourceRef, threshold }
  }

  const handleImport = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (importing) return
    const valid = validate()
    if (!valid || !file || !selectedSourceId) return
    setImporting(true)
    setImportError(null)
    setImportResult(null)
    try {
      const result = await importResolvedTicketExport({
        file,
        sourceRef: valid.normalizedSourceRef,
        sourceId: selectedSourceId,
        exportFormat,
        minimumClusterSize: valid.threshold,
      })
      setImportResult(result)
      setSourceRef(result.source_ref)
      void loadFunnel(result.source_ref)
    } catch (error) {
      setImportError(error instanceof Error ? error.message : String(error))
    } finally {
      setImporting(false)
    }
  }

  if (sourcesLoading) return <PageSkeleton />
  if (sourcesError) {
    return (
      <div className="min-h-full p-4 pb-10 pt-5 sm:p-6">
        <PageHeading />
        <ErrorNotice title={t('ticketInsights.sourceError')} message={sourcesError} retryLabel={t('ticketInsights.retrySources')} onRetry={retrySources} />
      </div>
    )
  }

  return (
    <div className="min-h-full p-4 pb-10 pt-5 sm:p-6">
      <PageHeading />

      <section className="bp-panel mb-5 p-4 sm:p-5" aria-labelledby="ticket-import-handoff-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="bp-label">SEC-D · {t('ticketInsights.handoff')}</div>
            <h2 id="ticket-import-handoff-title" className="mt-1 font-mono text-base font-bold">{t('ticketInsights.handoff')}</h2>
            <p className="mt-1.5 max-w-3xl font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.handoffNote')}</p>
          </div>
          <span className="bp-tol bp-tol-high">resolved-ticket-export/v1</span>
        </div>

        {sources.length === 0 ? (
          <div className="mt-4 border border-[color-mix(in_srgb,var(--high)_40%,transparent)] px-3 py-3 font-mono text-[11px] leading-relaxed text-muted-foreground" role="status">
            <div className="flex items-start gap-2">
              <AlertTriangle aria-hidden="true" size={14} className="mt-0.5 shrink-0" style={{ color: 'var(--high)' }} />
              <span>{t('ticketInsights.sourceEmpty')}</span>
            </div>
          </div>
        ) : null}

        <form className="mt-4 grid gap-4" onSubmit={handleImport} noValidate>
          <div className="grid gap-4 lg:grid-cols-2">
            <label className="flex min-w-0 flex-col gap-1.5">
              <span className="bp-label-inline">{t('ticketInsights.source')}</span>
              <select
                ref={sourceSelect}
                id="ticket-source"
                name="source_id"
                value={selectedSourceId}
                required
                aria-invalid={Boolean(fieldErrors.source)}
                aria-describedby={fieldErrors.source ? 'ticket-source-error' : undefined}
                onChange={(event) => { setSelectedSourceId(event.target.value); clearFieldError('source') }}
                className={fieldClass(Boolean(fieldErrors.source))}
              >
                <option value="">{t('ticketInsights.sourcePlaceholder')}</option>
                {sources.map((source) => (
                  <option key={source.id} value={source.id}>{source.title ?? source.file_name ?? source.id}</option>
                ))}
              </select>
              {fieldErrors.source && <span id="ticket-source-error" role="alert" className="font-mono text-[10.5px] text-[var(--urgent)]">{fieldErrors.source}</span>}
              {selectedSource && (
                <span className="bp-dim mt-1 break-all pt-2 font-mono text-[10px] leading-relaxed text-faint">
                  {t('ticketInsights.sourceId')}: {selectedSource.id} · {t('ticketInsights.sourceStatus')}: {selectedSource.status}
                  {selectedSource.file_name ? ` · ${selectedSource.file_name}` : ''}
                </span>
              )}
            </label>

            <label className="flex min-w-0 flex-col gap-1.5">
              <span className="bp-label-inline">{t('ticketInsights.sourceRef')}</span>
              <input
                ref={sourceRefInput}
                id="ticket-source-ref"
                name="source_ref"
                type="text"
                value={sourceRef}
                required
                spellCheck={false}
                autoComplete="off"
                aria-invalid={Boolean(fieldErrors.sourceRef)}
                aria-describedby={`ticket-source-ref-hint${fieldErrors.sourceRef ? ' ticket-source-ref-error' : ''}`}
                onChange={(event) => updateSourceRef(event.target.value)}
                className={fieldClass(Boolean(fieldErrors.sourceRef))}
              />
              <span id="ticket-source-ref-hint" className="font-mono text-[10px] leading-relaxed text-faint">{t('ticketInsights.sourceRefHint')}</span>
              {fieldErrors.sourceRef && <span id="ticket-source-ref-error" role="alert" className="font-mono text-[10.5px] text-[var(--urgent)]">{fieldErrors.sourceRef}</span>}
            </label>
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.35fr)]">
            <label className="flex min-w-0 flex-col gap-1.5">
              <span className="bp-label-inline">{t('ticketInsights.format')}</span>
              <select
                id="ticket-export-format"
                name="export_format"
                value={exportFormat}
                onChange={(event) => { setExportFormat(event.target.value as TicketExportFormat); setFile(null); clearFieldError('file') }}
                className={fieldClass(false)}
              >
                <option value="csv">CSV</option>
                <option value="jsonl">JSONL</option>
              </select>
            </label>

            <label className="flex min-w-0 flex-col gap-1.5">
              <span className="bp-label-inline">{t('ticketInsights.minimumClusterSize')}</span>
              <input
                ref={minimumInput}
                id="ticket-minimum-cluster-size"
                name="minimum_cluster_size"
                type="number"
                min={2}
                max={100}
                step={1}
                inputMode="numeric"
                value={minimumClusterSize}
                aria-invalid={Boolean(fieldErrors.minimumClusterSize)}
                aria-describedby={`ticket-minimum-hint${fieldErrors.minimumClusterSize ? ' ticket-minimum-error' : ''}`}
                onChange={(event) => { setMinimumClusterSize(event.target.value); clearFieldError('minimumClusterSize') }}
                className={fieldClass(Boolean(fieldErrors.minimumClusterSize))}
              />
              <span id="ticket-minimum-hint" className="font-mono text-[10px] leading-relaxed text-faint">{t('ticketInsights.minimumClusterSizeHint')}</span>
              {fieldErrors.minimumClusterSize && <span id="ticket-minimum-error" role="alert" className="font-mono text-[10.5px] text-[var(--urgent)]">{fieldErrors.minimumClusterSize}</span>}
            </label>

            <label className="flex min-w-0 flex-col gap-1.5">
              <span className="bp-label-inline">{t('ticketInsights.file')}</span>
              <input
                ref={fileInput}
                id="ticket-export-file"
                name="file"
                key={exportFormat}
                type="file"
                required
                accept={ACCEPT[exportFormat]}
                aria-invalid={Boolean(fieldErrors.file)}
                aria-describedby={fieldErrors.file ? 'ticket-file-error' : undefined}
                onChange={(event) => { setFile(event.target.files?.[0] ?? null); clearFieldError('file') }}
                className={fieldClass(Boolean(fieldErrors.file))}
              />
              <span className="font-mono text-[10px] leading-relaxed text-faint">{file ? `${file.name} · ${file.size.toLocaleString()} B` : t('ticketInsights.filePlaceholder')}</span>
              {fieldErrors.file && <span id="ticket-file-error" role="alert" className="font-mono text-[10.5px] text-[var(--urgent)]">{fieldErrors.file}</span>}
            </label>
          </div>

          <label className="flex items-start gap-2.5 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_25%,transparent)] pt-3.5">
            <input
              ref={acknowledgeInput}
              id="ticket-sanitized-ack"
              name="sanitized_acknowledged"
              type="checkbox"
              checked={acknowledged}
              required
              aria-invalid={Boolean(fieldErrors.acknowledge)}
              aria-describedby={fieldErrors.acknowledge ? 'ticket-ack-error' : undefined}
              onChange={(event) => { setAcknowledged(event.target.checked); clearFieldError('acknowledge') }}
              className="mt-0.5 h-4 w-4 accent-[var(--primary)]"
            />
            <span className="min-w-0 font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.acknowledge')}</span>
          </label>
          {fieldErrors.acknowledge && <span id="ticket-ack-error" role="alert" className="-mt-2 font-mono text-[10.5px] text-[var(--urgent)]">{fieldErrors.acknowledge}</span>}

          {importError && <ErrorNotice title={t('ticketInsights.importError')} message={importError} />}

          <div className="flex flex-wrap items-center gap-2 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_25%,transparent)] pt-3.5">
            <Button type="submit" disabled={importing || sources.length === 0}>
              {importing ? <Loader2 aria-hidden="true" size={14} className="animate-spin" /> : <Upload aria-hidden="true" size={14} />}
              {importing ? t('ticketInsights.submitting') : t('ticketInsights.submit')}
            </Button>
            <span className="font-mono text-[10px] text-faint">{t('ticketInsights.durableBoundaryNote')}</span>
          </div>
        </form>
      </section>

      {importResult && <ImportReceipt result={importResult} />}

      <FunnelObservation
        sourceRef={sourceRef}
        report={funnel}
        loading={funnelLoading}
        error={funnelError}
        onLoad={() => { void loadFunnel(sourceRef) }}
      />
    </div>
  )
}

function PageHeading() {
  const { t } = useTranslation()
  return (
    <div className="mb-5 flex flex-wrap items-end gap-3">
      <div className="min-w-0">
        <div className="bp-label mb-1">DWG-126 · TICKET CLUSTER INSIGHTS</div>
        <h1 className="font-mono text-[22px] font-bold leading-tight tracking-tight">{t('ticketInsights.title')}</h1>
        <p className="mt-1.5 max-w-4xl font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.intro')}</p>
      </div>
      <span className="bp-stamp ml-auto" style={{ color: 'var(--high)' }}>{t('ticketInsights.eyebrow')}</span>
    </div>
  )
}

function ImportReceipt({ result }: { result: TicketImportResult }) {
  const { t } = useTranslation()
  return (
    <section className="mb-5" aria-labelledby="ticket-import-receipt-title">
      <div className="mb-2 flex flex-wrap items-baseline gap-2">
        <div id="ticket-import-receipt-title" className="bp-label">{t('ticketInsights.importReceipt')}</div>
        <span className="font-mono text-[10px] text-faint">{result.import_digest}</span>
      </div>
      <div className="mb-3 flex flex-wrap gap-2.5">
        <Stat n={result.record_count} label={t('ticketInsights.records')} />
        <Stat n={result.candidate_count} label={t('ticketInsights.candidates')} />
        <Stat n={result.qualifying_candidate_count} label={t('ticketInsights.qualifyingCandidates')} dot="var(--ok)" />
        <Stat n={result.persisted_signal_count} label={t('ticketInsights.persistedSignals')} dot="var(--high)" />
      </div>
      <div className="bp-panel p-4 sm:p-5">
        <div className="mb-2 bp-label">{t('ticketInsights.durableBoundary')}</div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="bp-tol bp-tol-high">{t('ticketInsights.publicationState', { state: `${t('ticketInsights.notPublished')} · ${result.publication_state}` })}</span>
          <span className="bp-tol bp-tol-flat">{t('ticketInsights.notSubmitted')} · not_submitted</span>
        </div>
        <p className="mt-3 font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.durableBoundaryNote')}</p>
        <div className="mt-3 grid gap-2 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_25%,transparent)] pt-3 font-mono text-[10px] text-faint sm:grid-cols-2">
          <span className="break-all">{t('ticketInsights.sourceRef')}: {result.source_ref}</span>
          <span>{t('ticketInsights.sourceBinding')}: {result.source_id}</span>
          <span>{t('ticketInsights.contractVersion')}: {result.contract_version}</span>
          <span>{t('ticketInsights.exportFormat')}: {result.export_format.toUpperCase()} · {t('ticketInsights.minimumClusterSize')}: {result.minimum_cluster_size}</span>
          <span className="break-all">{t('ticketInsights.importDigest')}: {result.import_digest}</span>
          <span>{t('ticketInsights.nextStep')}: {result.next_step === 'review_qualifying_candidates' ? t('ticketInsights.reviewQualifyingCandidates') : result.next_step}</span>
        </div>

        <div className="mt-5" aria-labelledby="ticket-candidates-title">
          <div id="ticket-candidates-title" className="mb-1 bp-label">{t('ticketInsights.candidateRegion')}</div>
          <p className="mb-3 font-mono text-[10px] leading-relaxed text-faint">{t('ticketInsights.candidateRegionNote')}</p>
          {result.candidates.length > 0 ? (
            <div className="grid gap-3 md:grid-cols-2">
              {result.candidates.map((candidate) => <CandidateCard key={candidate.cluster_ref} candidate={candidate} />)}
            </div>
          ) : (
            <div className="bp-dim py-5 text-center font-mono text-[11px] text-muted-foreground">{t('ticketInsights.noCandidates')}</div>
          )}
        </div>

        <div className="mt-5" aria-labelledby="ticket-signals-title">
          <div id="ticket-signals-title" className="mb-1 bp-label">{t('ticketInsights.signalRegion')}</div>
          <p className="mb-3 font-mono text-[10px] leading-relaxed text-faint">{t('ticketInsights.signalRegionNote')}</p>
          {result.persisted_signal_refs.length > 0 ? (
            <div className="grid gap-3 md:grid-cols-2">
              {result.persisted_signal_refs.map((signalRef) => (
                <SignalCard
                  key={signalRef}
                  signalRef={signalRef}
                  signal={result.governance_signals.find((item) => item.signal_ref === signalRef) ?? null}
                />
              ))}
            </div>
          ) : (
            <div className="bp-dim py-5 text-center font-mono text-[11px] text-muted-foreground">{t('ticketInsights.noSignals')}</div>
          )}
        </div>
      </div>
    </section>
  )
}

function CandidateCard({ candidate }: { candidate: TicketClusterCandidate }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <article className="bp-panel overflow-hidden">
      <div className="bp-dim flex flex-wrap items-center gap-2 px-3.5 py-2.5">
        <span className={`bp-tol ${candidate.qualifies ? 'bp-tol-ok' : 'bp-tol-high'}`}>
          {candidate.qualifies ? <Check aria-hidden="true" size={11} className="mr-1 inline" /> : null}
          {candidate.qualifies ? t('ticketInsights.qualifies') : t('ticketInsights.excluded')}
        </span>
        <span className="ml-auto break-all font-mono text-[10px] text-faint">{candidate.cluster_ref}</span>
      </div>
      <div className="flex flex-col gap-2.5 p-3.5">
        <div>
          <div className="font-mono text-[13px] font-semibold leading-snug">{candidate.title}</div>
          <div className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{t('ticketInsights.issueSignature')}: {candidate.issue_signature}</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="bp-tol bp-tol-flat">{v.objectType(candidate.object_type)}</span>
          {candidate.feature && <span className="bp-tol bp-tol-flat">{candidate.feature}</span>}
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_22%,transparent)] pt-2 font-mono text-[10px] text-faint">
          <span>{t('ticketInsights.members')}: {candidate.member_count}</span>
          <span>{t('ticketInsights.threshold')}: {candidate.minimum_cluster_size}</span>
          <span>{t('ticketInsights.evidenceRefs')}: {candidate.evidence_ref_count}</span>
          <span>{t('ticketInsights.objectType')}: {v.objectType(candidate.object_type)}</span>
          <span className="col-span-2 break-all">{t('ticketInsights.window')}: {formatDate(candidate.window_start)} → {formatDate(candidate.window_end)}</span>
        </div>
        <p className="font-mono text-[11px] leading-relaxed text-muted-foreground">{candidate.representative_excerpt}</p>
      </div>
    </article>
  )
}

function SignalCard({ signalRef, signal }: { signalRef: string; signal: ImportedGovernanceSignal | null }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <article className="bp-panel overflow-hidden">
      <div className="bp-dim flex flex-wrap items-center gap-2 px-3.5 py-2.5">
        <span className="bp-tol bp-tol-high">{v.riskType('ticket_pressure')}</span>
        <span className="bp-tol bp-tol-flat">{t('ticketInsights.notPublished')}</span>
      </div>
      <div className="flex flex-col gap-2.5 p-3.5">
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="break-all font-mono text-[12px] font-semibold">{signalRef}</div>
            {signal && <div className="mt-1 font-mono text-[11px] text-muted-foreground">{signal.title}</div>}
          </div>
          <Link
            to={queueHref(signalRef)}
            className="bp-cmd shrink-0"
            aria-label={`${t('ticketInsights.queueLink')}: ${signalRef}`}
          >
            {t('ticketInsights.queueLink')} →
          </Link>
        </div>
        {signal ? (
          <>
            <div className="flex flex-wrap gap-1.5">
              <span className="bp-tol bp-tol-flat">{v.objectType(signal.object_type)}</span>
              <span className="bp-tol bp-tol-flat">{t('ticketInsights.signalStatus')}: {statusLabel(t, signal.status)}</span>
            </div>
            <p className="font-mono text-[11px] leading-relaxed text-muted-foreground">{signal.summary}</p>
            {signal.evidence_excerpt && <p className="font-mono text-[10px] leading-relaxed text-faint"><span className="bp-label-inline">{t('ticketInsights.excerpt')}</span> {signal.evidence_excerpt}</p>}
            <div className="border-t border-dashed border-[color-mix(in_srgb,var(--primary)_22%,transparent)] pt-2 font-mono text-[10px] leading-relaxed text-faint">
              <div><span className="bp-label-inline">{t('ticketInsights.reason')}</span> {signal.reason}</div>
              <div className="mt-1">{t('ticketInsights.evidenceRefs')}: {signal.evidence_refs.length} · {t('ticketInsights.createdAt')}: {formatDate(signal.created_at)}</div>
            </div>
          </>
        ) : (
          <div className="font-mono text-[10px] text-faint">{t('ticketInsights.persistedSignals')}</div>
        )}
      </div>
    </article>
  )
}

function FunnelObservation({
  sourceRef,
  report,
  loading,
  error,
  onLoad,
}: {
  sourceRef: string
  report: TicketPilotFunnelReport | null
  loading: boolean
  error: string | null
  onLoad: () => void
}) {
  const { t } = useTranslation()
  return (
    <section className="bp-panel p-4 sm:p-5" aria-labelledby="ticket-funnel-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="bp-label">SEC-D · {t('ticketInsights.funnel')}</div>
          <h2 id="ticket-funnel-title" className="mt-1 font-mono text-base font-bold">{t('ticketInsights.funnel')}</h2>
          <p className="mt-1.5 max-w-3xl font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.funnelNote')}</p>
        </div>
        <button type="button" className="bp-cmd disabled:cursor-not-allowed disabled:opacity-50" disabled={loading || !sourceRef.trim()} onClick={onLoad}>
          {loading ? t('ticketInsights.loadingFunnel') : t('ticketInsights.loadFunnel')}
        </button>
      </div>

      <div className="mt-4 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_25%,transparent)] pt-3 font-mono text-[11px]">
        <span className="bp-label-inline">{t('ticketInsights.funnelSource')}</span>
        <span className="ml-2 break-all text-muted-foreground">{sourceRef.trim() || '—'}</span>
      </div>

      {error && <div className="mt-4"><ErrorNotice title={t('ticketInsights.funnelError')} message={error} retryLabel={t('ticketInsights.loadFunnel')} onRetry={onLoad} /></div>}
      {!report && !loading && !error && (
        <div className="bp-dim mt-4 py-8 text-center font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.funnelPrompt')}</div>
      )}
      {report && <FunnelReport report={report} />}
    </section>
  )
}

function FunnelReport({ report }: { report: TicketPilotFunnelReport }) {
  const { t } = useTranslation()
  const summary = report.summary
  return (
    <div className="mt-4">
      <div className="mb-2 break-all font-mono text-[10px] text-faint">{t('ticketInsights.funnelReceipt')} · {report.source_ref}</div>
      <ObservationBanner observation={report.observation} />
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={report.matched_signal_count} label={t('ticketInsights.matchedSignals')} />
        <Stat n={report.excluded_signal_count} label={t('ticketInsights.excludedSignals')} dot="var(--high)" />
        <Stat n={report.import_digests.length} label={t('ticketInsights.imports')} />
      </div>
      <div className="bp-panel mb-4 p-4">
        <div className="mb-2 bp-label">{t('ticketInsights.durableBoundary')}</div>
        <div className="flex flex-wrap items-center gap-2">
          {report.persisted && <span className="bp-stamp" style={{ color: 'var(--ok)' }}>{t('ticketInsights.persisted')}</span>}
          <span className="bp-tol bp-tol-high">{t('ticketInsights.impactUnproven')}</span>
          <span className="bp-tol bp-tol-flat">{t('ticketInsights.rehearsal', { value: String(report.rehearsal) })}</span>
        </div>
        <p className="mt-2 font-mono text-[11px] leading-relaxed text-muted-foreground">{t('ticketInsights.boundaryMetric', { value: String(report.metric_boundary.business_impact_proven) })}</p>
        <p className="mt-1 font-mono text-[10px] text-faint">{t('ticketInsights.metricKind', { kind: report.metric_boundary.kind })}</p>
        {report.excluded_signal_count > 0 && (
          <p className="mt-2 border-t border-dashed border-[color-mix(in_srgb,var(--high)_28%,transparent)] pt-2 font-mono text-[10px] leading-relaxed" style={{ color: 'var(--high)' }}>
            {t('ticketInsights.excludedNote')}
          </p>
        )}
        <div className="mt-3 flex flex-wrap gap-1.5">
          {report.import_digests.length > 0 ? report.import_digests.map((digest) => <span key={digest} className="bp-tol bp-tol-flat break-all">{digest}</span>) : <span className="font-mono text-[10px] text-faint">{t('ticketInsights.notObserved')}</span>}
        </div>
      </div>

      <div className="mb-4" aria-labelledby="ticket-funnel-lifecycle-title">
        <div id="ticket-funnel-lifecycle-title" className="mb-2 bp-label">{t('ticketInsights.lifecycle')}</div>
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <Stat n={summary.eligible_signal_count} label={t('ticketInsights.eligible')} />
          <Stat n={summary.promoted_draft_count} label={t('ticketInsights.promoted')} />
          <Stat n={summary.review_submitted_draft_count} label={t('ticketInsights.submitted')} />
          <Stat n={summary.review_decided_draft_count} label={t('ticketInsights.decided')} />
          <Stat n={summary.approved_draft_count} label={t('ticketInsights.approved')} dot="var(--ok)" />
          <Stat n={summary.rejected_draft_count} label={t('ticketInsights.rejected')} dot="var(--urgent)" />
          <Stat n={summary.needs_revision_draft_count} label={t('ticketInsights.needsRevision')} dot="var(--high)" />
          <Stat n={summary.published_draft_count} label={t('ticketInsights.published')} dot="var(--ok)" />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <RatePanel summary={summary} />
        <DurationPanel summary={summary} />
      </div>

      <div className="mt-5" aria-labelledby="ticket-funnel-items-title">
        <div id="ticket-funnel-items-title" className="mb-2 bp-label">{t('ticketInsights.itemRegion')}</div>
        {report.items.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {report.items.map((item) => <FunnelItemCard key={`${item.signal_ref}:${item.import_digest}`} item={item} />)}
          </div>
        ) : (
          <div className="bp-dim py-6 text-center font-mono text-[11px] text-muted-foreground">{t('ticketInsights.noItems')}</div>
        )}
      </div>
    </div>
  )
}

function RatePanel({ summary }: { summary: TicketPilotFunnelReport['summary'] }) {
  const { t } = useTranslation()
  const rates = [
    ['signalToDraft', summary.rates.signal_to_draft],
    ['draftToReview', summary.rates.draft_to_review],
    ['terminalReviewAcceptance', summary.rates.terminal_review_acceptance],
    ['draftToPublish', summary.rates.draft_to_publish],
  ] as const
  return (
    <section className="bp-panel p-4" aria-labelledby="ticket-funnel-rates-title">
      <div id="ticket-funnel-rates-title" className="mb-3 bp-label">{t('ticketInsights.rates')}</div>
      <div className="grid gap-2">
        {rates.map(([key, value]) => (
          <div key={key} className="flex items-center justify-between gap-3 border-b border-dashed border-[color-mix(in_srgb,var(--primary)_20%,transparent)] pb-2 last:border-b-0 last:pb-0">
            <span className="font-mono text-[11px] text-muted-foreground">{t(`ticketInsights.${key}`)}</span>
            <span className="font-mono text-sm font-semibold">{formatRate(value)}</span>
          </div>
        ))}
      </div>
    </section>
  )
}

function DurationPanel({ summary }: { summary: TicketPilotFunnelReport['summary'] }) {
  const { t } = useTranslation()
  const rows = [
    ['signalToDraft', summary.durations_seconds.signal_to_draft],
    ['draftToReview', summary.durations_seconds.draft_to_review],
    ['signalToPublish', summary.durations_seconds.signal_to_publish],
  ] as const
  return (
    <section className="bp-panel p-4" aria-labelledby="ticket-funnel-durations-title">
      <div id="ticket-funnel-durations-title" className="mb-3 bp-label">{t('ticketInsights.durations')}</div>
      <div className="grid gap-3">
        {rows.map(([key, duration]) => <DurationSummary key={key} label={t(`ticketInsights.${key}`)} duration={duration} />)}
      </div>
    </section>
  )
}

function DurationSummary({ label, duration }: { label: string; duration: TicketPilotDurationSummary }) {
  const { t } = useTranslation()
  return (
    <div className="border-b border-dashed border-[color-mix(in_srgb,var(--primary)_20%,transparent)] pb-2 last:border-b-0 last:pb-0">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-[11px] text-muted-foreground">{label}</span>
        <span className="font-mono text-[10px] text-faint">{duration.observed_count > 0 ? t('ticketInsights.observed', { count: duration.observed_count }) : t('ticketInsights.notObserved')}</span>
      </div>
      <div className="mt-1 grid grid-cols-1 gap-1 font-mono text-[10px] text-faint sm:grid-cols-3">
        <span>{t('ticketInsights.average')}: <strong className="text-foreground">{formatDuration(duration.average, t('ticketInsights.seconds'))}</strong></span>
        <span>{t('ticketInsights.minimum')}: <strong className="text-foreground">{formatDuration(duration.minimum, t('ticketInsights.seconds'))}</strong></span>
        <span>{t('ticketInsights.maximum')}: <strong className="text-foreground">{formatDuration(duration.maximum, t('ticketInsights.seconds'))}</strong></span>
      </div>
    </div>
  )
}

function FunnelItemCard({ item }: { item: TicketPilotItem }) {
  const { t } = useTranslation()
  const v = useVocab()
  const dateRows = [
    [t('ticketInsights.observedAt'), formatDate(item.signal_observed_at)],
    [t('ticketInsights.createdAt'), formatDate(item.signal_created_at)],
    [t('ticketInsights.promotion'), formatDate(item.promotion.created_at)],
    [t('ticketInsights.draft'), statusLabel(t, item.draft.status)],
    [t('ticketInsights.review'), formatDate(item.review.submitted_at)],
    [t('ticketInsights.decision'), item.review.decision ? statusLabel(t, item.review.decision) : t('ticketInsights.notObserved')],
    [t('ticketInsights.publication'), formatDate(item.publication.published_at)],
  ]
  return (
    <article className="bp-panel overflow-hidden">
      <div className="bp-dim flex flex-wrap items-center gap-2 px-3.5 py-2.5">
        <span className="bp-tol bp-tol-high">{v.riskType('ticket_pressure')}</span>
        <span className="bp-tol bp-tol-flat">{statusLabel(t, item.signal_status)}</span>
      </div>
      <div className="flex flex-col gap-2.5 p-3.5">
        <div>
          <div className="break-all font-mono text-[12px] font-semibold">{item.signal_ref}</div>
          <div className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{t('ticketInsights.cluster')}: {item.ticket_cluster_ref}</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <span className="bp-tol bp-tol-flat">{v.objectType(item.object_type)}</span>
          <span className="bp-tol bp-tol-flat">{t('ticketInsights.evidenceRefs')}: {item.evidence_ref_count}</span>
        </div>
        <div className="grid gap-1 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_22%,transparent)] pt-2 font-mono text-[10px] text-faint sm:grid-cols-2">
          {dateRows.map(([label, value]) => <span key={label} className="min-w-0 break-words">{label}: {value}</span>)}
        </div>
        <div className="grid gap-1 border-t border-dashed border-[color-mix(in_srgb,var(--primary)_22%,transparent)] pt-2 font-mono text-[10px] text-faint sm:grid-cols-3">
          <span>{t('ticketInsights.signalToDraft')}: {formatDuration(item.durations_seconds.signal_to_draft, t('ticketInsights.seconds'))}</span>
          <span>{t('ticketInsights.draftToReview')}: {formatDuration(item.durations_seconds.draft_to_review, t('ticketInsights.seconds'))}</span>
          <span>{t('ticketInsights.signalToPublish')}: {formatDuration(item.durations_seconds.signal_to_publish, t('ticketInsights.seconds'))}</span>
        </div>
      </div>
    </article>
  )
}
