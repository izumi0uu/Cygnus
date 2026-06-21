import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'
import { fetchGovernanceOverview, type GovernanceOverviewSurface } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { PageSkeleton } from '@/components/Skeleton'

const RECOVERY_TOL: Record<string, string> = {
  false_recovery: 'bp-tol-urgent',
  recovering: 'bp-tol-high',
  recovered: 'bp-tol-ok',
  closed: 'bp-tol-ok',
}
const RECOVERY_COLOR: Record<string, string> = {
  false_recovery: 'var(--urgent)',
  recovering: 'var(--high)',
  recovered: 'var(--ok)',
  closed: 'var(--ok)',
}

export default function Overview() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [data, setData] = useState<GovernanceOverviewSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchGovernanceOverview().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  const d = useMemo(() => {
    if (!data) return null
    const loops = data.open_loops
    const falseRecovery = loops.filter((l) => l.assessment === 'false_recovery').length
    const residualRisks = loops.reduce((s, l) => s + l.residual_risk_count, 0)
    const pendingPropagation = loops.reduce((s, l) => s + l.pending_propagation_count, 0)
    const topLoop = data.open_loops.find((l) => l.command_id === data.highest_leverage_command) ?? loops[0]
    return {
      total: loops.length,
      falseRecovery,
      residualRisks,
      pendingPropagation,
      ranks: [...data.open_loop_ranks].sort((a, b) => b.leverage_score - a.leverage_score),
      topLoop,
    }
  }, [data])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="bp-panel p-4">
        <div className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data || !d) return null

  return (
    <div className="min-h-full p-6 pb-10 pt-5">
      {/* Drawing header — title + revision stamp */}
      <div className="mb-5 flex items-end gap-4">
        <div>
          <div className="bp-label mb-1">DWG-001 · GOVERNANCE OVERVIEW</div>
          <h1 className="font-mono text-[22px] font-bold leading-none tracking-tight">{data.headline}</h1>
        </div>
        <span className="bp-stamp ml-auto" style={{ color: d.falseRecovery > 0 ? 'var(--urgent)' : 'var(--ok)', borderColor: d.falseRecovery > 0 ? 'var(--urgent)' : 'var(--ok)' }}>
          {d.falseRecovery > 0 ? `REV · ${d.falseRecovery} FALSE` : 'REV · STABLE'}
        </span>
      </div>

      {/* Dimension line separator */}
      <div className="bp-dim mb-4" />

      {/* Title block — parameter grid */}
      <div className="bp-title-block mb-5">
        <div className="bp-tb-row">
          <div className="bp-tb-cell">
            <div className="bp-tb-key">{t('overview.openLoops')}</div>
            <div className="bp-tb-val">{d.total.toString().padStart(2, '0')}</div>
          </div>
          <div className="bp-tb-cell">
            <div className="bp-tb-key">{t('overview.falseRecovery')}</div>
            <div className="bp-tb-val" style={{ color: 'var(--urgent)' }}>±{d.falseRecovery.toString().padStart(2, '0')}</div>
          </div>
          <div className="bp-tb-cell">
            <div className="bp-tb-key">{t('overview.residualRisks')}</div>
            <div className="bp-tb-val" style={{ color: 'var(--high)' }}>±{d.residualRisks.toString().padStart(2, '0')}</div>
          </div>
          <div className="bp-tb-cell">
            <div className="bp-tb-key">{t('overview.pendingPropagation')}</div>
            <div className="bp-tb-val">{d.pendingPropagation.toString().padStart(2, '0')}</div>
          </div>
        </div>
        <div className="bp-tb-row">
          <div className="bp-tb-cell" style={{ flex: 2 }}>
            <div className="bp-tb-key">SUMMARY · NOTES</div>
            <div className="text-[12px] leading-relaxed text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>{data.summary}</div>
          </div>
        </div>
      </div>

      {/* Two-column: open loops annotation table + command horizon */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* Left: Open loops as annotation table */}
        <div className="bp-panel">
          <div className="flex items-baseline justify-between border-b border-[color-mix(in_srgb,var(--primary)_25%,transparent)] px-4 py-2.5">
            <span className="bp-label">SEC-A · {t('overview.openLoops')} ({t('overview.byLeverage')})</span>
            <Link to="/console/queue" className="bp-label hover:opacity-100" style={{ opacity: 0.7 }}>{t('overview.viewQueue')}</Link>
          </div>
          <div>
            {d.ranks.map((r, i) => {
              const loop = data.open_loops.find((l) => l.command_id === r.command_id)
              const color = RECOVERY_COLOR[r.recovery_status] ?? 'var(--faint)'
              return (
                <div
                  key={r.command_id}
                  role="button"
                  tabIndex={0}
                  onClick={() => navigate(`/console/recovery/${r.command_id}`)}
                  onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/console/recovery/${r.command_id}`) } }}
                  className="bp-anno"
                >
                  <span className="bp-anno-idx">{String(i + 1).padStart(2, '0')}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold leading-snug" style={{ fontFamily: 'var(--font-mono)' }}>{r.label.replace(/^\d+\.\s*/, '')}</span>
                      <span className={`bp-tol ${RECOVERY_TOL[r.recovery_status] ?? 'bp-tol-flat'}`}>{r.recovery_status.replace(/_/g, ' ')}</span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2.5 font-mono text-[10px] text-muted-foreground">
                      <span>LEV <b style={{ color: 'var(--primary)' }}>{r.leverage_score.toFixed(1)}</b></span>
                      <span>· RES {r.residual_risk_count}</span>
                      {r.pending_propagation_count > 0 && <span>· PROP {r.pending_propagation_count}</span>}
                      {loop?.top_next_command && (
                        <button
                          className="bp-cmd ml-auto"
                          onClick={(e) => { e.stopPropagation(); navigate(`/console/recovery/${r.command_id}`) }}
                        >
                          {loop.top_next_command.replace(/_/g, ' ')}
                        </button>
                      )}
                    </div>
                  </div>
                  <span className="ml-2 mt-1.5 h-2 w-2 shrink-0" style={{ background: color, transform: 'rotate(45deg)' }} />
                </div>
              )
            })}
          </div>
        </div>

        {/* Right: Command horizon + next commands + recovery proof */}
        <div className="flex flex-col gap-5">
          {/* Command horizon */}
          <div className="bp-panel">
            <div className="border-b border-[color-mix(in_srgb,var(--primary)_25%,transparent)] px-4 py-2.5">
              <span className="bp-label">SEC-B · {t('overview.commandHorizon')}</span>
            </div>
            <div className="flex flex-col gap-0">
              {data.command_horizon.map((h, i) => (
                <div
                  key={i}
                  className="flex items-start gap-3 px-4 py-2.5 border-b border-[color-mix(in_srgb,var(--primary)_12%,transparent)] last:border-b-0"
                >
                  <span className="font-mono text-[10px] text-[var(--primary)] opacity-40 mt-0.5">{String(i + 1).padStart(2, '0')}</span>
                  <span className="text-[12.5px] leading-relaxed text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>{h}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Next commands */}
          {data.next_command_ribbon.length > 0 && (
            <div className="bp-panel">
              <div className="border-b border-[color-mix(in_srgb,var(--primary)_25%,transparent)] px-4 py-2.5">
                <span className="bp-label">SEC-C · {t('overview.nextCommands')}</span>
              </div>
              <div className="flex flex-wrap gap-2 p-4">
                {data.next_command_ribbon.map((cmd) => (
                  <button
                    key={cmd}
                    className="bp-cmd"
                    onClick={() => navigate('/console/queue')}
                  >
                    {cmd.replace(/_/g, ' ')}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Recovery proof — top loop */}
          {d.topLoop && (
            <div className="bp-panel">
              <div className="flex items-baseline justify-between border-b border-[color-mix(in_srgb,var(--primary)_25%,transparent)] px-4 py-2.5">
                <span className="bp-label">SEC-D · {t('overview.recovery')}</span>
                <span
                  className="bp-tol"
                  style={{
                    color: RECOVERY_COLOR[d.topLoop.assessment] ?? 'var(--faint)',
                    borderColor: RECOVERY_COLOR[d.topLoop.assessment] ?? 'var(--faint)',
                  }}
                >
                  {d.topLoop.assessment.replace(/_/g, ' ')}
                </span>
              </div>
              <div className="px-4 py-3">
                <p className="text-[12px] leading-relaxed text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>{d.topLoop.recovery_proof_summary}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Governance notes — like drawing general notes */}
      {data.governance_notes.length > 0 && (
        <div className="bp-panel mt-5">
          <div className="border-b border-[color-mix(in_srgb,var(--primary)_25%,transparent)] px-4 py-2.5">
            <span className="bp-label">NOTES · {t('overview.governanceNotes')}</span>
          </div>
          <div className="px-4 py-3">
            <ul className="space-y-1.5">
              {data.governance_notes.map((note, i) => (
                <li key={i} className="flex items-start gap-3 text-[12px] leading-relaxed text-muted-foreground" style={{ fontFamily: 'var(--font-mono)' }}>
                  <span className="text-[var(--primary)] opacity-40 mt-0.5">{String(i + 1).padStart(2, '0')}.</span>
                  {note}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Drawing footer — scale + sheet info */}
      <div className="mt-5 flex items-center justify-between border-t border-[color-mix(in_srgb,var(--primary)_20%,transparent)] pt-2.5">
        <span className="bp-label" style={{ opacity: 0.4 }}>SCALE 1:1 · SHEET 1/1 · DWG-001</span>
        <span className="bp-label" style={{ opacity: 0.4 }}>CYGNUS · GOVERNANCE BLUEPRINT</span>
      </div>
    </div>
  )
}
