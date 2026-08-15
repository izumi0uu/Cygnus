import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Bell, CheckCheck, CloudOff, TriangleAlert } from 'lucide-react'
import { useVocab } from '@/lib/vocab'
import { useNotifications } from '@/lib/notification-state'
import { useFocusTrap } from '@/lib/useFocusTrap'
import type { CygnusNotification, NotifSeverity } from '@/lib/notifications'

const SEV_VAR: Record<NotifSeverity, string> = {
  urgent: 'var(--urgent)',
  high: 'var(--high)',
  medium: 'var(--medium)',
  low: 'var(--primary)',
}

export default function NotificationBell({ cloudsVisible, onToggleClouds }: { cloudsVisible: boolean; onToggleClouds: () => void }) {
  const { t } = useTranslation()
  const v = useVocab()
  const navigate = useNavigate()
  const { items, status, error, unreadCount, reload, markRead, markAllRead } = useNotifications()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)
  const popupRef = useRef<HTMLDivElement>(null)

  const close = useCallback(() => setOpen(false), [])
  // Dialog semantics: focus moves into the popup, Tab is trapped, Escape
  // closes, and focus returns to the bell button.
  useFocusTrap(popupRef, open, close)

  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) close() }
    window.addEventListener('mousedown', onDown)
    return () => { window.removeEventListener('mousedown', onDown) }
  }, [open, close])

  // Navigate FIRST, then optimistically mark read. A mark-read failure reverts
  // in the shared state and surfaces the outage — it never blocks the deep link.
  const openItem = (n: CygnusNotification) => {
    close()
    navigate(n.to)
    markRead(n.id)
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-label={t('notif.title')}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="notif-popup"
        data-status={status}
        className="relative flex h-[34px] w-[34px] items-center justify-center rounded-full border border-border bg-card text-muted-foreground hover:bg-muted max-md:h-11 max-md:w-11"
      >
        <Bell size={16} />
        {unreadCount > 0 && (
          <span className="absolute -right-1 -top-1 flex h-[17px] min-w-[17px] items-center justify-center rounded-full px-1 font-mono text-[10px] font-bold text-primary-foreground" style={{ background: 'var(--urgent)' }}>
            {unreadCount > 9 ? '9+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          id="notif-popup"
          ref={popupRef}
          role="dialog"
          aria-label={t('notif.title')}
          className="absolute right-0 top-[42px] z-[100] w-[calc(100vw-20px)] max-w-[360px] overflow-hidden rounded-xl border border-border bg-card shadow-soft max-md:top-[48px]"
        >
          <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
            <span className="text-[13px] font-bold">{t('notif.title')}</span>
            {unreadCount > 0 && <span className="rounded-full bg-muted px-1.5 font-mono text-[10px] text-muted-foreground">{unreadCount}</span>}
            <button
              onClick={(e) => { e.stopPropagation(); onToggleClouds() }}
              className="flex items-center gap-1 font-mono text-[10px] font-semibold transition-colors"
              style={{
                color: cloudsVisible ? 'var(--primary)' : 'var(--faint)',
                opacity: cloudsVisible ? 1 : 0.5,
              }}
              title={t('cloud.revisions')}
            >
              <CloudOff size={12} />
              {t('cloud.revisions')}
            </button>
            {unreadCount > 0 && (
              <button onClick={markAllRead} className="ml-auto flex items-center gap-1 font-mono text-[11px] font-semibold text-primary hover:underline">
                <CheckCheck size={13} />{t('notif.markAll')}
              </button>
            )}
          </div>

          <div className="thin-scroll max-h-[420px] overflow-y-auto" aria-busy={status === 'loading'}>
            {status === 'loading' && items.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm text-muted-foreground">{t('state.loading')}</div>
            ) : items.length === 0 ? (
              error ? (
                <div role="alert" className="px-4 py-8 text-center">
                  <div className="flex items-center justify-center gap-1.5 font-mono text-[12px] leading-relaxed" style={{ color: 'var(--urgent)' }}>
                    <TriangleAlert size={14} aria-hidden="true" /> {t('state.error')}
                  </div>
                  <button onClick={reload} className="mt-3 font-mono text-[11px] font-semibold text-primary hover:underline">
                    {t('state.retry')}
                  </button>
                </div>
              ) : (
                <div className="px-4 py-10 text-center text-sm text-muted-foreground">{t('notif.empty')}</div>
              )
            ) : (
              <>
                {error && (
                  <div role="alert" className="flex items-center gap-2 border-b border-border px-4 py-2.5 font-mono text-[11px]" style={{ color: 'var(--urgent)' }}>
                    <span className="min-w-0 flex-1">{t('state.error')}</span>
                    <button onClick={reload} className="shrink-0 font-semibold text-primary hover:underline">{t('state.retry')}</button>
                  </div>
                )}
                {items.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => openItem(n)}
                    className="flex w-full gap-2.5 border-b border-border px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-muted"
                    style={n.read ? undefined : { background: 'color-mix(in srgb, var(--accent) 40%, transparent)' }}
                  >
                    <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: n.read ? 'transparent' : SEV_VAR[n.severity], boxShadow: n.read ? 'inset 0 0 0 1.5px var(--faint)' : undefined }} />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: SEV_VAR[n.severity] }} />
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
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
