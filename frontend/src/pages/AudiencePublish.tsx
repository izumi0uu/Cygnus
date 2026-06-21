import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ShieldAlert, Plus, Minus, Ban } from 'lucide-react'
import { fetchPublishPreview, type PublishPreviewSurface, type BlastRadiusImpact } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'

// Publish becomes blast-radius control before any outward command.
// Sourced from the publish-preview surface: channel gate matrix, impacts,
// blocked bindings, and recommended action presets.
const EFFECT_TOL: Record<string, string> = {
  new_exposure: 'bp-tol-high',
  continuing_exposure: 'bp-tol-flat',
  stopped_exposure: 'bp-tol-high',
  conflict: 'bp-tol-urgent',
}
const EFFECT_COLOR: Record<string, string> = {
  new_exposure: 'var(--high)',
  continuing_exposure: 'var(--primary)',
  stopped_exposure: 'var(--medium)',
  conflict: 'var(--urgent)',
}

export default function AudiencePublish() {
  const { t } = useTranslation()
  const v = useVocab()
  const [data, setData] = useState<PublishPreviewSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchPublishPreview().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(() => {
    fetchPublishPreview().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
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

  const sf = data.situation_frame
  const preview = data.selected_preview
  const card = data.selected_card

  return (
    <>
      {/* hero — blast-radius briefing */}
      <section className="relative mb-4 overflow-hidden bp-panel p-5 pl-[22px]">
        <span className="absolute inset-y-0 left-0 w-[3px] bg-primary" />
        <div className="flex items-start gap-4">
          <span className="bp-tol bp-tol-urgent mt-0.5 shrink-0">{t('pub.blastRadius')}</span>
          <div className="min-w-0">
            <h2 className="font-mono text-[18px] font-bold leading-tight">{data.headline}</h2>
            <p className="mt-1.5 max-w-[80ch] font-mono text-[12px] leading-relaxed text-muted-foreground">{data.summary}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[11px] text-muted-foreground">
              <span className="bp-tol bp-tol-flat">{t('pub.truthBoundary')}</span>
              <span className="text-foreground">{sf.truth_boundary}</span>
            </div>
          </div>
          <div className="ml-auto hidden shrink-0 gap-5 sm:flex">
            <div><div className="font-mono text-2xl font-bold" style={{ color: 'var(--urgent)' }}>{sf.blocked_paths}</div><div className="font-mono text-[10px] uppercase text-muted-foreground">{t('pub.blocked')}</div></div>
            <div><div className="font-mono text-2xl font-bold" style={{ color: 'var(--high)' }}>{sf.stopped_paths}</div><div className="font-mono text-[10px] uppercase text-muted-foreground">{t('pub.stopped')}</div></div>
          </div>
        </div>
      </section>

      {/* stat tiles */}
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={data.total_items} label={t('pub.candidates')} />
        <Stat n={sf.blocked_paths} label={t('pub.blocked')} dot="var(--urgent)" />
        <Stat n={sf.new_paths} label={t('pub.newPaths')} dot="var(--primary)" />
        <Stat n={sf.stopped_paths} label={t('pub.stopped')} dot="var(--high)" />
        <Stat n={sf.affected_surfaces.length} label={t('queue.statSurfaces')} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* left: selected candidate + channel gate matrix */}
        <div className="bp-panel">
          <div className="px-4 pt-3.5"><div className="bp-label">{t('pub.candidate')}</div></div>
          {card ? (
            <div className="px-4 pb-3 pt-2">
              <div className="font-mono text-[13px] font-semibold leading-snug">{card.title}</div>
              <div className="mt-0.5 font-mono text-[10px] text-muted-foreground">{card.object_ref} · {v.objectType(card.object_type)} · {v.riskType(card.risk_type)}</div>
            </div>
          ) : <div className="px-4 pb-3 font-mono text-sm text-faint">{t('state.empty')}</div>}

          {preview && (
            <div className="bp-dim">
              <div className="px-4 pt-3.5"><div className="font-mono text-[12px] font-bold">{t('pub.gateMatrix')}</div><div className="font-mono text-[11px] text-faint">{t('pub.gateMatrixNote')}</div></div>
              <div className="overflow-x-auto px-4 pb-4 pt-2">
                <table className="w-full font-mono text-[12px]">
                  <thead>
                    <tr className="text-[10px] uppercase tracking-wide text-faint">
                      <th className="pb-2 text-left font-medium">{t('pub.channel')}</th>
                      <th className="pb-2 text-center font-medium"><Plus size={11} className="inline" /> {t('pub.new')}</th>
                      <th className="pb-2 text-center font-medium">{t('pub.continuing')}</th>
                      <th className="pb-2 text-center font-medium"><Minus size={11} className="inline" /> {t('pub.stopped')}</th>
                      <th className="pb-2 text-center font-medium"><Ban size={11} className="inline" /> {t('pub.conflicts')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.channel_gate_matrix.map((row) => (
                      <tr key={row.channel} className="bp-dim">
                        <td className="py-2 font-medium">{v.surface(row.channel)}</td>
                        <td className="py-2 text-center" style={{ color: row.new_exposure ? 'var(--high)' : 'var(--faint)' }}>{row.new_exposure}</td>
                        <td className="py-2 text-center" style={{ color: row.continuing_exposure ? 'var(--primary)' : 'var(--faint)' }}>{row.continuing_exposure}</td>
                        <td className="py-2 text-center" style={{ color: row.stopped_exposure ? 'var(--medium)' : 'var(--faint)' }}>{row.stopped_exposure}</td>
                        <td className="py-2 text-center font-bold" style={{ color: row.conflicts ? 'var(--urgent)' : 'var(--faint)' }}>{row.conflicts}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        {/* right: impacts + warnings */}
        <div className="flex flex-col bp-panel">
          <div className="px-4 pt-3.5"><div className="bp-label">{t('pub.impacts')}</div><div className="font-mono text-[11px] text-faint">{t('pub.impactsNote')}</div></div>
          <div className="flex flex-col gap-2 px-4 py-3">
            {preview?.impacts.map((imp, i) => <ImpactRow key={i} imp={imp} />)}
            {(!preview || preview.impacts.length === 0) && <div className="font-mono text-sm text-faint">{t('state.empty')}</div>}
          </div>

          {preview && preview.warnings.length > 0 && (
            <div className="mt-auto bp-dim px-4 py-3">
              <div className="mb-1.5 flex items-center gap-1.5"><ShieldAlert size={13} style={{ color: 'var(--urgent)' }} /><span className="font-mono text-[10px] uppercase tracking-wide text-faint">{t('pub.warnings')}</span></div>
              <ul className="space-y-1">
                {preview.warnings.map((w, i) => (
                  <li key={i} className="flex items-start gap-2 font-mono text-[12px] leading-relaxed text-muted-foreground">
                    <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rotate-45" style={{ background: 'var(--urgent)' }} />
                    {w}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* action presets — recommended commands with consequence hints */}
      {data.action_presets.length > 0 && (
        <div className="mt-4 bp-panel">
          <div className="px-4 pt-3.5"><div className="bp-label">{t('pub.actionPresets')}</div><div className="font-mono text-[11px] text-faint">{t('pub.actionPresetsNote')}</div></div>
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            {data.action_presets.map((ap) => (
              <div key={ap.command_key} className={`bp-panel flex flex-col gap-2 p-3.5 ${ap.recommended ? '' : ''}`} style={ap.recommended ? { borderColor: 'color-mix(in srgb, var(--primary) 50%, transparent)' } : undefined}>
                <div className="flex items-center gap-2">
                  {ap.recommended && <span className="bp-tol bp-tol-urgent">{t('pub.recommended')}</span>}
                  <span className="font-mono text-[11px] text-muted-foreground">{ap.command_key}</span>
                  <CmdButton command={ap.command_key} className="ml-auto" />
                </div>
                <p className="text-[12.5px] leading-relaxed text-muted-foreground">{ap.summary}</p>
                <p className="font-mono text-[10.5px] leading-relaxed text-faint">{ap.consequence_hint}</p>
                <div className="flex flex-wrap gap-1.5">
                  {ap.channels.map((c) => <span key={c} className="bp-tol bp-tol-flat">{v.surface(c)}</span>)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* context notes */}
      {data.context_notes.length > 0 && (
        <div className="mt-4 bp-panel px-4 py-3">
          <div className="mb-1.5 bp-label">{t('pub.contextNotes')}</div>
          <ul className="space-y-1">
            {data.context_notes.map((note, i) => (
              <li key={i} className="flex items-start gap-2 font-mono text-[12px] leading-relaxed text-muted-foreground">
                <span className="mt-1.5 h-1 w-1 shrink-0 rotate-45 bg-faint" />
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}
    </>
  )
}

function ImpactRow({ imp }: { imp: BlastRadiusImpact }) {
  const color = EFFECT_COLOR[imp.effect] ?? 'var(--faint)'
  return (
    <div className="bp-dim flex items-start gap-2.5 px-3 py-2">
      <span className="mt-1 h-2 w-2 shrink-0 rotate-45" style={{ background: color }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-mono text-[11px] text-muted-foreground">{imp.audience_label}</span>
          <span className="font-mono text-[10px] text-faint">· {imp.channel}</span>
          <span className={`bp-tol ${EFFECT_TOL[imp.effect] ?? 'bp-tol-flat'} ml-auto`}>{imp.effect.replace(/_/g, ' ')}</span>
        </div>
        <p className="mt-1 font-mono text-[11.5px] leading-relaxed text-faint">{imp.reason}</p>
      </div>
    </div>
  )
}
