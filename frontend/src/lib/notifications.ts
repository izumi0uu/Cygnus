import { fetchCommandCenter, type CommandCenterSurface, type PriorityItem } from '@/lib/api'
import { authApi } from '@/lib/authApi'

export type NotifSeverity = 'urgent' | 'high' | 'medium' | 'low'

export type CygnusNotification = {
  id: string
  kind: string // risk_type
  severity: NotifSeverity
  title: string
  body: string
  objectRef: string
  to: string // console route to open
  navKey: string // i18n nav.* key for the target section
  ownerGap: boolean
  read: boolean
}

// Swappable boundary: a derived (read-only) source today; an app.main /api/notifications
// persisted source can implement the same interface later without touching the UI.
export interface NotificationSource {
  list(): Promise<CygnusNotification[]>
  markRead(id: string): Promise<void>
  markAllRead(): Promise<void>
}

const SEV_RANK: Record<NotifSeverity, number> = { urgent: 3, high: 2, medium: 1, low: 0 }

const ROUTE_BY_RISK: Record<string, { to: string; navKey: string }> = {
  source_blindness: { to: '/console/sources', navKey: 'sources' },
  drift: { to: '/console/drift', navKey: 'drift' },
  audience_mismatch: { to: '/console/audience', navKey: 'audience' },
  ticket_pressure: { to: '/console/queue', navKey: 'reviewQueue' },
  policy_conflict: { to: '/console/queue', navKey: 'reviewQueue' },
  owner_gap: { to: '/console/queue', navKey: 'reviewQueue' },
}
const FALLBACK_ROUTE = { to: '/console/queue', navKey: 'reviewQueue' }

export function routeForRisk(riskType: string): { to: string; navKey: string } {
  return ROUTE_BY_RISK[riskType] ?? FALLBACK_ROUTE
}

const READ_KEY = 'cygnus-notif-read'

function readSet(): Set<string> {
  try {
    const raw = localStorage.getItem(READ_KEY)
    return new Set(raw ? (JSON.parse(raw) as string[]) : [])
  } catch {
    return new Set()
  }
}
function writeSet(set: Set<string>) {
  localStorage.setItem(READ_KEY, JSON.stringify([...set]))
}

function toNotification(it: PriorityItem, read: Set<string>): CygnusNotification {
  const route = ROUTE_BY_RISK[it.risk_type] ?? FALLBACK_ROUTE
  return {
    id: it.risk_id,
    kind: it.risk_type,
    severity: (it.urgency as NotifSeverity) ?? 'low',
    title: it.title,
    body: it.why_now_summary,
    objectRef: it.object_ref,
    to: route.to,
    navKey: route.navKey,
    ownerGap: it.owner_state === 'unassigned',
    read: read.has(it.risk_id),
  }
}

function derive(surface: CommandCenterSurface, read: Set<string>): CygnusNotification[] {
  return surface.priority_stack
    .map((it) => toNotification(it, read))
    .sort((a, b) => Number(a.read) - Number(b.read) || SEV_RANK[b.severity] - SEV_RANK[a.severity])
}

// Default source: derive alerts from the command-center feed; read state in localStorage.
export const commandCenterSource: NotificationSource = {
  async list() {
    const surface = await fetchCommandCenter()
    return derive(surface, readSet())
  },
  async markRead(id) {
    const set = readSet()
    set.add(id)
    writeSet(set)
  },
  async markAllRead() {
    const surface = await fetchCommandCenter()
    const set = readSet()
    surface.priority_stack.forEach((it) => set.add(it.risk_id))
    writeSet(set)
  },
}

// app.main persisted-notifications source. Same NotificationSource contract, so it is a
// drop-in for commandCenterSource — but app.main needs a live backend (Postgres), so it is
// only reachable once that infra is up. Select via VITE_NOTIF_SOURCE=arkon.
type ArkonNotification = {
  id: string
  type: string
  subject: string
  body: string
  target_type: string
  target_id: string
  read_at: string | null
  created_at: string
}

export const arkonNotificationSource: NotificationSource = {
  async list() {
    const rows = await authApi<ArkonNotification[]>('/api/notifications')
    return rows.map((n) => ({
      id: String(n.id),
      kind: n.type,
      severity: 'medium' as NotifSeverity, // app.main notifications carry no severity yet
      title: n.subject,
      body: n.body,
      objectRef: n.target_id,
      to: FALLBACK_ROUTE.to,
      navKey: FALLBACK_ROUTE.navKey,
      ownerGap: false,
      read: n.read_at != null,
    }))
  },
  async markRead(id) {
    await authApi(`/api/notifications/${id}/read`, { method: 'POST' })
  },
  async markAllRead() {
    await authApi('/api/notifications/read-all', { method: 'POST' })
  },
}

// Active source. Swap to the persisted backend with VITE_NOTIF_SOURCE=arkon once app.main is live.
export const notificationSource: NotificationSource =
  import.meta.env.VITE_NOTIF_SOURCE === 'arkon' ? arkonNotificationSource : commandCenterSource
