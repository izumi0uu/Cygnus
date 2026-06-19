import { useEffect, useMemo, useRef, useState } from 'react'
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
  { navKey: 'audience', to: '/console/audience' },
  { navKey: 'drift', to: '/console/drift' },
  { navKey: 'propagation', to: '/console/propagation' },
  { navKey: 'audit', to: '/console/audit' },
]

export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const v = useVocab()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const [risks, setRisks] = useState<Item[]>([])
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  useFocusTrap(boxRef, open, onClose)

  useEffect(() => {
    if (!open) return
    setQuery('')
    setActive(0)
    inputRef.current?.focus()
    fetchCommandCenter()
      .then((d) =>
        setRisks(
          d.priority_stack.map((it) => ({
            id: it.risk_id,
            group: 'risks' as const,
            label: it.title,
            sub: `${it.object_ref} · ${v.riskType(it.risk_type)}`,
            to: routeForRisk(it.risk_type).to,
          })),
        ),
      )
      .catch(() => setRisks([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const sections: Item[] = useMemo(
    () => SECTIONS.map((s) => ({ id: s.navKey, group: 'sections', label: t(`nav.${s.navKey}`), to: s.to })),
    [t],
  )

  const results = useMemo(() => {
    const q = query.trim().toLowerCase()
    const all = [...sections, ...risks]
    if (!q) return all
    return all.filter((i) => i.label.toLowerCase().includes(q) || i.sub?.toLowerCase().includes(q))
  }, [query, sections, risks])

  useEffect(() => { setActive(0) }, [query])

  if (!open) return null

  const go = (item?: Item) => {
    const target = item ?? results[active]
    if (!target) return
    onClose()
    navigate(target.to)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); go() }
    else if (e.key === 'Escape') { e.preventDefault(); onClose() }
  }

  let idx = -1

  return (
    <div className="fixed inset-0 z-[150] flex items-start justify-center bg-foreground/25 pt-[12vh]" onMouseDown={onClose}>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('palette.placeholder')}
        tabIndex={-1}
        className="w-full max-w-[560px] overflow-hidden rounded-xl border border-border bg-card shadow-soft outline-none"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-border px-4">
          <Search size={16} className="shrink-0 text-faint" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={t('palette.placeholder')}
            className="w-full bg-transparent py-3.5 text-sm outline-none placeholder:text-faint"
          />
        </div>

        <div className="thin-scroll max-h-[50vh] overflow-y-auto py-1.5">
          {results.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground">{t('palette.empty')}</div>
          ) : (
            (['sections', 'risks'] as const).map((group) => {
              const groupItems = results.filter((i) => i.group === group)
              if (groupItems.length === 0) return null
              return (
                <div key={group}>
                  <div className="px-4 pb-1 pt-2 font-mono text-[10px] uppercase tracking-widest text-faint">{t(`palette.${group}`)}</div>
                  {groupItems.map((item) => {
                    idx++
                    const isActive = idx === active
                    return (
                      <button
                        key={item.id}
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
