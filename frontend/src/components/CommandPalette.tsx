import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Search, CornerDownLeft } from 'lucide-react'
import { fetchCommandCenter } from '@/lib/api'
import { routeForRisk } from '@/lib/notifications'
import { useVocab } from '@/lib/vocab'
import { useFocusTrap } from '@/lib/useFocusTrap'

type Item = { id: string; group: 'sections' | 'risks'; label: string; sub?: string; to: string }

const SECTIONS: { navKey: string; to: string }[] = [
  { navKey: 'overview', to: '/console' },
  { navKey: 'reviewQueue', to: '/console/queue' },
  { navKey: 'objects', to: '/console/objects' },
  { navKey: 'sources', to: '/console/sources' },
  { navKey: 'ticketInsights', to: '/console/tickets' },
  { navKey: 'audience', to: '/console/audience' },
  { navKey: 'drift', to: '/console/drift' },
  { navKey: 'propagation', to: '/console/propagation' },
  { navKey: 'audit', to: '/console/audit' },
]

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t, i18n } = useTranslation()
  const language = i18n.resolvedLanguage ?? i18n.language
  const v = useVocab()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [risks, setRisks] = useState<Item[]>([])
  const [riskState, setRiskState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle')
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const dialogTitleId = useId()
  const listboxId = useId()
  const requestRef = useRef<{ language: string } | null>(null)
  const mountedRef = useRef(true)
  useFocusTrap(boxRef, open, onClose)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      requestRef.current = null
    }
  }, [])
  const closePalette = () => {
    setQuery('')
    setActive(0)
    onClose()
  }

  useEffect(() => {
    if (!open) {
      requestRef.current = null
      return
    }
    inputRef.current?.focus()
    if (requestRef.current?.language === language) return
    const request = { language }
    requestRef.current = request
    setRiskState('loading')
    fetchCommandCenter()
      .then((data) => {
        if (!mountedRef.current || requestRef.current !== request) return
        setRisks(
          data.priority_stack.map((item) => ({
            id: item.risk_id,
            group: 'risks' as const,
            label: item.title,
            sub: `${item.object_ref} · ${v.riskType(item.risk_type)}`,
            to: routeForRisk(item.risk_type, { riskId: item.risk_id, objectRef: item.object_ref }).to,
          })),
        )
        setRiskState('ready')
      })
      .catch(() => {
        if (mountedRef.current && requestRef.current === request) {
          setRisks([])
          setRiskState('error')
        }
      })
  }, [language, open, v])

  const sections: Item[] = useMemo(
    () => SECTIONS.map((s) => ({ id: s.navKey, group: 'sections' as const, label: t(`nav.${s.navKey}`), to: s.to })),
    [t],
  )

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return [...sections, ...risks]
    return [...sections, ...risks].filter((item) => item.label.toLowerCase().includes(q) || item.sub?.toLowerCase().includes(q))
  }, [query, sections, risks])
  const activeIndex = results.length === 0 ? 0 : Math.min(active, results.length - 1)


  if (!open) return null

  const go = (item?: Item) => {
    const target = item ?? results[activeIndex]
    if (!target) return
    closePalette()
    navigate(target.to)
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (results.length === 0) return
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); go() }
  }

  let idx = -1

  return (
    <div className="fixed inset-0 z-[150] flex items-start justify-center bg-foreground/25 px-3 pt-[12vh]" onMouseDown={closePalette}>
      <div
        id="command-palette"
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={dialogTitleId}
        tabIndex={-1}
        className="w-full max-w-[560px] overflow-hidden border border-border bg-card shadow-soft outline-none"
        style={{ borderRadius: 0 }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id={dialogTitleId} className="sr-only">{t('palette.inputLabel')}</h2>
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search size={16} aria-hidden="true" className="shrink-0 text-faint" />
          <input
            ref={inputRef}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded="true"
            aria-controls={listboxId}
            aria-activedescendant={results.length > 0 ? `${listboxId}-option-${activeIndex}` : undefined}
            aria-label={t('palette.inputLabel')}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            onKeyDown={onKeyDown}
            placeholder={t('palette.placeholder')}
            className="min-h-11 w-full bg-transparent py-3.5 text-sm outline-none placeholder:text-faint"
          />
        </div>
        {riskState === 'loading' && <div role="status" className="px-4 py-2 font-mono text-[11px] text-faint">{t('palette.loading')}</div>}
        {riskState === 'error' && <div role="status" className="px-4 py-2 font-mono text-[11px] text-high">{t('palette.risksUnavailable')}</div>}

        <div id={listboxId} role="listbox" aria-label={t('palette.inputLabel')} className="thin-scroll max-h-[50vh] overflow-y-auto py-1.5">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t('palette.empty')}</div>
          ) : (
            (['sections', 'risks'] as const).map((group) => {
              const groupItems = results.filter((item) => item.group === group)
              if (groupItems.length === 0) return null
              return (
                <div key={group} role="group" aria-labelledby={`${listboxId}-${group}`}>
                  <div id={`${listboxId}-${group}`} className="flex items-center gap-1.5 px-4 pb-1 pt-2 font-mono text-[10px] uppercase tracking-widest text-faint">
                    {t(`palette.${group}`)}
                  </div>
                  {groupItems.map((item) => {
                    idx++
                    const isActive = idx === activeIndex
                    return (
                      <button
                        key={item.id}
                        id={`${listboxId}-option-${idx}`}
                        type="button"
                        role="option"
                        aria-selected={isActive}
                        tabIndex={-1}
                        onMouseEnter={() => setActive(results.indexOf(item))}
                        onClick={() => go(item)}
                        className={`flex w-full items-center gap-2 px-4 py-2 text-left ${isActive ? 'bg-muted' : ''}`}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="truncate text-[13px] font-medium">{item.label}</span>
                          {item.sub && <span className="ml-2 font-mono text-[11px] text-faint">{item.sub}</span>}
                        </span>
                        {isActive && <CornerDownLeft size={13} className="shrink-0 text-faint" />}
                      </button>
                    )
                  })}
                </div>
              )
            })
          )}
        </div>

        <div className="border-t border-border px-4 py-2 font-mono text-[10px] text-faint">{t('palette.hint')}</div>
      </div>
    </div>
  )
}
