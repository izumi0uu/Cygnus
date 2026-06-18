import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { fetchCommandCenter, type CommandCenterSurface } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Segmented } from '@/components/Segmented'
import { Stat } from '@/components/Stat'

type Filter = 'all' | 'external' | 'internal'
type Seg = { label: string; visibility: string; risks: number; surfaces: string[] }

function aggregate(data: CommandCenterSurface): Seg[] {
  const map = new Map<string, { label: string; visibility: string; risks: number; surfaces: Set<string> }>()
  for (const it of data.priority_stack) {
    it.audience_labels.forEach((label, i) => {
      const vis = it.affected_audiences[i]?.visibility ?? (label.startsWith('internal') ? 'internal' : 'external')
      const seg = map.get(label) ?? { label, visibility: vis, risks: 0, surfaces: new Set<string>() }
      seg.risks += 1
      it.affected_surfaces.forEach((s) => seg.surfaces.add(s))
      map.set(label, seg)
    })
  }
  return [...map.values()].map((s) => ({ ...s, surfaces: [...s.surfaces] })).sort((a, b) => b.risks - a.risks)
}

export default function AudiencePublish() {
  const { t } = useTranslation()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter().then(setData).catch((e) => setError(String(e))).finally(() => setLoading(false))
  }
  useEffect(load, [])

  const segs = useMemo(() => (data ? aggregate(data) : []), [data])

  if (loading) return <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>
  if (error)
    return (
      <div className="rounded-xl border border-border bg-card p-4 shadow-card">
        <div className="font-semibold" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button variant="ghost" className="mt-3" onClick={load}>{t('state.retry')}</Button>
      </div>
    )
  if (!data) return null

  const ext = segs.filter((s) => s.visibility === 'external').length
  const int = segs.filter((s) => s.visibility === 'internal').length
  const surfaces = new Set(segs.flatMap((s) => s.surfaces)).size
  const rows = segs.filter((s) => (filter === 'all' ? true : s.visibility === filter))

  return (
    <>
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={segs.length} label={t('aud.segs')} />
        <Stat n={ext} label={t('aud.external')} dot="var(--high)" />
        <Stat n={int} label={t('aud.internal')} dot="var(--primary)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
      </div>

      <div className="mb-3.5 flex items-center gap-3">
        <Segmented
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: t('queue.all') },
            { value: 'external', label: t('aud.external') },
            { value: 'internal', label: t('aud.internal') },
          ]}
        />
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-soft">
        <div className="grid grid-cols-[110px_1.3fr_110px_1.4fr_130px] gap-3.5 border-b border-border px-[18px] py-2.5 font-mono text-[10px] uppercase tracking-[1px] text-faint">
          <span>{t('aud.thVis')}</span>
          <span>{t('aud.thSeg')}</span>
          <span>{t('aud.thRisks')}</span>
          <span>{t('aud.thSurf')}</span>
          <span>{t('aud.thAct')}</span>
        </div>
        {rows.map((s) => (
          <div key={s.label} className="grid grid-cols-[110px_1.3fr_110px_1.4fr_130px] items-center gap-3.5 border-b border-border px-[18px] py-[14px] last:border-b-0">
            <span>
              <span className={`chip ${s.visibility === 'external' ? 'chip-high' : ''}`}>{t(`aud.${s.visibility}`)}</span>
            </span>
            <span className="font-mono text-[12px] text-foreground">{s.label}</span>
            <span className="font-mono text-[12px] text-muted-foreground">{s.risks} {t('aud.risksUnit')}</span>
            <span className="flex flex-wrap gap-1.5">
              {s.surfaces.map((su) => <span key={su} className="chip">{su}</span>)}
            </span>
            <span>
              <button className="cmd">{s.visibility === 'external' ? 'restrict_publish' : 'open_review'} →</button>
            </span>
          </div>
        ))}
        {rows.length === 0 && <div className="px-[18px] py-10 text-center text-sm text-muted-foreground">{t('state.empty')}</div>}
      </div>
    </>
  )
}
