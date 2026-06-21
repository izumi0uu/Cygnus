import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Check } from 'lucide-react'
import { fetchSourceBlindnessSurface, type SourceBlindnessSurface, type SourceBlindnessContext } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'

// freshness → tol style (stale = urgent heat, fresh = ok, unknown = muted)
const FRESH_TOL: Record<string, string> = { stale: 'bp-tol-urgent', fresh: 'bp-tol-ok', unknown: 'bp-tol-flat' }
const FRESH_COLOR: Record<string, string> = { stale: 'var(--urgent)', fresh: 'var(--ok)', unknown: 'var(--medium)' }

// Source/evidence integrity health board — source-blindness risks as governance-loss cards.
// Sourced from the source-health surface (degraded source refs, freshness states, signal loss).
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
  const stale = rows.filter((c) => c.freshness_states.includes('stale')).length
  const surfaces = new Set(rows.flatMap((c) => c.affected_surfaces)).size
  const watched = new Set(rows.flatMap((c) => c.evidence_ids)).size
  const blindObjs = new Set(rows.map((c) => c.proposal_ref)).size
  const ok = Math.max(0, watched - blindObjs)

  return (
    <>
      <p className="mb-3 font-mono text-[12px] leading-relaxed text-muted-foreground">{data.summary}</p>

      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={rows.length} label={t('src.statSources')} dot="var(--urgent)" />
        <Stat n={stale} label={t('frame.urgent')} dot="var(--urgent)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
        <Stat n={watched} label={t('src.statWatched')} />
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {rows.map((c) => (
          <SourceCard key={c.proposal_ref} ctx={c} command={data.available_commands[0]} />
        ))}
      </div>

      {rows.length === 0 ? (
        <div className="bp-panel px-[18px] py-10 text-center font-mono text-sm text-muted-foreground">{t('src.empty')}</div>
      ) : ok > 0 ? (
        <div className="mt-4 flex items-center gap-2 bp-panel px-4 py-3 font-mono text-[13px] text-muted-foreground">
          <Check size={16} style={{ color: 'var(--ok)' }} />
          {t('src.okFmt', { n: ok })}
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
        <span className={`bp-tol ${FRESH_TOL[worstFresh] ?? 'bp-tol-flat'} ml-auto`}>{t(`urgency.${worstFresh === 'stale' ? 'urgent' : 'medium'}`)}</span>
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
                <span className="h-1.5 w-1.5 rotate-45" style={{ background: FRESH_COLOR[ctx.freshness_states[i] ?? 'unknown'] ?? 'var(--faint)' }} />
                <span className="text-muted-foreground">{ref}</span>
                <span className="text-faint">{ctx.source_types[i] ?? ''} · {ctx.freshness_states[i] ?? 'unknown'}</span>
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
