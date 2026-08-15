import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CloudOff } from 'lucide-react'
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

// Deterministic pseudo-random position per notification ID — spreads clouds across canvas
function cloudPosition(id: string): { x: number; y: number } {
  let hash = 0
  for (let i = 0; i < id.length; i++) hash = ((hash << 5) - hash + id.charCodeAt(i)) | 0
  const x = 80 + Math.abs(hash % 70) * 12  // 80–920 range
  const y = 60 + Math.abs((hash >> 8) % 50) * 10  // 60–560 range
  return { x, y }
}

// SVG revision cloud path — a lumpy circle with arcs
function cloudPath(w: number, h: number): string {
  const cx = w / 2
  const cy = h / 2
  const rx = w / 2 - 2
  const ry = h / 2 - 2
  const bumps = 8
  const pts: string[] = []
  for (let i = 0; i < bumps; i++) {
    const a = (i / bumps) * Math.PI * 2
    const aNext = ((i + 1) / bumps) * Math.PI * 2
    const x2 = cx + Math.cos(aNext) * rx
    const y2 = cy + Math.sin(aNext) * ry
    const mx = cx + Math.cos((a + aNext) / 2) * (rx + 6)
    const my = cy + Math.sin((a + aNext) / 2) * (ry + 6)
    pts.push(`Q ${mx.toFixed(1)} ${my.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`)
  }
  const x0 = cx + rx
  const y0 = cy
  return `M ${x0.toFixed(1)} ${y0.toFixed(1)} ${pts.join(' ')} Z`
}

const CLOUD_W = 48
const CLOUD_H = 36

export function RevisionClouds({ zoom, panX, panY }: { zoom: number; panX: number; panY: number }) {
  const { t } = useTranslation()
  const v = useVocab()
  const navigate = useNavigate()
  const { items, error, reload, markRead, markAllRead } = useNotifications()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const closePanel = useCallback(() => setSelectedId(null), [])
  // Dialog semantics for the detail panel: focus moves in, Tab is trapped,
  // Escape closes, focus returns to the activating cloud.
  useFocusTrap(panelRef, selectedId !== null, closePanel)

  // Navigate FIRST, then optimistically mark read. A mark-read failure reverts
  // in the shared state and surfaces the outage — it never blocks the deep link.
  const openItem = (n: CygnusNotification) => {
    closePanel()
    navigate(n.to)
    markRead(n.id)
  }

  const toggleCloud = (id: string) => setSelectedId((cur) => (cur === id ? null : id))

  // Clicking outside the selected cloud / its panel closes the detail view.
  // Clouds and the panel stop propagation on their own clicks; anything else
  // (blank canvas, page chrome) clears the selection.
  useEffect(() => {
    if (!selectedId) return
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as HTMLElement | null
      if (target?.closest('.bp-cloud, .bp-cloud-panel')) return
      closePanel()
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [selectedId, closePanel])

  // Cap the drawing at the most important clouds (already sorted unread-first
  // by severity in the source) so the canvas never gets crowded.
  const MAX_CLOUDS = 5

  // Group clouds by position to stack nearby ones
  const clouds = items.map((n) => ({
    notif: n,
    pos: cloudPosition(n.id),
  })).slice(0, MAX_CLOUDS)

  const selectedCloud = clouds.find((c) => c.notif.id === selectedId)

  return (
    <>
      {/* Outage visibility: never a blank canvas that reads as "no revisions". */}
      {error && (
        <div
          role="alert"
          className="bp-cloud-error flex items-center gap-2 px-3 py-2 font-mono text-[11px]"
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            zIndex: 60,
            border: '1px solid color-mix(in srgb, var(--urgent) 45%, transparent)',
            background: 'var(--card)',
            color: 'var(--urgent)',
          }}
        >
          <span>{t('state.error')}</span>
          <button onClick={reload} className="font-semibold text-primary hover:underline">{t('state.retry')}</button>
        </div>
      )}

      {/* Cloud markers on the canvas — positioned in drawing coordinates */}
      {clouds.map(({ notif, pos }) => {
        const screenX = pos.x * zoom + panX
        const screenY = pos.y * zoom + panY
        const color = SEV_VAR[notif.severity]
        const isUnread = !notif.read
        const isUrgent = notif.severity === 'urgent'
        const isSelected = notif.id === selectedId
        return (
          <div
            key={notif.id}
            role="button"
            tabIndex={0}
            aria-expanded={isSelected}
            aria-label={`${v.riskType(notif.kind)} · ${notif.title}`}
            className={`bp-cloud ${isUnread ? 'bp-cloud-unread' : 'bp-cloud-read'} ${isUnread && isUrgent ? 'bp-cloud-pulse' : ''}`}
            style={{
              left: `${screenX - (CLOUD_W * zoom) / 2}px`,
              top: `${screenY - (CLOUD_H * zoom) / 2}px`,
            }}
            onClick={(e) => {
              e.stopPropagation()
              toggleCloud(notif.id)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                e.stopPropagation()
                toggleCloud(notif.id)
              }
            }}
          >
            <svg
              width={CLOUD_W * zoom}
              height={CLOUD_H * zoom}
              viewBox={`0 0 ${CLOUD_W} ${CLOUD_H}`}
            >
              <path
                d={cloudPath(CLOUD_W, CLOUD_H)}
                fill="none"
                stroke={color}
                strokeWidth={1.5}
                opacity={isUnread ? 0.8 : 0.3}
              />
            </svg>
            <span className="bp-cloud-tag" style={{ color, borderColor: color }}>
              {notif.title.slice(0, 30)}
            </span>
          </div>
        )
      })}

      {/* Cloud detail panel — appears when a cloud is clicked */}
      {selectedCloud && (
        <div
          ref={panelRef}
          role="dialog"
          aria-label={v.riskType(selectedCloud.notif.kind)}
          className="bp-cloud-panel"
          style={{
            left: `${selectedCloud.pos.x * zoom + panX + 30}px`,
            top: `${selectedCloud.pos.y * zoom + panY - 20}px`,
          }}
        >
          <div className="bp-cloud-panel-header">
            <span className="bp-cloud-panel-title">{v.riskType(selectedCloud.notif.kind)}</span>
            <button
              onClick={markAllRead}
              className="ml-auto font-mono text-[9px] font-semibold text-primary hover:underline"
            >
              {t('cloud.markAllRead')}
            </button>
            <button
              onClick={closePanel}
              aria-label={t('detail.close')}
              className="font-mono text-[10px] text-faint hover:text-foreground"
            >
              ✕
            </button>
          </div>
          <div className="bp-cloud-panel-body">
            <div className="bp-cloud-panel-item">
              <span
                className="bp-cloud-panel-dot"
                style={{ background: SEV_VAR[selectedCloud.notif.severity] }}
              />
              <div className="bp-cloud-panel-item-content">
                <div className="bp-cloud-panel-item-title">{selectedCloud.notif.title}</div>
                <div className="bp-cloud-panel-item-body">{selectedCloud.notif.body}</div>
                <div className="bp-cloud-panel-item-meta">
                  <span style={{ color: 'var(--faint)' }}>@{selectedCloud.notif.objectRef}</span>
                  {selectedCloud.notif.ownerGap && (
                    <span style={{ color: 'var(--high)' }}>· {t('owner.gap')}</span>
                  )}
                </div>
                <button
                  onClick={() => openItem(selectedCloud.notif)}
                  className="mt-2 font-mono text-[10px] font-semibold text-primary hover:underline"
                >
                  {t(`nav.${selectedCloud.notif.navKey}`)} →
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// Coordinate bar summary button — replaces NotificationBell
export function CloudSummaryButton({ onClick }: { onClick: () => void }) {
  const { t } = useTranslation()
  const { items, status, error, unreadCount } = useNotifications()

  const total = items.length

  return (
    <button
      className="bp-cloud-btn"
      data-has-unread={unreadCount > 0 ? 'true' : 'false'}
      data-status={status}
      onClick={onClick}
      aria-label={t('cloud.revisions')}
      title={error ? t('state.error') : t('cloud.showOnDrawing', { n: total })}
    >
      <CloudOff size={12} />
      <span>{t('cloud.revisions')}</span>
      {unreadCount > 0 && <span className="bp-cloud-btn-count">{unreadCount}</span>}
    </button>
  )
}
