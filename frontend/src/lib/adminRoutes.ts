import type { User } from '@/lib/auth'

export function isSystemAdmin(user: Pick<User, 'role'> | null): boolean {
  return user?.role === 'admin'
}

export function auditEventRoute(eventId: string): string {
  return `/console/audit?event=${encodeURIComponent(eventId)}`
}

export function governedObjectRoute(objectRef: string): string {
  return `/console/objects?object=${encodeURIComponent(objectRef)}`
}
