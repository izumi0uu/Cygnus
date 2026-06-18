import type { ComponentType } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  LayoutDashboard,
  ListTodo,
  Boxes,
  Database,
  Users,
  TrendingUp,
  Share2,
  ShieldCheck,
  Search,
  Bell,
} from 'lucide-react'
import { cn } from '@/lib/utils'

type Group = 'gov' | 'obs'
type NavItem = { to: string; key: string; code: string; icon: ComponentType<{ size?: number; className?: string }>; group: Group; end?: boolean; badge?: string }

const NAV: NavItem[] = [
  { to: '/console', key: 'overview', code: 'OVERVIEW', icon: LayoutDashboard, group: 'gov', end: true },
  { to: '/console/queue', key: 'reviewQueue', code: 'REVIEW QUEUE', icon: ListTodo, group: 'gov', badge: '4' },
  { to: '/console/objects', key: 'objects', code: 'KNOWLEDGE OBJECTS', icon: Boxes, group: 'gov' },
  { to: '/console/sources', key: 'sources', code: 'SOURCES & EVIDENCE', icon: Database, group: 'gov' },
  { to: '/console/audience', key: 'audience', code: 'AUDIENCE & PUBLISH', icon: Users, group: 'gov' },
  { to: '/console/drift', key: 'drift', code: 'COVERAGE & DRIFT', icon: TrendingUp, group: 'obs' },
  { to: '/console/propagation', key: 'propagation', code: 'PROPAGATION', icon: Share2, group: 'obs' },
  { to: '/console/audit', key: 'audit', code: 'AUDIT', icon: ShieldCheck, group: 'obs' },
]

function NavGroup({ group }: { group: Group }) {
  const { t } = useTranslation()
  return (
    <div className="mt-1">
      <div className="px-3 pb-1.5 pt-3 font-mono text-[10px] uppercase tracking-[1.2px] text-faint">
        {t(`nav.${group}Group`)}
      </div>
      <nav className="flex flex-col gap-0.5">
        {NAV.filter((i) => i.group === group).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-[9px] px-3 py-2 text-[13.5px] font-medium transition-colors',
                isActive
                  ? 'bg-sidebar-accent text-sidebar-accent-foreground font-semibold'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              )
            }
          >
            <item.icon size={17} className="shrink-0 opacity-90" />
            <span>{t(`nav.${item.key}`)}</span>
            {item.badge && (
              <span className="ml-auto rounded-full bg-primary px-1.5 font-mono text-[10px] font-semibold text-primary-foreground">
                {item.badge}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

export default function AppShell() {
  const { t } = useTranslation()
  const { pathname } = useLocation()
  const active = NAV.find((i) => i.to === pathname) ?? NAV[0]

  return (
    <div className="grid h-screen grid-cols-[248px_1fr] bg-background">
      <aside className="flex flex-col border-r border-sidebar-border bg-sidebar px-3 py-4">
        <div className="flex items-center gap-2.5 px-2.5 pb-2">
          <div className="flex h-[26px] w-[26px] items-center justify-center rounded-[7px] bg-primary text-sm font-extrabold text-primary-foreground">C</div>
          <span className="font-bold tracking-tight">Cygnus</span>
          <span className="ml-auto rounded-md border border-border px-1.5 py-0.5 font-mono text-[9px] text-faint">SUPPORT</span>
        </div>
        <div className="thin-scroll flex-1 overflow-y-auto">
          <NavGroup group="gov" />
          <NavGroup group="obs" />
        </div>
        <div className="mt-2 flex items-center gap-2.5 border-t border-sidebar-border px-1.5 pt-3">
          <div className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-[11px] font-bold text-primary-foreground">ID</div>
          <div className="min-w-0">
            <div className="truncate text-[12.5px] font-semibold">support-lead</div>
            <div className="truncate text-[11px] text-faint">izumi0uu</div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="flex h-[60px] shrink-0 items-center gap-4 border-b border-border bg-card/85 px-6 backdrop-blur">
          <h1 className="font-bold">{t(`nav.${active.key}`)}</h1>
          <span className="font-mono text-[11px] text-faint">{active.code}</span>
          <div className="ml-auto flex w-60 items-center gap-2 rounded-full border border-border bg-muted px-3.5 py-2 text-[12.5px] text-faint">
            <Search size={14} />
            <span>{t('queue.search')}</span>
          </div>
          <button className="flex h-[34px] w-[34px] items-center justify-center rounded-full border border-border bg-card text-muted-foreground hover:bg-muted">
            <Bell size={16} />
          </button>
        </header>
        <main className="flex-1 overflow-y-auto px-6 pb-10 pt-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
