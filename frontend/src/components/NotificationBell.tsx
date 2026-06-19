import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bell, CheckCheck } from 'lucide-react'
import { useVocab } from '@/lib/vocab'
import { notificationSource, type CygnusNotification, type NotifSeverity } from '@/lib/notifications'

const SEV_HEX: Record<NotifSeverity, string> = { urgent: '#e5484d', high: '#f76808', medium: '#e8930c', low: '#185ee0' }

const source = notificationSource

export default function NotificationBell() {
  const { t } = useTranslation()
  const v = useVocab()
  const navigate = useNavigate()
  const [items, setItems] = useState<CygnusNotification[]>([])
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    source.list().then(setItems).catch(() => setItems([]))
  }, [])
  useEffect(load, [load])

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey) }
  }, [open])

  const unread = items.filter((n) => !n.read).length

  const openItem = async (n: CygnusNotification) => {
    if (!n.read) {
      await source.markRead(n.id)
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)))
    }
    setOpen(false)
    navigate(n.to)
  }

  const markAll = async () => {
    await source.markAllRead()
    setItems((prev) => prev.map((x) => ({ ...x, read: true })))
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={t('notif.title')}
        className="relative flex h-[34px] w-[34px] items-center justify-center rounded-full border border-border bg-card text-muted-foreground hover:bg-muted"
      >
        <Bell size={16} />
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-[17px] min-w-[17px] items-center justify-center rounded-full px-1 font-mono text-[10px] font-bold text-primary-foreground" style={{ background: 'var(--urgent)' }}>
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-[42px] z-[100] w-[360px] overflow-hidden rounded-xl border border-border bg-card shadow-soft">
          <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
            <span className="text-[13px] font-bold">{t('notif.title')}</span>
            {unread > 0 && <span className="rounded-full bg-muted px-1.5 font-mono text-[10px] text-muted-foreground">{unread}</span>}
            {unread > 0 && (
              <button onClick={markAll} className="ml-auto flex items-center gap-1 font-mono text-[11px] font-semibold text-primary hover:underline">
                <CheckCheck size={13} />{t('notif.markAll')}
              </button>
            )}
          </div>

          <div className="thin-scroll max-h-[420px] overflow-y-auto">
            {items.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-muted-foreground">{t('notif.empty')}</div>
            ) : (
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => openItem(n)}
                  className="flex w-full gap-2.5 border-b border-border px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-muted"
                  style={n.read ? undefined : { background: 'color-mix(in srgb, var(--accent) 40%, transparent)' }}
                >
                  <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: n.read ? 'transparent' : SEV_HEX[n.severity], boxShadow: n.read ? 'inset 0 0 0 1.5px var(--faint)' : undefined }} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-1.5">
                      <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: SEV_HEX[n.severity] }} />
                      <span className={`truncate text-[13px] ${n.read ? 'font-medium' : 'font-semibold'}`}>{n.title}</span>
                    </span>
                    <span className="mt-0.5 line-clamp-2 block text-[12px] leading-relaxed text-muted-foreground">{n.body}</span>
                    <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <span className="rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">{v.riskType(n.kind)}</span>
                      {n.ownerGap && <span className="chip chip-gap">{t('owner.gap')}</span>}
                      <span className="ml-auto font-mono text-[10px] text-primary">{t(`nav.${n.navKey}`)} →</span>
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
