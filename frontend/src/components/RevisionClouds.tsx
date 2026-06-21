import { useEffect, useRef, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { CloudOff } from 'lucide-react'
import { useVocab } from '@/lib/vocab'
import { notificationSource, type CygnusNotification, type NotifSeverity } from '@/lib/notifications'

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
  const [items, setItems] = useState<CygnusNotification[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const load = useCallback(() => {
    notificationSource.list().then(setItems).catch(() => setItems([]))
  }, [])
  useEffect(load, [load])

  const openItem = async (n: CygnusNotification) => {
    if (!n.read) {
      await notificationSource.markRead(n.id)
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)))
    }
    setSelectedId(null)
    navigate(n.to)
  }

  const markAll = async () => {
    await notificationSource.markAllRead()
    setItems((prev) => prev.map((x) => ({ ...x, read: true })))
  }

  // Group clouds by position to stack nearby ones
  const clouds = items.map((n) => ({
    notif: n,
    pos: cloudPosition(n.id),
  }))

  const selectedCloud = clouds.find((c) => c.notif.id === selectedId)

  return (
    <>
      {/* Cloud markers on the canvas — positioned in drawing coordinates */}
      {clouds.map(({ notif, pos }) => {
        const screenX = pos.x * zoom + panX
        const screenY = pos.y * zoom + panY
        const color = SEV_VAR[notif.severity]
        const isUnread = !notif.read
        const isUrgent = notif.severity === 'urgent'
        return (
          <div
            key={notif.id}
            className={`bp-cloud ${isUnread ? 'bp-cloud-unread' : 'bp-cloud-read'} ${isUnread && isUrgent ? 'bp-cloud-pulse' : ''}`}
            style={{
              left: `${screenX - (CLOUD_W * zoom) / 2}px`,
              top: `${screenY - (CLOUD_H * zoom) / 2}px`,
            }}
            onClick={(e) => {
              e.stopPropagation()
              setSelectedId(notif.id === selectedId ? null : notif.id)
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
          className="bp-cloud-panel"
          style={{
            left: `${selectedCloud.pos.x * zoom + panX + 30}px`,
            top: `${selectedCloud.pos.y * zoom + panY - 20}px`,
          }}
        >
          <div className="bp-cloud-panel-header">
            <span className="bp-cloud-panel-title">{v.riskType(selectedCloud.notif.kind)}</span>
            <button
              onClick={markAll}
              className="ml-auto font-mono text-[9px] font-semibold text-primary hover:underline"
            >
              {t('cloud.markAllRead')}
            </button>
            <button
              onClick={() => setSelectedId(null)}
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
                    <span style={{ color: 'var(--high)' }}>· owner gap</span>
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
  const [items, setItems] = useState<CygnusNotification[]>([])

  useEffect(() => {
    notificationSource.list().then(setItems).catch(() => setItems([]))
  }, [])

  const unreadCount = items.filter((n) => !n.read).length
  const total = items.length

  return (
    <button
      className="bp-cloud-btn"
      data-has-unread={unreadCount > 0 ? 'true' : 'false'}
      onClick={onClick}
      aria-label={t('cloud.revisions')}
      title={t('cloud.showOnDrawing', { n: total })}
    >
      <CloudOff size={12} />
      <span>{t('cloud.revisions')}</span>
      {unreadCount > 0 && <span className="bp-cloud-btn-count">{unreadCount}</span>}
    </button>
  )
}
