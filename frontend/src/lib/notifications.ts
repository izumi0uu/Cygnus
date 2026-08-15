import {
  fetchNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type PersistedNotification,
} from '@/lib/api'

export type NotifSeverity = 'urgent' | 'high' | 'medium' | 'low'

export type CygnusNotification = {
  id: string
  kind: string
  severity: NotifSeverity
  title: string
  body: string
  objectRef: string
  to: string
  navKey: string
  ownerGap: boolean
  read: boolean
}

export interface NotificationSource {
  list(): Promise<CygnusNotification[]>
  markRead(id: string): Promise<void>
  markAllRead(): Promise<void>
}

const SEV_RANK: Record<NotifSeverity, number> = {
  urgent: 3,
  high: 2,
  medium: 1,
  low: 0,
}

// Exact-target routing: every risk kind resolves to the surface that owns it
// plus the strongest pointer that surface actually consumes. Queue-owned kinds
// select by `?risk=` (matches the review queue's risk_id exactly when a riskId
// is known). Audience-publish consumes `?object_ref=`. Sources and drift
// surfaces have no selection param yet, so they route to their base surface —
// the deep link stays lossless, and the exact-target gap is tracked for the
// page owners.
const ROUTE_BY_RISK: Record<string, { base: string; navKey: string; selectBy: 'risk' | 'object_ref' | 'none' }> = {
  source_blindness: { base: '/console/sources', navKey: 'sources', selectBy: 'none' },
  drift: { base: '/console/drift', navKey: 'drift', selectBy: 'none' },
  audience_mismatch: { base: '/console/audience', navKey: 'audience', selectBy: 'object_ref' },
  ticket_pressure: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
  policy_conflict: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
  owner_gap: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
  review_assignment: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
  review_feedback: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
  review_approved: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
  review_withdrawn: { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' },
}
const FALLBACK_ROUTE = { base: '/console/queue', navKey: 'reviewQueue', selectBy: 'risk' as const }

export type RouteTarget = { riskId?: string; objectRef?: string }

const EVENT_META: Record<string, { kind: string; severity: NotifSeverity }> = {
  submitted: { kind: 'review_assignment', severity: 'medium' },
  resubmitted: { kind: 'review_assignment', severity: 'high' },
  changes_requested: { kind: 'review_feedback', severity: 'high' },
  rejected: { kind: 'review_feedback', severity: 'high' },
  approved: { kind: 'review_approved', severity: 'low' },
  withdrawn: { kind: 'review_withdrawn', severity: 'low' },
}

export function routeForRisk(riskType: string, target?: RouteTarget): { to: string; navKey: string } {
  const route = ROUTE_BY_RISK[riskType] ?? FALLBACK_ROUTE
  if (route.selectBy === 'none') return { to: route.base, navKey: route.navKey }
  const id = target
    ? route.selectBy === 'risk'
      ? (target.riskId ?? target.objectRef)
      : (target.objectRef ?? target.riskId)
    : undefined
  const to = id ? `${route.base}?${route.selectBy}=${encodeURIComponent(id)}` : route.base
  return { to, navKey: route.navKey }
}

function toNotification(record: PersistedNotification): CygnusNotification {
  const event = record.type.split('.').at(-1) ?? ''
  const meta = EVENT_META[event] ?? {
    kind: 'governance_notification',
    severity: 'medium' as const,
  }
  const route = routeForRisk(meta.kind, { objectRef: record.target_id })
  return {
    id: record.id,
    kind: meta.kind,
    severity: meta.severity,
    title: record.subject,
    body: record.body,
    objectRef: record.target_id,
    to: route.to,
    navKey: route.navKey,
    ownerGap: meta.kind === 'owner_gap',
    read: record.lifecycle_state === 'read',
  }
}

export const persistedNotificationSource: NotificationSource = {
  async list() {
    const records = await fetchNotifications()
    return records
      .map(toNotification)
      .sort(
        (left, right) =>
          Number(left.read) - Number(right.read) ||
          SEV_RANK[right.severity] - SEV_RANK[left.severity],
      )
  },
  async markRead(id) {
    await markNotificationRead(id)
  },
  async markAllRead() {
    await markAllNotificationsRead()
  },
}

export const notificationSource: NotificationSource = persistedNotificationSource
