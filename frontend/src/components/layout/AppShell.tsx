import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Menu, Search, X } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import ThemeToggle from '@/components/ThemeToggle'
import LangToggle from '@/components/LangToggle'
import NotificationBell from '@/components/NotificationBell'
import { RevisionClouds } from '@/components/RevisionClouds'
import CommandPalette from '@/components/CommandPalette'
import { PageSkeleton } from '@/components/Skeleton'
import { useFocusTrap } from '@/lib/useFocusTrap'

type Group = 'gov' | 'obs' | 'admin'
type NavItem = { to: string; key: string; code: string; group: Group; end?: boolean; adminOnly?: boolean }

const NAV: NavItem[] = [
  { to: '/console', key: 'overview', code: 'DWG-01', group: 'gov', end: true },
  { to: '/console/queue', key: 'reviewQueue', code: 'SEC-A', group: 'gov' },
  { to: '/console/objects', key: 'objects', code: 'SEC-B', group: 'gov' },
  { to: '/console/sources', key: 'sources', code: 'SEC-C', group: 'gov' },
  { to: '/console/tickets', key: 'ticketInsights', code: 'SEC-D', group: 'gov', adminOnly: true },
  { to: '/console/audience', key: 'audience', code: 'SEC-E', group: 'gov' },
  { to: '/console/copilot', key: 'copilot', code: 'SEC-I', group: 'gov' },
  { to: '/console/drift', key: 'drift', code: 'SEC-F', group: 'obs' },
  { to: '/console/propagation', key: 'propagation', code: 'SEC-G', group: 'obs' },
  { to: '/console/audit', key: 'audit', code: 'SEC-H', group: 'obs' },
  { to: '/console/employees', key: 'employees', code: 'ADM-A', group: 'admin', adminOnly: true },
  { to: '/console/roles', key: 'roles', code: 'ADM-B', group: 'admin', adminOnly: true },
  { to: '/console/settings', key: 'settings', code: 'ADM-C', group: 'admin', adminOnly: true },
]

function isNavActive(item: NavItem, pathname: string) {
  return pathname === item.to
    || (!item.end && pathname.startsWith(`${item.to}/`))
    || (item.to === '/console' && pathname.startsWith('/console/recovery/'))
}

function DirGroup({ group, onNavigate, isAdmin, pathname }: { group: Group; onNavigate?: () => void; isAdmin: boolean; pathname: string }) {
  const { t } = useTranslation()
  return (
    <div>
      <h2 className="bp-dir-group">{t(`nav.${group}Group`)}</h2>
      {NAV.filter((i) => i.group === group && (!i.adminOnly || isAdmin)).map((item) => {
        const active = isNavActive(item, pathname)
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={`bp-dir-item${active ? ' is-active' : ''}`}
            data-active={active ? 'true' : 'false'}
            aria-current={active ? 'page' : undefined}
            onClick={onNavigate}
          >
            <span className="bp-dir-vis" aria-hidden="true" />
            <span className="bp-dir-code">{item.code}</span>
            <span>{t(`nav.${item.key}`)}</span>
          </NavLink>
        )
      })}
    </div>
  )
}



export default function AppShell() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
  const active = NAV.find((item) => isNavActive(item, pathname)) ?? NAV[0]
  const sectionTitle = pathname.startsWith('/console/recovery/') ? t('recovery.window') : t(`nav.${active.key}`)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [cloudsVisible, setCloudsVisible] = useState(false)

  // Narrow-viewport navigation drawer (< md breakpoint)
  const [navOpen, setNavOpen] = useState(false)
  const navRef = useRef<HTMLElement>(null)
  const closeNav = useCallback(() => setNavOpen(false), [])
  const closePalette = useCallback(() => setPaletteOpen(false), [])
  useFocusTrap(navRef, navOpen, closeNav)


  // A live viewport resize must not leave the desktop directory behaving as
  // a modal focus trap.
  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 768px)')
    const onChange = (event: MediaQueryListEvent) => {
      if (event.matches) setNavOpen(false)
    }
    desktop.addEventListener('change', onChange)
    return () => desktop.removeEventListener('change', onChange)
  }, [])

  // Preserve native browser zoom and text entry. The only global command
  // shortcut is explicit Mod+K, and it never fires from interactive/modal UI.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.isComposing || event.altKey || event.shiftKey) return
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'k') return
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return
      const target = event.target instanceof Element ? event.target : document.activeElement
      if (
        target instanceof Element
        && target.closest('input, textarea, select, button, a[href], [contenteditable]:not([contenteditable="false"]), [role="dialog"], [aria-modal="true"]')
      ) return
      event.preventDefault()
      setPaletteOpen((open) => !open)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    document.title = `${sectionTitle} · Cygnus`
    return () => { document.title = t('document.baseTitle') }
  }, [sectionTitle, t])

  const mainHeading = `${t('app.surface')} - ${sectionTitle}`

  return (
    <div className="bp-shell grid min-h-dvh min-w-0 grid-cols-1 md:grid-cols-[220px_minmax(0,1fr)]">
      <a className="bp-skip-link" href="#main-content">{t('app.skipToContent')}</a>

      <aside
        ref={navRef}
        className="bp-dir"
        id="bp-nav-drawer"
        data-open={navOpen}
        role={navOpen ? 'dialog' : undefined}
        aria-modal={navOpen || undefined}
        aria-label={t('nav.primary')}
        tabIndex={-1}
      >
        <div className="bp-dir-header">
          <div>
            <div className="bp-dir-dwg-id">{t('app.sheetIndex')}</div>
            <div className="bp-dir-dwg-title">CYGNUS</div>
          </div>
          <button
            type="button"
            onClick={closeNav}
            aria-label={t('nav.close')}
            title={t('nav.close')}
            className="bp-nav-close"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
        <div className="thin-scroll flex-1 overflow-y-auto pb-2">
          <nav aria-label={t('nav.primary')}>
            <DirGroup group="gov" onNavigate={closeNav} isAdmin={user?.role === 'admin'} pathname={pathname} />
            <DirGroup group="obs" onNavigate={closeNav} isAdmin={user?.role === 'admin'} pathname={pathname} />
            {user?.role === 'admin' && <DirGroup group="admin" onNavigate={closeNav} isAdmin pathname={pathname} />}
          </nav>
        </div>
        <div className="bp-dir-footer">
          <div className="bp-dir-footer-info">
            <div className="bp-dir-footer-name">{user?.name}</div>
            <div className="bp-dir-footer-email">{user?.email}</div>
          </div>
          <button
            type="button"
            onClick={logout}
            aria-label={t('auth.logout')}
            title={t('auth.logout')}
            className="bp-dir-footer-btn"
          >
            {t('auth.logout')}
          </button>
        </div>
      </aside>

      {navOpen && <div className="bp-nav-backdrop" aria-hidden="true" onClick={closeNav} />}

      <div className="flex min-h-0 min-w-0 flex-col">
        <header>
          <nav className="bp-coord-bar" aria-label={t('nav.utility')}>
            <button
              type="button"
              className="bp-nav-trigger"
              onClick={() => setNavOpen((open) => !open)}
              aria-expanded={navOpen}
              aria-controls="bp-nav-drawer"
              aria-label={t('nav.menu')}
              title={t('nav.menu')}
            >
              <Menu size={16} aria-hidden="true" />
            </button>
            <span className="bp-coord-dwg">{active.code}</span>
            <span className="bp-coord-sep" aria-hidden="true">/</span>
            <span className="bp-coord-sec">{t(`nav.${active.key}`)}</span>

            <button
              type="button"
              onClick={() => setPaletteOpen(true)}
              className="bp-palette-trigger ml-auto"
              aria-label={t('queue.search')}
              aria-haspopup="dialog"
              aria-expanded={paletteOpen}
              aria-controls="command-palette"
            >
              <Search size={14} aria-hidden="true" />
              <span className="bp-palette-trigger-label">{t('queue.search')}</span>
              <kbd className="bp-palette-trigger-key">{t('palette.shortcut')}</kbd>
            </button>
            <ThemeToggle />
            <LangToggle />
            <NotificationBell cloudsVisible={cloudsVisible} onToggleClouds={() => setCloudsVisible((visible) => !visible)} />
          </nav>
        </header>

        <main id="main-content" tabIndex={-1} aria-label={mainHeading} className="bp-canvas bp-page-container">
          <div className="bp-canvas-grid" aria-hidden="true" />
          <div id="bp-revision-cloud-overlay" className="bp-cloud-overlay" role="region" aria-label={t('cloud.revisions')} aria-hidden={!cloudsVisible}>
            {cloudsVisible && <RevisionClouds zoom={1} panX={0} panY={0} />}
          </div>
          <div className="bp-canvas-inner">
            <Suspense fallback={<PageSkeleton />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>

      <CommandPalette open={paletteOpen} onClose={closePalette} />
    </div>
  )
}
