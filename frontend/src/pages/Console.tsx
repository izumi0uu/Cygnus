import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
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

export default function Console() {
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
      <header className="sticky top-0 z-30 flex items-center gap-3 border-b-2 border-border bg-background/95 px-5 py-3 backdrop-blur">
        <Link to="/" className="font-display text-lg font-bold tracking-tight">CYGNUS</Link>
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
  const [selected, setSelected] = useState<PriorityItem | null>(null)

  useEffect(() => {
    if (!selected) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelected(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected])

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
          <RiskCard key={it.risk_id} item={it} lead={i === 0} onSelect={() => setSelected(it)} />
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

      {selected && <ConsequenceDrawer item={selected} onClose={() => setSelected(null)} />}
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

function RiskCard({ item, lead, onSelect }: { item: PriorityItem; lead: boolean; onSelect: () => void }) {
  const { t } = useTranslation()
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      className={`card-brutal cursor-pointer p-4 pl-5 transition-transform hover:-translate-y-0.5 ${lead ? 'card-lead' : ''}`}
    >
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
        <span className="cmd-pill ml-auto">{item.primary_command} →</span>
      </div>
    </div>
  )
}

function ConsequenceDrawer({ item, onClose }: { item: PriorityItem; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        className="fixed right-0 top-0 z-50 flex h-full w-full max-w-[440px] flex-col overflow-y-auto border-l-2 border-border bg-surface p-5"
        style={{ boxShadow: '-6px 0 0 0 var(--primary-active)' }}
      >
        <div className="flex items-center gap-2">
          <span className={`chip ${HEAT[item.urgency]}`}>{t(`urgency.${item.urgency}`)}</span>
          <span className="chip">{item.risk_type}</span>
          <button className="icon-btn ml-auto" aria-label={t('detail.close')} onClick={onClose}>✕</button>
        </div>

        <h2 className="mt-3 font-display text-lg font-bold leading-tight">{item.title}</h2>
        <div className="mt-1 font-mono text-[11px] text-muted-foreground">{item.object_ref} · {item.object_type}</div>

        <Section label={t('detail.whyNow')}>
          <p className="text-sm leading-relaxed">{item.why_now_summary}</p>
        </Section>

        <Section label={t('detail.scope')}>
          <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{t('detail.audiences')}</div>
          <div className="flex flex-wrap gap-1.5">
            {item.audience_labels.map((a) => <span key={a} className="chip">{a}</span>)}
          </div>
          <div className="mt-3 mb-1 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">{t('detail.surfaces')}</div>
          <div className="flex flex-wrap gap-1.5">
            {item.affected_surfaces.map((s) => <span key={s} className="chip">{s}</span>)}
          </div>
        </Section>

        <Section label={t('detail.owner')}>
          {item.owner_state === 'unassigned'
            ? <span className="chip chip-ownergap">{t('detail.unassigned')}</span>
            : <span className="chip chip-assigned">@{item.queue_owner}</span>}
        </Section>

        <Section label={t('detail.commands')}>
          <div className="flex flex-wrap gap-2">
            {item.command_actions.map((c) => (
              <button key={c} className="cmd-pill">{c}</button>
            ))}
          </div>
          <p className="mt-2 font-mono text-[10px] leading-relaxed text-muted-foreground">{t('detail.commandNote')}</p>
        </Section>
      </aside>
    </>
  )
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mt-5 border-t-2 border-border pt-4">
      <div className="mb-2 font-mono text-xs font-semibold uppercase tracking-widest text-muted-foreground">{label}</div>
      {children}
    </div>
  )
}
