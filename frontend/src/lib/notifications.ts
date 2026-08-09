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

const ROUTE_BY_RISK: Record<string, { to: string; navKey: string }> = {
  source_blindness: { to: '/console/sources', navKey: 'sources' },
  drift: { to: '/console/drift', navKey: 'drift' },
  audience_mismatch: { to: '/console/audience', navKey: 'audience' },
  ticket_pressure: { to: '/console/queue', navKey: 'reviewQueue' },
  policy_conflict: { to: '/console/queue', navKey: 'reviewQueue' },
  owner_gap: { to: '/console/queue', navKey: 'reviewQueue' },
  review_assignment: { to: '/console/queue', navKey: 'reviewQueue' },
  review_feedback: { to: '/console/queue', navKey: 'reviewQueue' },
  review_approved: { to: '/console/queue', navKey: 'reviewQueue' },
  review_withdrawn: { to: '/console/queue', navKey: 'reviewQueue' },
}
const FALLBACK_ROUTE = { to: '/console/queue', navKey: 'reviewQueue' }

const EVENT_META: Record<string, { kind: string; severity: NotifSeverity }> = {
  submitted: { kind: 'review_assignment', severity: 'medium' },
  resubmitted: { kind: 'review_assignment', severity: 'high' },
  changes_requested: { kind: 'review_feedback', severity: 'high' },
  rejected: { kind: 'review_feedback', severity: 'high' },
  approved: { kind: 'review_approved', severity: 'low' },
  withdrawn: { kind: 'review_withdrawn', severity: 'low' },
}

export function routeForRisk(riskType: string): { to: string; navKey: string } {
  return ROUTE_BY_RISK[riskType] ?? FALLBACK_ROUTE
}

function toNotification(record: PersistedNotification): CygnusNotification {
  const event = record.type.split('.').at(-1) ?? ''
  const meta = EVENT_META[event] ?? {
    kind: 'governance_notification',
    severity: 'medium' as const,
  }
  const route = routeForRisk(meta.kind)
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
