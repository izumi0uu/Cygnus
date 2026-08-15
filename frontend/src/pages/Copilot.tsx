import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ArrowUpRight, CheckCircle2, FileSearch, LockKeyhole, RotateCw, ShieldAlert } from 'lucide-react'
import {
  fetchSessionBridgeManifest,
  SESSION_CONTRACT_VERSION,
  submitSessionQuery,
  submitSessionFeedback,
  type SessionAudienceContext,
  type SessionBridgeManifest,
  type SessionGovernanceDisposition,
  type SessionFeedbackResponse,
  type SessionFeedbackSignalType,
  type SessionQueryResponse,
  type SourceTrace,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { PageSkeleton } from '@/components/Skeleton'
import { RequestErrorState } from '@/components/RequestState'

const DISPOSITION_STYLE: Record<SessionGovernanceDisposition, { badge: string; border: string; Icon: typeof CheckCircle2 }> = {
  answerable: { badge: 'bp-tol-ok', border: 'var(--ok)', Icon: CheckCircle2 },
  restricted: { badge: 'bp-tol-high', border: 'var(--high)', Icon: LockKeyhole },
  fallback: { badge: 'bp-tol-urgent', border: 'var(--urgent)', Icon: ShieldAlert },
  escalate: { badge: 'bp-tol-urgent', border: 'var(--urgent)', Icon: ShieldAlert },
}

const FRESHNESS_STYLE: Record<string, string> = {
  fresh: 'bp-tol-ok',
  stale: 'bp-tol-urgent',
  unknown: 'bp-tol-high',
}

const EMPTY_AUDIENCE: SessionAudienceContext = {
  visibility: 'internal',
  plan_tier: '',
  region: '',
  language: '',
  product_version: '',
}

function createRequestRef() {
  return `copilot-query:${crypto.randomUUID()}`
}
function compactAudienceContext(context: SessionAudienceContext): SessionAudienceContext {
  const brand = context.brand?.trim()
  const productLine = context.product_line?.trim()
  const planTier = context.plan_tier?.trim()
  const region = context.region?.trim()
  const language = context.language?.trim()
  const productVersion = context.product_version?.trim()
  return {
    visibility: context.visibility,
    ...(brand ? { brand } : {}),
    ...(productLine ? { product_line: productLine } : {}),
    ...(planTier ? { plan_tier: planTier } : {}),
    ...(region ? { region } : {}),
    ...(language ? { language } : {}),
    ...(productVersion ? { product_version: productVersion } : {}),
  }
}


export default function Copilot() {
  const { t } = useTranslation()
  const [manifest, setManifest] = useState<SessionBridgeManifest | null>(null)
  const [manifestError, setManifestError] = useState<unknown>(null)
  const [manifestLoading, setManifestLoading] = useState(true)
  const [query, setQuery] = useState('')
  const [audience, setAudience] = useState<SessionAudienceContext>(EMPTY_AUDIENCE)
  const [result, setResult] = useState<SessionQueryResponse | null>(null)
  const [queryError, setQueryError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)
  const manifestRequestKey = useRef(0)
  const queryRequestKey = useRef(0)

  const loadManifest = () => {
    const requestKey = ++manifestRequestKey.current
    setManifestLoading(true)
    setManifestError(null)
    fetchSessionBridgeManifest()
      .then((next) => {
        if (requestKey === manifestRequestKey.current) setManifest(next)
      })
      .catch((error: unknown) => {
        if (requestKey === manifestRequestKey.current) setManifestError(error)
      })
      .finally(() => {
        if (requestKey === manifestRequestKey.current) setManifestLoading(false)
      })
  }

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) loadManifest() })
    return () => {
      active = false
      manifestRequestKey.current += 1
      queryRequestKey.current += 1
    }
  }, [])

  const updateAudience = (field: keyof SessionAudienceContext, value: string) => {
    setAudience((current) => ({ ...current, [field]: value }))
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedQuery = query.trim()
    if (!normalizedQuery || !manifest || manifest.contract_version !== SESSION_CONTRACT_VERSION) return

    const requestKey = ++queryRequestKey.current
    setSubmitting(true)
    setQueryError(null)
    setResult(null)
    submitSessionQuery({
      request_ref: createRequestRef(),
      query: normalizedQuery,
      channel: 'copilot',
      audience_context: compactAudienceContext(audience),
      limit: 5,
    })
      .then((next) => {
        if (requestKey === queryRequestKey.current) setResult(next)
      })
      .catch((error: unknown) => {
        if (requestKey === queryRequestKey.current) setQueryError(error)
      })
      .finally(() => {
        if (requestKey === queryRequestKey.current) setSubmitting(false)
      })
  }

  if (manifestLoading && !manifest) return <PageSkeleton />
  if (manifestError && !manifest) return <RequestErrorState error={manifestError} onRetry={loadManifest} />

  const contractReady = manifest?.contract_version === SESSION_CONTRACT_VERSION

  return (
    <div className="space-y-4">
      <header className="bp-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="bp-label">{t('copilot.eyebrow')}</div>
            <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('copilot.title')}</h1>
            <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">{t('copilot.summary')}</p>
          </div>
          <dl className="grid shrink-0 grid-cols-2 gap-x-5 gap-y-2 font-mono text-xs">
            <Meta label={t('copilot.contract')} value={manifest?.contract_version ?? '—'} />
            <Meta label={t('copilot.toolsVisible')} value={String(manifest?.visible_tools.length ?? 0)} />
            <Meta label={t('copilot.schema')} value={manifest?.schema_fingerprint?.slice(0, 12) ?? '—'} />
            <Meta label={t('copilot.memoryTruth')} value="false" tone="var(--ok)" />
          </dl>
        </div>
      </header>

      {!contractReady ? (
        <section role="alert" className="bp-panel p-4" style={{ borderColor: 'var(--urgent)' }}>
          <h2 className="font-mono text-sm font-bold" style={{ color: 'var(--urgent)' }}>{t('copilot.contractMismatch')}</h2>
          <p className="mt-1 font-mono text-xs text-muted-foreground">
            {t('copilot.contractMismatchDetail', { expected: SESSION_CONTRACT_VERSION, actual: manifest?.contract_version ?? '—' })}
          </p>
        </section>
      ) : null}

      <form onSubmit={handleSubmit} className="bp-panel p-5" aria-labelledby="copilot-query-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="copilot-query-heading" className="font-mono text-base font-bold">{t('copilot.queryHeading')}</h2>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{t('copilot.queryHint')}</p>
          </div>
          <span className="bp-tol bp-tol-flat">{t('copilot.singleQuery')}</span>
        </div>

        <div className="mt-4">
          <label htmlFor="copilot-query" className="mb-1.5 block font-mono text-xs font-semibold">{t('copilot.queryLabel')}</label>
          <textarea
            id="copilot-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            required
            maxLength={4000}
            disabled={submitting}
            rows={4}
            className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm outline-none transition-colors placeholder:text-faint focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            placeholder={t('copilot.queryPlaceholder')}
          />
          <div className="mt-1 flex justify-between gap-3 font-mono text-xs text-faint">
            <span>{t('copilot.queryLimit')}</span>
            <span>{query.length} / 4000</span>
          </div>
        </div>

        <fieldset disabled={submitting} className="mt-5">
          <legend className="font-mono text-xs font-semibold">{t('copilot.audienceHeading')}</legend>
          <p className="mt-1 font-mono text-xs text-muted-foreground">{t('copilot.audienceHint')}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <FormField label={t('copilot.visibility')} htmlFor="copilot-visibility" required>
              <select
                id="copilot-visibility"
                value={audience.visibility}
                onChange={(event) => updateAudience('visibility', event.target.value)}
                required
                className="h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="internal">{t('copilot.visibilityInternal')}</option>
                <option value="external">{t('copilot.visibilityExternal')}</option>
              </select>
            </FormField>
            <AudienceInput id="copilot-plan" label={t('copilot.plan')} value={audience.plan_tier ?? ''} onChange={(value) => updateAudience('plan_tier', value)} />
            <AudienceInput id="copilot-region" label={t('copilot.region')} value={audience.region ?? ''} onChange={(value) => updateAudience('region', value)} />
            <AudienceInput id="copilot-version" label={t('copilot.version')} value={audience.product_version ?? ''} onChange={(value) => updateAudience('product_version', value)} />
            <AudienceInput id="copilot-language" label={t('copilot.language')} value={audience.language ?? ''} onChange={(value) => updateAudience('language', value)} />
          </div>
        </fieldset>

        <div className="mt-5 flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={!contractReady || submitting || !query.trim()}>
            {submitting ? <RotateCw aria-hidden="true" size={14} className="animate-spin" /> : <FileSearch aria-hidden="true" size={14} />}
            {submitting ? t('copilot.submitting') : t('copilot.submit')}
          </Button>
          <p className="font-mono text-xs text-faint">{t('copilot.submitBoundary')}</p>
        </div>
      </form>

      <div role="status" aria-live="polite" className="sr-only">
        {submitting ? t('copilot.submitting') : result ? t('copilot.resultReady') : ''}
      </div>

      {queryError ? <RequestErrorState error={queryError} onRetry={() => {
        const form = document.getElementById('copilot-query')?.closest('form')
        form?.requestSubmit()
      }} /> : null}
      {result ? <GovernedResult result={result} /> : null}
    </div>
  )
}

function Meta({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <dt className="text-faint">{label}</dt>
      <dd className="mt-0.5 max-w-36 truncate font-semibold" style={tone ? { color: tone } : undefined} title={value}>{value}</dd>
    </div>
  )
}

function FormField({ label, htmlFor, required, children }: { label: string; htmlFor: string; required?: boolean; children: ReactNode }) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block font-mono text-xs text-muted-foreground">
        {label}{required ? <span aria-hidden="true" style={{ color: 'var(--urgent)' }}> *</span> : null}
      </label>
      {children}
    </div>
  )
}

function AudienceInput({ id, label, value, onChange }: { id: string; label: string; value: string; onChange: (value: string) => void }) {
  const { t } = useTranslation()
  return (
    <FormField label={label} htmlFor={id}>
      <input
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        maxLength={120}
        className="h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none placeholder:text-faint focus-visible:ring-2 focus-visible:ring-ring"
        placeholder={t('copilot.optional')}
      />
    </FormField>
  )
}

function GovernedResult({ result }: { result: SessionQueryResponse }) {
  const { t } = useTranslation()
  const disposition = result.data.governance.state
  const style = DISPOSITION_STYLE[disposition]
  const Icon = style.Icon
  const answer = result.data.answer

  return (
    <section aria-labelledby="copilot-result-heading" className="space-y-4">
      <div className="bp-panel overflow-hidden" style={{ borderColor: `color-mix(in srgb, ${style.border} 55%, transparent)` }}>
        <div className="bp-dim flex flex-wrap items-center gap-2 px-4 py-3">
          <Icon aria-hidden="true" size={16} style={{ color: style.border }} />
          <h2 id="copilot-result-heading" className="font-mono text-sm font-bold">{t('copilot.resultHeading')}</h2>
          <span className={`bp-tol ${style.badge}`}>{t(`copilot.disposition.${disposition}`)}</span>
          <span className="ml-auto font-mono text-xs text-faint">{result.data.request_ref}</span>
        </div>
        <div className="p-4">
          <p className="font-mono text-sm leading-relaxed">{result.summary}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {result.data.governance.codes.map((code) => <span key={code} className="bp-tol bp-tol-flat">{code}</span>)}
          </div>
          {result.data.governance.directives.length > 0 ? (
            <div className="mt-4">
              <div className="bp-label">{t('copilot.directives')}</div>
              <ul className="mt-2 space-y-1 font-mono text-xs text-muted-foreground">
                {result.data.governance.directives.map((directive) => <li key={directive}>• {directive}</li>)}
              </ul>
            </div>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="bp-panel p-4">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-mono text-sm font-bold">{t('copilot.answer')}</h3>
            {answer ? <span className={`bp-tol ${FRESHNESS_STYLE[answer.freshness] ?? 'bp-tol-flat'}`}>{answer.freshness}</span> : null}
            {answer ? <span className="bp-tol bp-tol-flat">{answer.publication_status}</span> : null}
          </div>
          {answer ? (
            <div className="mt-3">
              <div className="font-mono text-base font-bold">{answer.title}</div>
              <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{answer.snippet}</p>
              {answer.content ? <ContentProjection content={answer.content} /> : (
                <p className="mt-4 border-l-2 border-border pl-3 font-mono text-xs leading-relaxed text-muted-foreground">
                  {t('copilot.contentWithheld')}
                </p>
              )}
              <dl className="mt-4 grid grid-cols-2 gap-3 font-mono text-xs">
                <Meta label={t('copilot.usage')} value={answer.usage} />
                <Meta label={t('copilot.externalUse')} value={String(answer.direct_external_use)} tone={answer.direct_external_use ? 'var(--ok)' : 'var(--high)'} />
              </dl>
            </div>
          ) : (
            <p className="mt-3 font-mono text-xs leading-relaxed text-muted-foreground">{t('copilot.noAnswer')}</p>
          )}
        </div>

        <ContinuityPanel result={result} />
      </div>

      <TracePanel trace={result.data.source_trace} objectId={answer?.object_id ?? null} />
      <FeedbackPanel key={result.data.request_ref} result={result} />
    </section>
  )
}

function FeedbackPanel({ result }: { result: SessionQueryResponse }) {
  const { t } = useTranslation()
  const [signalType, setSignalType] = useState<SessionFeedbackSignalType>('answer_accepted')
  const [notes, setNotes] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [receipt, setReceipt] = useState<SessionFeedbackResponse | null>(null)
  const [payload, setPayload] = useState<Parameters<typeof submitSessionFeedback>[0] | null>(null)
  const objectId = result.data.answer?.object_id ?? result.data.governance_context.object_id ?? undefined

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    let requestPayload = payload
    if (!requestPayload) {
      requestPayload = {
        command_id: `copilot-feedback:${crypto.randomUUID()}`,
        signal_type: signalType,
        audience_context: compactAudienceContext(result.data.audience_context),
        ...(objectId ? { object_id: objectId } : {}),
        ...(notes.trim() ? { notes: notes.trim() } : {}),
        source_context_ref: result.data.request_ref,
      }
      setPayload(requestPayload)
    }
    setPending(true)
    setError(null)
    submitSessionFeedback(requestPayload)
      .then((next) => {
        if (next.status !== 'success' || next.persisted !== true) {
          throw new Error(next.errors.join(', ') || next.summary)
        }
        setReceipt(next)
      })
      .catch((nextError: unknown) => setError(nextError))
      .finally(() => setPending(false))
  }

  const attempted = payload !== null
  return (
    <section aria-labelledby="copilot-feedback-heading" className="bp-panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="copilot-feedback-heading" className="font-mono text-sm font-bold">{t('copilot.feedbackTitle')}</h3>
          <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{t('copilot.feedbackNote')}</p>
        </div>
        <span className="bp-tol bp-tol-flat">{result.data.request_ref}</span>
      </div>
      {receipt ? (
        <div role="status" className="mt-4 border px-3 py-3" style={{ borderColor: 'color-mix(in srgb, var(--ok) 45%, transparent)' }}>
          <div className="flex flex-wrap items-center gap-2">
            <span className="bp-stamp" style={{ color: 'var(--ok)' }}>{t('copilot.feedbackPersisted')}</span>
            {receipt.replayed ? <span className="bp-tol bp-tol-flat">{t('copilot.feedbackReplayed')}</span> : null}
            {receipt.routing_state ? <span className="bp-tol bp-tol-high">{receipt.routing_state}</span> : null}
          </div>
          <p className="mt-2 font-mono text-xs text-muted-foreground">{receipt.summary}</p>
          <p className="mt-2 break-all font-mono text-xs text-faint">{receipt.trace_ref ?? receipt.signal_id ?? '—'}</p>
          <p className="mt-2 font-mono text-xs text-faint">{t('copilot.feedbackBoundary')}</p>
        </div>
      ) : (
        <form onSubmit={submit} className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('copilot.feedbackType')}</span>
              <select value={signalType} disabled={attempted || pending} onChange={(event) => setSignalType(event.target.value as SessionFeedbackSignalType)} className="h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60">
                {(['answer_accepted', 'low_rating', 'stale_answer', 'unsupported_answer', 'escalated', 'human_rewrite'] as const).map((type) => (
                  <option key={type} value={type}>{t(`copilot.feedback.${type}`)}</option>
                ))}
              </select>
            </label>
            <label>
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('copilot.feedbackNotes')}</span>
              <input value={notes} disabled={attempted || pending} onChange={(event) => setNotes(event.target.value)} maxLength={10000} className="h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60" />
            </label>
          </div>
          {error ? <RequestErrorState error={error} compact /> : null}
          <Button type="submit" className="min-h-11" disabled={pending}>
            {pending ? <RotateCw aria-hidden="true" size={14} className="animate-spin" /> : null}
            {pending ? t('copilot.feedbackSubmitting') : attempted ? t('copilot.feedbackRetry') : t('copilot.feedbackSubmit')}
          </Button>
        </form>
      )}
    </section>
  )
}

function ContentProjection({ content }: { content: Record<string, unknown> }) {
  return (
    <dl className="mt-4 space-y-3">
      {Object.entries(content).map(([key, value]) => (
        <div key={key} className="bp-dim px-3 py-2">
          <dt className="font-mono text-xs uppercase tracking-wide text-faint">{key.replaceAll('_', ' ')}</dt>
          <dd className="mt-1 font-mono text-sm leading-relaxed text-foreground"><ContentValue value={value} /></dd>
        </div>
      ))}
    </dl>
  )
}

function ContentValue({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return <span>—</span>
    return <ul className="space-y-1">{value.map((item, index) => <li key={index}>• {String(item)}</li>)}</ul>
  }
  if (value === null || value === undefined || value === '') return <span>—</span>
  if (typeof value === 'object') return <span>{JSON.stringify(value)}</span>
  return <span>{String(value)}</span>
}

function ContinuityPanel({ result }: { result: SessionQueryResponse }) {
  const { t } = useTranslation()
  const continuity = result.data.continuity
  return (
    <div className="bp-panel p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-mono text-sm font-bold">{t('copilot.continuity')}</h3>
        <span className="bp-tol bp-tol-flat">{continuity.state}</span>
        <span className="bp-tol bp-tol-ok">{t('copilot.revalidated')}</span>
      </div>
      <dl className="mt-3 space-y-2 font-mono text-xs">
        <div className="flex justify-between gap-4"><dt className="text-faint">{t('copilot.memoryTruth')}</dt><dd className="font-bold" style={{ color: 'var(--ok)' }}>false</dd></div>
        <div className="flex justify-between gap-4"><dt className="text-faint">{t('copilot.objectVersion')}</dt><dd>{continuity.governance_context.object_version ?? '—'}</dd></div>
        <div className="flex justify-between gap-4"><dt className="text-faint">{t('copilot.traceRef')}</dt><dd className="max-w-56 break-all text-right">{continuity.governance_context.trace_ref ?? '—'}</dd></div>
      </dl>
      <div className="mt-4">
        <div className="bp-label">{t('copilot.continuityReasons')}</div>
        <ul className="mt-2 space-y-1 font-mono text-xs text-muted-foreground">
          {continuity.reasons.map((reason) => <li key={reason}>• {reason}</li>)}
        </ul>
      </div>
    </div>
  )
}

function TracePanel({ trace, objectId }: { trace: SourceTrace | null; objectId: string | null }) {
  const { t } = useTranslation()
  if (!trace) {
    return (
      <div className="bp-panel p-4">
        <h3 className="font-mono text-sm font-bold">{t('copilot.trace')}</h3>
        <p className="mt-2 font-mono text-xs text-muted-foreground">{t('copilot.noTrace')}</p>
      </div>
    )
  }
  return (
    <div className="bp-panel overflow-hidden">
      <div className="bp-dim flex flex-wrap items-center gap-2 px-4 py-3">
        <h3 className="font-mono text-sm font-bold">{t('copilot.trace')}</h3>
        <span className={`bp-tol ${FRESHNESS_STYLE[trace.freshness] ?? 'bp-tol-flat'}`}>{trace.freshness}</span>
        <span className="font-mono text-xs text-faint">v{trace.version}</span>
        {objectId ? (
          <Link
            to={`/console/propagation?object_ref=${encodeURIComponent(objectId)}`}
            className="ml-auto inline-flex items-center gap-1 font-mono text-xs font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {t('copilot.openPropagation')} <ArrowUpRight aria-hidden="true" size={13} />
          </Link>
        ) : null}
      </div>
      <div className="grid gap-px bg-border lg:grid-cols-2">
        <section className="bg-card p-4" aria-labelledby="copilot-citations-heading">
          <h4 id="copilot-citations-heading" className="bp-label">{t('copilot.citations')}</h4>
          <div className="mt-3 space-y-2">
            {trace.evidence_refs.map((evidence) => (
              <article key={evidence.evidence_id} className="bp-dim px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-semibold">{evidence.title}</span>
                  <span className={`bp-tol ${FRESHNESS_STYLE[evidence.freshness] ?? 'bp-tol-flat'}`}>{evidence.freshness}</span>
                </div>
                <div className="mt-1 break-all font-mono text-xs text-faint">{evidence.source_ref} · {evidence.excerpt_ref}</div>
                <div className="mt-1 font-mono text-xs text-muted-foreground">{evidence.updated_at ?? t('copilot.updatedUnknown')}</div>
              </article>
            ))}
            {trace.evidence_refs.length === 0 ? <p className="font-mono text-xs text-muted-foreground">{t('copilot.noCitations')}</p> : null}
          </div>
        </section>
        <section className="bg-card p-4" aria-labelledby="copilot-publication-heading">
          <h4 id="copilot-publication-heading" className="bp-label">{t('copilot.publicationTrace')}</h4>
          <div className="mt-3 space-y-2">
            {trace.publication_records.map((record) => (
              <div key={`${record.channel}:${record.publication_state}`} className="bp-dim flex items-center justify-between gap-3 px-3 py-2 font-mono text-xs">
                <span>{record.channel}</span>
                <span className="bp-tol bp-tol-flat">{record.publication_state}</span>
              </div>
            ))}
            {trace.publication_records.length === 0 ? <p className="font-mono text-xs text-muted-foreground">{t('copilot.noPublicationTrace')}</p> : null}
          </div>
          {trace.blind_spots.length > 0 ? (
            <div className="mt-4">
              <div className="bp-label">{t('copilot.blindSpots')}</div>
              <ul className="mt-2 space-y-1 font-mono text-xs text-muted-foreground">
                {trace.blind_spots.map((spot) => <li key={spot}>• {spot}</li>)}
              </ul>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  )
}
