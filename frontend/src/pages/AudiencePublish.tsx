import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchCommandCenter, type CommandCenterSurface, type AffectedAudience } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'

type Seg = { label: string; visibility: string; aud?: AffectedAudience; risks: number; surfaces: string[] }

function aggregate(data: CommandCenterSurface): Seg[] {
  const map = new Map<string, { label: string; visibility: string; aud?: AffectedAudience; risks: number; surfaces: Set<string> }>()
  for (const it of data.priority_stack) {
    it.audience_labels.forEach((label, i) => {
      const a = it.affected_audiences[i]
      const vis = a?.visibility ?? (label.startsWith('internal') ? 'internal' : 'external')
      const seg = map.get(label) ?? { label, visibility: vis, aud: a, risks: 0, surfaces: new Set<string>() }
      seg.risks += 1
      it.affected_surfaces.forEach((s) => seg.surfaces.add(s))
      map.set(label, seg)
    })
  }
  return [...map.values()].map((s) => ({ ...s, surfaces: [...s.surfaces] })).sort((a, b) => b.risks - a.risks)
}

const visColor = (vis: string) => (vis === 'external' ? 'var(--high)' : 'var(--primary)')

export default function AudiencePublish() {
  const { t } = useTranslation()
  const v = useVocab()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const segs = useMemo(() => (data ? aggregate(data) : []), [data])

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data || segs.length === 0) return null

  const ext = segs.filter((s) => s.visibility === 'external').length
  const int = segs.filter((s) => s.visibility === 'internal').length
  const surfaces = new Set(segs.flatMap((s) => s.surfaces)).size
  const maxRisks = Math.max(...segs.map((s) => s.risks), 1)

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={segs.length} label={t('aud.segs')} />
        <Stat n={ext} label={t('aud.external')} dot="var(--high)" />
        <Stat n={int} label={t('aud.internal')} dot="var(--primary)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        {/* segments × risk-touch bar chart */}
        <div className="rounded-xl border border-border bg-card shadow-soft">
          <div className="px-4 pt-3.5"><div className="text-[13px] font-bold">{t('aud.byRisk')}</div><div className="text-[11px] text-faint">{t('aud.byRiskSub')}</div></div>
          <div className="flex flex-col gap-4 p-[18px]">
            {segs.map((s) => (
              <div key={s.label} className="flex flex-col gap-1.5">
                <div className="flex items-center gap-2 text-[13px]">
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: visColor(s.visibility) }} />
                  <span className="truncate">{s.aud ? v.audienceFacets(s.aud).join(' · ') || s.label : s.label}</span>
                  <span className="shrink-0 font-mono text-[11px] text-faint">{v.visibility(s.visibility)}</span>
                  <span className="ml-auto shrink-0 font-mono font-bold">{s.risks}</span>
                </div>
                <div className="h-2.5 overflow-hidden rounded-full bg-muted">
                  <span className="block h-full rounded-full" style={{ width: `${(s.risks / maxRisks) * 100}%`, background: visColor(s.visibility) }} />
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* audience segment cards */}
        <div className="grid content-start gap-3.5 sm:grid-cols-2">
          {segs.map((s) => (
            <div key={s.label} className="flex flex-col gap-2.5 rounded-xl border border-border bg-card p-4 shadow-card transition-transform hover:-translate-y-px">
              <span
                className="self-start rounded-full border px-2.5 py-1 font-mono text-[10px] font-bold uppercase tracking-wide"
                style={{
                  color: visColor(s.visibility),
                  background: `color-mix(in srgb, ${visColor(s.visibility)} 10%, transparent)`,
                  borderColor: `color-mix(in srgb, ${visColor(s.visibility)} 35%, transparent)`,
                }}
              >
                ● {v.visibility(s.visibility)}
              </span>
              <div className="font-mono text-[12.5px] font-semibold">{s.aud ? v.audienceSegment(s.aud) : s.label}</div>
              {s.aud && (
                <div className="flex flex-wrap gap-1.5">
                  {v.audienceFacets(s.aud).map((f) => (
                    <span key={f} className="rounded-md border border-border bg-muted px-2 py-0.5 font-mono text-[11px]">{f}</span>
                  ))}
                </div>
              )}
              <div className="border-t border-border pt-2.5 text-[12px] text-muted-foreground">
                <span className="font-mono font-bold text-foreground">{s.risks}</span> {t('aud.touched')} · {s.surfaces.length} {t('aud.surfUnit')}
              </div>
              <div className="flex flex-wrap gap-1.5">
                {s.surfaces.map((su) => <span key={su} className="chip">{v.surface(su)}</span>)}
              </div>
              <div className="flex">
                <CmdButton command={s.visibility === 'external' ? 'restrict_publish' : 'open_review'} className="ml-auto" />
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
