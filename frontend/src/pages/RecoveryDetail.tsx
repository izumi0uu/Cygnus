import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ArrowLeft } from 'lucide-react'
import {
  fetchRecoveryWindow,
  fetchDownstreamRealityCheck,
  type RecoveryWindowSurface,
  type DownstreamRealityCheckSurface,
  type RecoveryMetricDelta,
  type AlignmentPlaneChange,
  type ResidualRisk,
  type DownstreamFeedbackSignal,
  type MismatchByAudience,
} from '@/lib/api'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'

// recovery_status → heat color + tol class
const ASSESSMENT_CHIP: Record<string, string> = {
  recovery_confirmed: 'bp-tol-ok',
  recovery_incomplete: 'bp-tol-high',
  false_recovery: 'bp-tol-urgent',
  drift_rebound: 'bp-tol-urgent',
}
const METRIC_COLOR: Record<string, string> = {
  improved: 'var(--ok)',
  worsened: 'var(--urgent)',
  flat: 'var(--faint)',
}
const PLANE_COLOR: Record<string, string> = {
  aligned: 'var(--ok)',
  partial: 'var(--medium)',
  misaligned: 'var(--urgent)',
  split_brain: 'var(--high)',
}
const SEVERITY_CHIP: Record<string, string> = {
  critical: 'bp-tol-urgent',
  elevated: 'bp-tol-high',
  emerging: 'bp-tol-high',
  watch: 'bp-tol-flat',
}
const SIGNAL_CHIP: Record<string, string> = {
  copilot_accepted: 'bp-tol-ok',
  human_rewrite: 'bp-tol-high',
  reject_after_suggestion: 'bp-tol-high',
  escalation_after_suggestion: 'bp-tol-urgent',
  unresolved_conversation: 'bp-tol-urgent',
}

export default function RecoveryDetail() {
  const { commandId } = useParams<{ commandId: string }>()
  const { t } = useTranslation()
  const v = useVocab()
  const [window, setWindow] = useState<RecoveryWindowSurface | null>(null)
  const [reality, setReality] = useState<DownstreamRealityCheckSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!commandId) return
    setLoading(true)
    setError(null)
    Promise.all([
      fetchRecoveryWindow(commandId).catch((e) => { throw new Error(`window: ${e}`) }),
      fetchDownstreamRealityCheck(commandId).catch((e) => { throw new Error(`reality: ${e}`) }),
    ])
      .then(([w, r]) => { setWindow(w); setReality(r) })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [commandId])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>{error}</div>
        <Link to="/console" className="mt-3 inline-block font-mono text-[11px] text-primary hover:underline">{t('recovery.backToOverview')}</Link>
      </div>
    )
  if (!window) return null

  const w = window
  const align = w.before_after_alignment_view
  const judge = w.closure_judge
  const metrics = [w.rewrite_delta, w.drift_delta, w.escalation_delta, w.coverage_gap_delta, w.publish_conflict_delta]
  const unacceptable = w.residual_risks.filter((r) => !r.acceptable_residual)
  const improvedCount = metrics.filter((m) => m.improved).length

  return (
    <>
      {/* header */}
      <div className="mb-4">
        <Link to="/console" className="inline-flex items-center gap-1 font-mono text-[11px] text-muted-foreground hover:text-primary">
          <ArrowLeft size={13} />{t('recovery.backToOverview')}
        </Link>
        <div className="mt-2 flex items-center gap-2.5">
          <span className={`chip ${ASSESSMENT_CHIP[w.assessment] ?? 'chip'}`}>{v.recoveryAssessment(w.assessment)}</span>
          <span className="font-mono text-[11px] text-faint">{w.command_ref.command_type}</span>
          <h2 className="text-lg font-bold leading-tight">{w.command_ref.object_title}</h2>
          <span className="ml-auto font-mono text-[10px] text-faint">{w.command_ref.issued_by} · {w.command_ref.issued_at}</span>
        </div>
        <p className="mt-1.5 max-w-[80ch] text-[13px] leading-relaxed text-muted-foreground">{w.summary}</p>
      </div>

      {/* stat row */}
      <div className="mb-4 flex flex-wrap gap-2.5">
        <ScoreStat label={t('recovery.beforeScore')} value={align.before_score} color="var(--medium)" />
        <span className="self-center font-mono text-[14px] text-faint">→</span>
        <ScoreStat label={t('recovery.afterScore')} value={align.after_score} color="var(--ok)" />
        <Stat n={improvedCount} label={t('recovery.improved')} dot="var(--ok)" />
        <Stat n={w.residual_risks.length} label={t('recovery.residualRisks')} dot={unacceptable.length > 0 ? 'var(--urgent)' : 'var(--ok)'} />
        <div className="flex min-w-[130px] flex-1 items-center gap-2 rounded-xl border border-border bg-card p-4 shadow-card">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: judge.closeable ? 'var(--ok)' : 'var(--urgent)' }} />
          <span className="font-mono text-[12px] font-bold" style={{ color: judge.closeable ? 'var(--ok)' : 'var(--urgent)' }}>
            {judge.closeable ? t('recovery.closeable') : t('recovery.notCloseable')}
          </span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* left: metrics delta + alignment planes */}
        <div className="flex flex-col gap-4">
          {/* metrics delta table */}
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
            <div className="px-4 pt-3.5 text-[13px] font-bold">{t('recovery.metrics')}</div>
            <div className="mt-1.5">
              {metrics.map((m) => <MetricRow key={m.metric_key} delta={m} />)}
            </div>
          </div>

          {/* alignment planes */}
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
            <div className="px-4 pt-3.5 text-[13px] font-bold">{t('recovery.alignment')}</div>
            <div className="px-4 pb-3.5 pt-2">
              <div className="mb-3 flex items-center gap-3">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-[18px] font-bold" style={{ color: 'var(--medium)' }}>{align.before_score.toFixed(2)}</span>
                  <span className="font-mono text-[10px] text-faint">→</span>
                  <span className="font-mono text-[18px] font-bold" style={{ color: 'var(--ok)' }}>{align.after_score.toFixed(2)}</span>
                </div>
                <span className="font-mono text-[11px]" style={{ color: align.delta >= 0 ? 'var(--ok)' : 'var(--urgent)' }}>
                  {align.delta >= 0 ? '+' : ''}{align.delta.toFixed(3)}
                </span>
              </div>
              <div className="flex flex-col gap-2">
                {align.plane_changes.map((p) => <PlaneRow key={p.plane_key} plane={p} />)}
              </div>
              {align.residual_truth_planes.length > 0 && (
                <div className="mt-3 flex flex-wrap items-center gap-1.5">
                  <span className="font-mono text-[10px] uppercase text-faint">residual:</span>
                  {align.residual_truth_planes.map((p) => <span key={p} className="chip chip-medium">{p}</span>)}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* right: closure judge + residual risks */}
        <div className="flex flex-col gap-4">
          {/* closure judge */}
          <div className="rounded-xl border border-border bg-card p-4 shadow-soft">
            <div className="mb-2.5 font-mono text-[10px] uppercase tracking-widest text-faint">{t('recovery.closure')}</div>
            <div className="flex items-center gap-2">
              <span className={`chip ${ASSESSMENT_CHIP[judge.assessment] ?? 'chip'}`}>{v.recoveryAssessment(judge.assessment)}</span>
              <span className="chip">{v.recoveryDecision(judge.recommendation)}</span>
            </div>
            <p className="mt-2.5 text-[12.5px] leading-relaxed text-muted-foreground">{judge.rationale}</p>
            {judge.improved_metrics.length > 0 && (
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {judge.improved_metrics.map((m) => <span key={m} className="chip">{m}</span>)}
              </div>
            )}
            {judge.closure_blockers.length > 0 && (
              <div className="mt-3 border-t border-border pt-2.5">
                <div className="mb-1.5 font-mono text-[10px] uppercase text-faint">{t('recovery.closureBlockers')}</div>
                <ul className="space-y-1">
                  {judge.closure_blockers.map((b, i) => (
                    <li key={i} className="flex items-start gap-2 text-[12px] text-muted-foreground">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: 'var(--urgent)' }} />{b}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* residual risks */}
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
            <div className="flex items-baseline px-4 pt-3.5">
              <div className="text-[13px] font-bold">{t('recovery.residualRisks')}</div>
              <span className="ml-auto font-mono text-[11px] text-faint">{w.residual_risks.length}</span>
            </div>
            <div className="mt-1.5">
              {w.residual_risks.length === 0 ? (
                <div className="px-4 py-6 text-center text-sm text-muted-foreground">{t('recovery.noResidualRisks')}</div>
              ) : (
                w.residual_risks.map((r) => <RiskRow key={r.risk_id} risk={r} />)
              )}
            </div>
          </div>
        </div>
      </div>

      {/* downstream reality check */}
      {reality && (
        <RealityCheckSection reality={reality} />
      )}

      {/* footer: continue + send-back commands */}
      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-border pt-4">
        {w.continue_commands.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase text-faint">{t('recovery.continueCommands')}</span>
            {w.continue_commands.map((cmd) => <CmdButton key={cmd} command={cmd} />)}
          </div>
        )}
        {reality && reality.send_back_commands.length > 0 && (
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span className="font-mono text-[10px] uppercase text-faint">{t('recovery.sendBackCommands')}</span>
            {reality.send_back_commands.map((cmd) => <CmdButton key={cmd} command={cmd} />)}
          </div>
        )}
      </div>

      {/* monitor targets */}
      {judge.monitor_targets.length > 0 && (
        <div className="mt-3 rounded-lg border border-border bg-muted/50 px-4 py-2.5">
          <span className="font-mono text-[10px] uppercase text-faint">{t('recovery.monitorTargets')} </span>
          <span className="font-mono text-[11px] text-muted-foreground">{judge.monitor_targets.join(' · ')}</span>
        </div>
      )}
    </>
  )
}

function MetricRow({ delta }: { delta: RecoveryMetricDelta }) {
  const v = useVocab()
  const color = METRIC_COLOR[delta.status] ?? 'var(--faint)'
  const arrow = delta.delta < 0 ? '↓' : delta.delta > 0 ? '↑' : '→'
  return (
    <div className="border-b border-border px-4 py-2.5 last:border-b-0">
      <div className="flex items-center gap-2.5">
        <span className="min-w-0 flex-1 text-[13px] font-medium">{delta.label}</span>
        <span className="font-mono text-[13px] text-muted-foreground">{delta.before_value}</span>
        <span className="font-mono text-[10px] text-faint">→</span>
        <span className="font-mono text-[15px] font-bold" style={{ color }}>{delta.after_value}</span>
        <span className="font-mono text-[12px] font-bold" style={{ color }}>{arrow}{Math.abs(delta.delta)}</span>
        <span className={`chip ${delta.status === 'improved' ? 'chip' : delta.status === 'worsened' ? 'chip-urgent' : 'chip-medium'}`}>{v.metricStatus(delta.status)}</span>
      </div>
      {delta.explanation && <p className="mt-1 font-mono text-[10px] leading-relaxed text-faint">{delta.explanation}</p>}
    </div>
  )
}

function PlaneRow({ plane }: { plane: AlignmentPlaneChange }) {
  const v = useVocab()
  const beforeColor = PLANE_COLOR[plane.before_state] ?? 'var(--faint)'
  const afterColor = PLANE_COLOR[plane.after_state] ?? 'var(--faint)'
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <div className="flex items-center gap-2">
        <span className="text-[12.5px] font-medium">{plane.label}</span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10px]">
          <span style={{ color: beforeColor }}>{v.truthPlane(plane.before_state)}</span>
          <span className="text-faint">→</span>
          <span style={{ color: afterColor }}>{v.truthPlane(plane.after_state)}</span>
        </span>
      </div>
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
          <span className="block h-full rounded-full" style={{ width: `${plane.before_score * 100}%`, background: beforeColor }} />
        </div>
        <span className="font-mono text-[10px] text-faint">{plane.before_score.toFixed(2)}</span>
        <span className="font-mono text-[10px] text-faint">→</span>
        <span className="font-mono text-[10px] font-bold" style={{ color: afterColor }}>{plane.after_score.toFixed(2)}</span>
        {plane.improved && <span className="h-1.5 w-1.5 rounded-full" style={{ background: 'var(--ok)' }} />}
      </div>
      {plane.residual_reasons.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {plane.residual_reasons.map((r, i) => (
            <li key={i} className="font-mono text-[10px] leading-relaxed text-faint">· {r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function RiskRow({ risk }: { risk: ResidualRisk }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div className="border-b border-border px-4 py-3 last:border-b-0">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-semibold">{risk.label}</span>
        <span className={`chip ${SEVERITY_CHIP[risk.severity] ?? 'chip'}`}>{v.severity(risk.severity)}</span>
        <span className="chip" style={{ fontSize: '9px' }}>{risk.truth_plane}</span>
        <span className={`chip ml-auto ${risk.acceptable_residual ? 'chip' : 'chip-urgent'}`}>
          {risk.acceptable_residual ? t('recovery.acceptable') : t('recovery.unacceptable')}
        </span>
      </div>
      <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{risk.summary}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2 font-mono text-[10px] text-faint">
        {risk.owner && <span>@{risk.owner}</span>}
        {risk.blocking_surface && <span>· {v.surface(risk.blocking_surface)}</span>}
        {risk.recommended_command && (
          <span className="ml-auto"><CmdButton command={risk.recommended_command} className="text-[10px]" /></span>
        )}
      </div>
    </div>
  )
}

function RealityCheckSection({ reality }: { reality: DownstreamRealityCheckSurface }) {
  const { t } = useTranslation()
  const v = useVocab()
  const strip = reality.reality_check_strip
  return (
    <div className="mt-5 rounded-xl border border-border bg-card shadow-soft">
      <div className="px-4 pt-3.5 text-[13px] font-bold">{t('recovery.realityCheck')}</div>
      <p className="px-4 pb-2 pt-1 text-[12px] leading-relaxed text-muted-foreground">{reality.summary}</p>

      {/* reality strip */}
      <div className="mx-4 mb-3 rounded-lg border border-border bg-muted/50 px-3.5 py-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: strip.frontline_changed ? 'var(--ok)' : 'var(--faint)' }} />
            <span className="text-[12.5px] font-semibold" style={{ color: strip.frontline_changed ? 'var(--ok)' : 'var(--faint)' }}>
              {strip.frontline_changed ? t('recovery.frontlineChanged') : t('recovery.frontlineNotChanged')}
            </span>
          </span>
          <span className="font-mono text-[11px]" style={{ color: 'var(--urgent)' }}>{strip.unresolved_signal_count} {t('recovery.unresolvedSignals')}</span>
        </div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {strip.converging_surfaces.length > 0 && (
            <div>
              <div className="mb-1 font-mono text-[9px] uppercase text-faint">{t('recovery.converging')}</div>
              <div className="flex flex-wrap gap-1.5">{strip.converging_surfaces.map((s) => <span key={s} className="chip">{v.surface(s)}</span>)}</div>
            </div>
          )}
          {strip.lagging_surfaces.length > 0 && (
            <div>
              <div className="mb-1 font-mono text-[9px] uppercase text-faint">{t('recovery.lagging')}</div>
              <div className="flex flex-wrap gap-1.5">{strip.lagging_surfaces.map((s) => <span key={s} className="chip chip-medium">{v.surface(s)}</span>)}</div>
            </div>
          )}
        </div>
        {strip.next_actions.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-border pt-2">
            <span className="font-mono text-[9px] uppercase text-faint">{t('recovery.nextActions')}</span>
            {strip.next_actions.map((a) => <span key={a} className="chip">{a.replace(/_/g, ' ')}</span>)}
          </div>
        )}
      </div>

      {/* feedback feed + mismatch by audience */}
      <div className="grid gap-4 px-4 pb-4 lg:grid-cols-2">
        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">{t('recovery.feedbackFeed')}</div>
          <div className="flex flex-col gap-1.5">
            {reality.feedback_feed.map((sig) => <FeedbackRow key={sig.signal_id} signal={sig} />)}
          </div>
        </div>
        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">{t('recovery.mismatchByAudience')}</div>
          <div className="overflow-hidden rounded-lg border border-border">
            <div className="grid grid-cols-[1fr_40px_40px_40px_40px] border-b border-border bg-muted px-2.5 py-1.5 font-mono text-[9px] uppercase text-faint">
              <span>{t('recovery.audienceLabel')}</span>
              <span className="text-center" style={{ color: 'var(--high)' }}>RW</span>
              <span className="text-center" style={{ color: 'var(--medium)' }}>RJ</span>
              <span className="text-center" style={{ color: 'var(--urgent)' }}>ESC</span>
              <span className="text-center" style={{ color: 'var(--urgent)' }}>UNS</span>
            </div>
            {reality.mismatch_by_audience.map((m) => <MismatchRow key={m.audience_label} mismatch={m} />)}
          </div>
        </div>
      </div>
    </div>
  )
}

function FeedbackRow({ signal }: { signal: DownstreamFeedbackSignal }) {
  const v = useVocab()
  return (
    <div className="rounded-lg border border-border px-3 py-2">
      <div className="flex items-center gap-2">
        <span className={`chip ${SIGNAL_CHIP[signal.signal_type] ?? 'chip'}`}>{v.feedbackSignal(signal.signal_type)}</span>
        <span className="truncate text-[12px] font-medium">{signal.audience_label}</span>
        <span className="ml-auto font-mono text-[10px] text-faint">{signal.event_at}</span>
      </div>
      <p className="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">{signal.summary}</p>
      <p className="mt-0.5 font-mono text-[10px] leading-relaxed text-faint">{signal.changed_behavior}</p>
    </div>
  )
}

function MismatchRow({ mismatch }: { mismatch: MismatchByAudience }) {
  return (
    <div className="grid grid-cols-[1fr_40px_40px_40px_40px] border-b border-border px-2.5 py-2 last:border-b-0">
      <span className="truncate text-[11.5px] font-medium">{mismatch.audience_label}</span>
      <MismatchCell n={mismatch.rewrite_count} color="var(--high)" />
      <MismatchCell n={mismatch.reject_count} color="var(--medium)" />
      <MismatchCell n={mismatch.escalation_count} color="var(--urgent)" />
      <MismatchCell n={mismatch.unresolved_count} color="var(--urgent)" />
    </div>
  )
}

function MismatchCell({ n, color }: { n: number; color: string }) {
  return (
    <span className="text-center font-mono text-[12px] font-semibold" style={{ color: n > 0 ? color : 'var(--faint)' }}>
      {n > 0 ? n : '—'}
    </span>
  )
}

function ScoreStat({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex min-w-[120px] items-baseline gap-2 rounded-xl border border-border bg-card px-4 py-3 shadow-card">
      <span className="h-2 w-2 self-center rounded-full" style={{ background: color }} />
      <span className="text-[22px] font-bold tracking-tight" style={{ color }}>{value.toFixed(2)}</span>
      <span className="font-mono text-[10px] uppercase tracking-wide text-muted-foreground">{label}</span>
    </div>
  )
}
