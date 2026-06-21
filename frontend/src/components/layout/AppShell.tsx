import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Search, Plus, Minus, Maximize2 } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { useZoom } from '@/lib/zoom'
import { useToast } from '@/lib/toast'
import ThemeToggle from '@/components/ThemeToggle'
import LangToggle from '@/components/LangToggle'
import NotificationBell from '@/components/NotificationBell'
import { RevisionClouds } from '@/components/RevisionClouds'
import CommandPalette from '@/components/CommandPalette'

type Group = 'gov' | 'obs'
type NavItem = { to: string; key: string; code: string; group: Group; end?: boolean; badge?: string }

const NAV: NavItem[] = [
  { to: '/console', key: 'overview', code: 'DWG-01', group: 'gov', end: true },
  { to: '/console/queue', key: 'reviewQueue', code: 'SEC-A', group: 'gov', badge: '4' },
  { to: '/console/objects', key: 'objects', code: 'SEC-B', group: 'gov' },
  { to: '/console/sources', key: 'sources', code: 'SEC-C', group: 'gov' },
  { to: '/console/audience', key: 'audience', code: 'SEC-D', group: 'gov' },
  { to: '/console/drift', key: 'drift', code: 'SEC-E', group: 'obs' },
  { to: '/console/propagation', key: 'propagation', code: 'SEC-F', group: 'obs' },
  { to: '/console/audit', key: 'audit', code: 'SEC-G', group: 'obs' },
]

function DirGroup({ group }: { group: Group }) {
  const { t } = useTranslation()
  return (
    <div>
      <div className="bp-dir-group">{t(`nav.${group}Group`)}</div>
      {NAV.filter((i) => i.group === group).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className="bp-dir-item"
        >
          {({ isActive }) => (
            <>
              <span className="bp-dir-vis" data-active={isActive ? 'true' : 'false'} />
              <span className="bp-dir-code">{item.code}</span>
              <span>{t(`nav.${item.key}`)}</span>
              {item.badge && <span className="bp-dir-badge">{item.badge}</span>}
            </>
          )}
        </NavLink>
      ))}
    </div>
  )
}

// Dynamic grid background — grid size scales with zoom level
function CanvasGrid({ zoom }: { zoom: number }) {
  const major = 80 * zoom
  const minor = 20 * zoom
  return (
    <div
      className="bp-canvas-grid"
      style={{
        backgroundImage: `
          linear-gradient(color-mix(in srgb, var(--primary) 7%, transparent) 1px, transparent 1px),
          linear-gradient(90deg, color-mix(in srgb, var(--primary) 7%, transparent) 1px, transparent 1px),
          linear-gradient(color-mix(in srgb, var(--primary) 3%, transparent) 1px, transparent 1px),
          linear-gradient(90deg, color-mix(in srgb, var(--primary) 3%, transparent) 1px, transparent 1px)
        `,
        backgroundSize: `${major}px ${major}px, ${major}px ${major}px, ${minor}px ${minor}px, ${minor}px ${minor}px`,
        backgroundPosition: '0 0',
      }}
    />
  )
}

export default function AppShell() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const active = NAV.find((i) => i.to === pathname) ?? NAV[0]
  const [paletteOpen, setPaletteOpen] = useState(false)
  const { zoom, panX, panY, zoomIn, zoomOut, zoomFit, setZoom, panBy, resetView } = useZoom()
  const toast = useToast()

  const canvasRef = useRef<HTMLDivElement>(null)
  const [isPanning, setIsPanning] = useState(false)
  const [mouseCoord, setMouseCoord] = useState({ x: 0, y: 0 })
  const [cloudsVisible, setCloudsVisible] = useState(true)

  // Reset view when navigating between sections
  useEffect(() => {
    resetView()
  }, [pathname, resetView])

  // P3: Click coordinate readout to copy
  const copyCoord = useCallback(() => {
    const coord = `${mouseCoord.x},${mouseCoord.y}`
    navigator.clipboard?.writeText(coord).then(
      () => toast(t('coord.copied')),
      () => {},
    )
  }, [mouseCoord, toast, t])

  // Mouse wheel — Ctrl/⌘ + wheel = zoom, plain wheel = native scroll
  const onWheel = useCallback((e: React.WheelEvent) => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault()
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const mouseX = e.clientX - rect.left
      const mouseY = e.clientY - rect.top
      const delta = e.deltaY > 0 ? -0.1 : 0.1
      const newZoom = Math.max(0.5, Math.min(2.0, Math.round((zoom + delta) * 100) / 100))
      const zoomRatio = newZoom / zoom
      setZoom(newZoom)
      panBy(mouseX - mouseX * zoomRatio, mouseY - mouseY * zoomRatio)
    }
  }, [zoom, setZoom, panBy])

  // Drag to pan — limited to a small range (~25px) for a subtle nudge feel
  const MAX_PAN = 25
  const panStartRef = useRef<{ x: number; y: number } | null>(null)
  const lastMoveRef = useRef<{ x: number; y: number } | null>(null)
  const panOriginRef = useRef<{ panX: number; panY: number }>({ panX: 0, panY: 0 })

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    const target = e.target as HTMLElement
    if (target.closest('button, a, input, [role="button"], [role="checkbox"], .bp-panel, .bp-cloud, .bp-cloud-panel')) return
    setIsPanning(true)
    panStartRef.current = { x: e.clientX, y: e.clientY }
    panOriginRef.current = { panX, panY }
    lastMoveRef.current = { x: e.clientX, y: e.clientY }
  }, [panX, panY])

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    const canvas = canvasRef.current
    if (canvas) {
      const rect = canvas.getBoundingClientRect()
      setMouseCoord({
        x: Math.round((e.clientX - rect.left - panX) / zoom),
        y: Math.round((e.clientY - rect.top - panY) / zoom),
      })
    }
    if (!isPanning || !panStartRef.current) return
    const rawDx = e.clientX - panStartRef.current.x
    const rawDy = e.clientY - panStartRef.current.y
    const clamp = (raw: number) => {
      if (Math.abs(raw) <= MAX_PAN) return raw
      const sign = raw > 0 ? 1 : -1
      const overshoot = Math.abs(raw) - MAX_PAN
      return sign * (MAX_PAN + overshoot * 0.15)
    }
    const targetPanX = panOriginRef.current.panX + clamp(rawDx)
    const targetPanY = panOriginRef.current.panY + clamp(rawDy)
    panBy(targetPanX - panX, targetPanY - panY)
    lastMoveRef.current = { x: e.clientX, y: e.clientY }
  }, [isPanning, panX, panY, zoom, panBy])

  const onMouseUp = useCallback(() => {
    setIsPanning(false)
    panStartRef.current = null
    lastMoveRef.current = null
    resetView()
  }, [resetView])

  // Keyboard shortcuts for zoom
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = document.activeElement as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return
      if (e.key === '+' || e.key === '=') { e.preventDefault(); zoomIn() }
      else if (e.key === '-') { e.preventDefault(); zoomOut() }
      else if (e.key === '0' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); zoomFit() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [zoomIn, zoomOut, zoomFit])

  // g-key navigation + command palette
  useEffect(() => {
    const GO: Record<string, string> = {
      o: '/console', q: '/console/queue', k: '/console/objects', s: '/console/sources',
      a: '/console/audience', d: '/console/drift', p: '/console/propagation', t: '/console/audit',
    }
    const isTyping = () => {
      const el = document.activeElement as HTMLElement | null
      return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)
    }
    let gPending = false
    let gTimer: ReturnType<typeof setTimeout> | undefined
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((o) => !o)
        return
      }
      if (isTyping()) return
      if (e.key === '/') { e.preventDefault(); setPaletteOpen(true); return }
      if (e.key === 'g') { gPending = true; clearTimeout(gTimer); gTimer = setTimeout(() => { gPending = false }, 1200); return }
      if (gPending) {
        gPending = false
        const to = GO[e.key.toLowerCase()]
        if (to) { e.preventDefault(); navigate(to) }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('keydown', onKey); clearTimeout(gTimer) }
  }, [navigate])

  const scaleLabel = `${zoom.toFixed(2)}:1`

  return (
    <div className="grid h-screen grid-cols-[220px_1fr]">
      {/* Drawing directory panel */}
      <aside className="bp-dir">
        <div className="bp-dir-header">
          <div className="bp-dir-dwg-id">DWG-SHEET · 1/1</div>
          <div className="bp-dir-dwg-title">CYGNUS</div>
        </div>
        <div className="thin-scroll flex-1 overflow-y-auto pb-2">
          <DirGroup group="gov" />
          <DirGroup group="obs" />
        </div>
        <div className="bp-dir-footer">
          <div className="bp-dir-footer-info">
            <div className="bp-dir-footer-name">{user?.name ?? 'support-lead'}</div>
            <div className="bp-dir-footer-email">{user?.email ?? 'admin@cygnus.local'}</div>
          </div>
          <button
            onClick={logout}
            aria-label={t('auth.logout')}
            title={t('auth.logout')}
            className="bp-dir-footer-btn"
          >
            EXIT
          </button>
        </div>
      </aside>

      {/* Main drawing area */}
      <div className="flex min-w-0 flex-col">
        {/* Coordinate bar */}
        <div className="bp-coord-bar">
          <span className="bp-coord-dwg">{active.code}</span>
          <span className="bp-coord-sep">/</span>
          <span className="bp-coord-sec">{t(`nav.${active.key}`)}</span>

          {/* P3: Clickable coordinate readout — click to copy */}
          <span className="bp-coord-sep">·</span>
          <button
            className="bp-coord-readout"
            onClick={copyCoord}
            title={t('coord.copied')}
          >
            X:{mouseCoord.x} Y:{mouseCoord.y}
          </button>

          {/* Zoom controls */}
          <div className="bp-zoom-ctrl ml-4">
            <button className="bp-zoom-btn" onClick={zoomOut} aria-label="Zoom out" title="Zoom out (−)">
              <Minus size={13} />
            </button>
            <span className="bp-zoom-display">{(zoom * 100).toFixed(0)}%</span>
            <button className="bp-zoom-btn" onClick={zoomIn} aria-label="Zoom in" title="Zoom in (+)">
              <Plus size={13} />
            </button>
            <button className="bp-zoom-btn" onClick={zoomFit} aria-label="Fit to screen" title="Fit (⌘0)">
              <Maximize2 size={12} />
            </button>
          </div>

          <button
            onClick={() => setPaletteOpen(true)}
            className="ml-auto flex items-center gap-2 border border-[color-mix(in_srgb,var(--primary)_25%,transparent)] bg-transparent px-3 py-1.5 font-mono text-[11px] text-faint transition-all hover:border-[color-mix(in_srgb,var(--primary)_50%,transparent)] hover:text-foreground"
            style={{ borderRadius: 0 }}
          >
            <Search size={12} />
            <span>{t('queue.search')}</span>
            <kbd className="font-mono text-[9px] opacity-50">⌘K</kbd>
          </button>
          <ThemeToggle />
          <LangToggle />
          <NotificationBell cloudsVisible={cloudsVisible} onToggleClouds={() => setCloudsVisible((v) => !v)} />
        </div>

        {/* Drawing canvas — zoomable + pannable */}
        <div
          ref={canvasRef}
          className="bp-canvas"
          data-panning={isPanning}
          onWheel={onWheel}
          onMouseDown={onMouseDown}
          onMouseMove={onMouseMove}
          onMouseUp={onMouseUp}
          onMouseLeave={onMouseUp}
        >
          <CanvasGrid zoom={zoom} />

          {/* P4: Revision cloud notifications on canvas */}
          {cloudsVisible && (
            <RevisionClouds zoom={zoom} panX={panX} panY={panY} />
          )}

          {/* Transformed content layer */}
          <div
            className="bp-canvas-inner"
            style={{ transform: `translate(${panX}px, ${panY}px) scale(${zoom})` }}
          >
            <Suspense fallback={<div className="font-mono text-sm text-muted-foreground p-6">{t('state.loading')}</div>}>
              <Outlet />
            </Suspense>
          </div>
        </div>
      </div>

      {/* Title block */}
      <div className="bp-titleblock">
        <div className="bp-tb-col">
          <div className="bp-tb-col-key">DWG</div>
          <div className="bp-tb-col-val">{active.code}</div>
        </div>
        <div className="bp-tb-col">
          <div className="bp-tb-col-key">SCALE</div>
          <div className="bp-tb-col-val">{scaleLabel}</div>
        </div>
        <div className="bp-tb-col">
          <div className="bp-tb-col-key">REV</div>
          <div className="bp-tb-col-val">2026.06</div>
        </div>
        <div className="bp-tb-col">
          <div className="bp-tb-col-key">DRAFTED BY</div>
          <div className="bp-tb-col-val">{(user?.name || 'ID').slice(0, 8)}</div>
        </div>
      </div>

      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  )
}
