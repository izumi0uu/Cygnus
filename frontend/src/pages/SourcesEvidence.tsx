import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  fetchSourceBlindnessSurface,
  type SourceBlindnessContext,
  type SourceBlindnessSurface,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'
import { ObservationBanner } from '@/components/ObservationBanner'
import { SourceFailureCard } from '@/components/SourceFailureCard'

// Freshness labels report backend state without adding health or urgency semantics.
const FRESH_COLOR = 'var(--muted-foreground)'

// Source/evidence integrity surface: observed source failures plus complete governance contexts.
export default function SourcesEvidence() {
  const { t } = useTranslation()
  const [data, setData] = useState<SourceBlindnessSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchSourceBlindnessSurface().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(() => {
    fetchSourceBlindnessSurface().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }, [])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="bp-panel p-4">
        <div className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const rows = data.contexts
  const failures = data.source_observations
  const surfaces = new Set(rows.flatMap((c) => c.affected_surfaces)).size
  const showSummary = rows.length > 0 || failures.length > 0 || data.observation.state === 'ready'
  const emptyCopyKey = failures.length > 0
    ? 'observation.sourceFactsOnly'
    : data.observation.state === 'ready'
      ? 'observation.sourceEmptyReady'
      : data.observation.state === 'partial'
        ? 'observation.sourceEmptyPartial'
        : 'observation.sourceEmptyUnavailable'

  return (
    <>
      <ObservationBanner observation={data.observation} />
      {showSummary && (
        <p className="mb-3 font-mono text-[12px] leading-relaxed text-muted-foreground">{data.summary}</p>
      )}

      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={failures.length} label={t('observation.sourceFacts')} dot="var(--high)" />
        <Stat n={rows.length} label={t('observation.completeRisks')} dot="var(--urgent)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
      </div>

      {failures.length > 0 && (
        <section className="mb-5" aria-labelledby="source-facts-heading">
          <div id="source-facts-heading" className="mb-2 bp-label">{t('observation.sourceFacts')}</div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {failures.map((failure) => <SourceFailureCard key={failure.source_id} failure={failure} />)}
          </div>
        </section>
      )}

      {rows.length > 0 && (
        <section aria-labelledby="complete-source-risks-heading">
          <div id="complete-source-risks-heading" className="mb-2 bp-label">{t('observation.completeRisks')}</div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((c) => (
              <SourceCard key={c.proposal_ref} ctx={c} command={data.available_commands[0]} />
            ))}
          </div>
        </section>
      )}

      {rows.length === 0 ? (
        <div className="bp-panel px-[18px] py-10 text-center font-mono text-sm text-muted-foreground">
          {t(emptyCopyKey)}
        </div>
      ) : null}
    </>
  )
}


function SourceCard({ ctx, command }: { ctx: SourceBlindnessContext; command: string }) {
  const { t } = useTranslation()
  const v = useVocab()
  const worstFresh = ctx.freshness_states.includes('stale') ? 'stale' : ctx.freshness_states[0] ?? 'unknown'
  return (
    <div className="bp-panel overflow-hidden">
      <div className="bp-dim flex items-center gap-2 px-4 py-3">
        <span className="h-2 w-2 rotate-45" style={{ background: 'var(--urgent)' }} />
        <span className="font-mono text-[11px] font-bold uppercase tracking-wide" style={{ color: 'var(--urgent)' }}>{t('src.blind')}</span>
        <span className="bp-tol bp-tol-flat ml-auto">{v.freshness(worstFresh)}</span>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <div>
          <div className="font-mono text-[13px] font-semibold leading-tight">{ctx.title}</div>
          <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{ctx.proposal_ref} · {v.objectType(ctx.suggested_object_type)}</div>
        </div>

        <p className="text-[12.5px] leading-relaxed text-muted-foreground">{ctx.business_consequence}</p>

        {ctx.source_refs.length > 0 && (
          <div className="space-y-1">
            {ctx.source_refs.map((ref, i) => (
              <div key={ref} className="flex items-center gap-2 font-mono text-[10px]">
                <span className="h-1.5 w-1.5 rotate-45" style={{ background: FRESH_COLOR }} />
                <span className="text-muted-foreground">{ref}</span>
                <span className="text-faint">{v.evidenceSourceType(ctx.source_types[i] ?? '')} · {v.freshness(ctx.freshness_states[i] ?? 'unknown')}</span>
              </div>
            ))}
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {ctx.affected_surfaces.map((s) => <span key={s} className="bp-tol bp-tol-flat">{v.surface(s)}</span>)}
        </div>

        <div className="bp-dim pt-3">
          <p className="font-mono text-[10px] leading-relaxed text-faint">{ctx.signal_loss_summary}</p>
        </div>

        <div className="bp-dim flex items-center gap-2 pt-3">
          {command && <CmdButton command={command} className="ml-auto" />}
        </div>
      </div>
    </div>
  )
}
