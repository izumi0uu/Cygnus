import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useTheme } from '@/lib/theme'
import { fetchCommandCenter, type CommandCenterSurface, type PriorityItem } from '@/lib/api'

const HEAT: Record<string, string> = {
  urgent: 'heat-urgent',
  high: 'heat-high',
  medium: 'heat-medium',
  low: 'heat-low',
}
const HEAT_BAR: Record<string, string> = {
  urgent: 'var(--heat-urgent)',
  high: 'var(--heat-high)',
  medium: 'var(--heat-medium)',
  low: 'var(--heat-low)',
}

function App() {
  const { t, i18n } = useTranslation()
  const { theme, setTheme } = useTheme()
  const [data, setData] = useState<CommandCenterSurface | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const load = () => {
    setLoading(true)
    setError(null)
    fetchCommandCenter()
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }
  useEffect(load, [])

  const isZh = i18n.language.startsWith('zh')
  const toggleLang = () => {
    const next = isZh ? 'en' : 'zh'
    i18n.changeLanguage(next)
    localStorage.setItem('cygnus-lang', next)
  }
  const cycleTheme = () => setTheme(theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system')
  const themeGlyph = theme === 'system' ? '⚙' : theme === 'light' ? '☀' : '☾'

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-50 flex items-center gap-3 border-b-2 border-border bg-background/95 px-5 py-3 backdrop-blur">
        <span className="font-display text-lg font-bold tracking-tight">CYGNUS</span>
        <span className="text-muted-foreground">/</span>
        <span className="font-display font-semibold">{t('app.surface')}</span>
        <span className="chip">{t('app.brief')}</span>
        <div className="ml-auto flex items-center gap-2">
          <button className="icon-btn" onClick={toggleLang}>{isZh ? '中 / EN' : 'EN / 中'}</button>
          <button className="icon-btn" onClick={cycleTheme}>
            <span>{themeGlyph}</span> {t(`toggle.${theme}`)}
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-[1100px] px-5 py-5">
        {loading && <div className="font-mono text-sm text-muted-foreground">{t('state.loading')}</div>}
        {error && (
          <div className="card-brutal p-4" style={{ borderColor: 'var(--critical)' }}>
            <div className="flex items-center gap-2 font-semibold" style={{ color: 'var(--critical)' }}>
              <span>⚠</span> {t('state.error')}
            </div>
            <button className="btn-secondary mt-3" onClick={load}>{t('state.retry')}</button>
          </div>
        )}
        {data && !loading && <CommandCenter data={data} />}
      </main>
    </div>
  )
}

function CommandCenter({ data }: { data: CommandCenterSurface }) {
  const { t } = useTranslation()
  const sf = data.situation_frame
  return (
    <>
      <section className="card-brutal p-4">
        <div className="flex items-start gap-3">
          <span className="chip heat-urgent shrink-0">{t('frame.label')}</span>
          <div className="min-w-0">
            <h1 className="font-display text-xl font-bold leading-tight">{data.headline}</h1>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{sf.primary_tension}</p>
          </div>
          <div className="ml-auto hidden shrink-0 gap-2 sm:flex">
            <Stat n={sf.urgent_items} label={t('frame.urgent')} color="var(--critical)" />
            <Stat n={sf.owner_gaps} label={t('frame.ownerGaps')} color="var(--caution)" />
          </div>
        </div>
      </section>

      <div className="mt-5 mb-2 flex items-center justify-between">
        <h2 className="font-mono text-xs font-semibold uppercase tracking-widest text-muted-foreground">
          {t('stack.label')}
        </h2>
        <span className="font-mono text-[11px] text-muted-foreground">{t('stack.note')}</span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {data.priority_stack.map((it, i) => (
          <RiskCard key={it.risk_id} item={it} lead={i === 0} />
        ))}
      </div>

      <h2 className="mt-6 mb-2 font-mono text-xs font-semibold uppercase tracking-widest text-muted-foreground">
        {t('commands.label')}
      </h2>
      <div className="flex flex-wrap gap-2">
        {data.available_commands.map((c) => (
          <span key={c} className="chip">{c}</span>
        ))}
      </div>
    </>
  )
}

function Stat({ n, label, color }: { n: number; label: string; color: string }) {
  return (
    <div className="card-brutal px-3 py-1.5 text-center">
      <div className="font-mono text-xl font-bold" style={{ color }}>{n}</div>
      <div className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">{label}</div>
    </div>
  )
}

function RiskCard({ item, lead }: { item: PriorityItem; lead: boolean }) {
  const { t } = useTranslation()
  return (
    <div className={`card-brutal p-4 pl-5 ${lead ? 'card-lead' : ''}`}>
      <span
        className="absolute left-0 top-0 bottom-0 w-2 rounded-l-[8px]"
        style={{ background: HEAT_BAR[item.urgency] }}
      />
      <div className="flex items-center gap-2">
        <span className={`chip ${HEAT[item.urgency]}`}>{t(`urgency.${item.urgency}`)}</span>
        <span className="chip">{item.risk_type}</span>
      </div>
      <div className={`mt-2 ${lead ? 'text-base font-semibold' : 'text-sm'} leading-snug`}>{item.title}</div>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{item.why_now_summary}</p>
      <div className="mt-3 flex items-center gap-2">
        {item.owner_state === 'unassigned' ? (
          <span className="chip chip-ownergap">{t('owner.gap')}</span>
        ) : (
          <span className="chip chip-assigned">@{item.queue_owner}</span>
        )}
        <button className="cmd-pill ml-auto">{item.primary_command} →</button>
      </div>
    </div>
  )
}

export default App
