import { describe, expect, it } from 'vitest'
import { initialNotificationsState, notificationsReducer } from '../src/lib/notification-state'
import type { CygnusNotification } from '../src/lib/notifications'

// CYG-133 shared notification state contract: one error-aware store shared by
// the bell, revision clouds and the coordinate-bar button. It must never
// present a fetch failure as "no notifications" and mark-read failures must
// revert without affecting navigation (navigation is the caller's job).

function notif(id: string, read = false): CygnusNotification {
  return {
    id,
    kind: 'review_assignment',
    severity: 'medium',
    title: `title-${id}`,
    body: 'body',
    objectRef: `obj-${id}`,
    to: '/console/queue?risk=risk-' + id,
    navKey: 'reviewQueue',
    ownerGap: false,
    read,
  }
}

describe('notificationsReducer', () => {
  it('starts in loading with no items (never empty)', () => {
    expect(initialNotificationsState).toEqual({ items: [], status: 'loading', error: null })
  })

  it('load-success replaces items and clears error', () => {
    const next = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a')] })
    expect(next).toMatchObject({ status: 'ready', error: null })
    expect(next.items).toHaveLength(1)
  })

  it('load-failure with no data flips to error — not empty', () => {
    const err = new Error('boom')
    const next = notificationsReducer(initialNotificationsState, { type: 'load-failure', error: err })
    expect(next.status).toBe('error')
    expect(next.error).toBe(err)
    expect(next.items).toEqual([])
  })

  it('load-failure with stale items stays ready and keeps them visible', () => {
    const loaded = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a')] })
    const next = notificationsReducer(loaded, { type: 'load-failure', error: new Error('boom') })
    expect(next.status).toBe('ready')
    expect(next.error).toBeInstanceOf(Error)
    expect(next.items).toHaveLength(1)
  })

  it('load-start keeps stale items and clears the error while reloading', () => {
    const loaded = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a')] })
    const failed = notificationsReducer(loaded, { type: 'load-failure', error: new Error('boom') })
    const next = notificationsReducer(failed, { type: 'load-start' })
    expect(next.status).toBe('loading')
    expect(next.error).toBeNull()
    expect(next.items).toHaveLength(1)
  })

  it('mark-read-start flips the item optimistically', () => {
    const loaded = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a'), notif('b', true)] })
    const next = notificationsReducer(loaded, { type: 'mark-read-start', id: 'a' })
    expect(next.items.map((n) => n.read)).toEqual([true, true])
  })

  it('mark-read-failure reverts the item and surfaces the error', () => {
    const loaded = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a')] })
    const flipped = notificationsReducer(loaded, { type: 'mark-read-start', id: 'a' })
    const next = notificationsReducer(flipped, { type: 'mark-read-failure', id: 'a', error: new Error('boom') })
    expect(next.items[0].read).toBe(false)
    expect(next.error).toBeInstanceOf(Error)
  })

  it('mark-all-start marks every item read and mark-all-failure restores the snapshot', () => {
    const loaded = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a'), notif('b'), notif('c', true)] })
    const allRead = notificationsReducer(loaded, { type: 'mark-all-start' })
    expect(allRead.items.every((n) => n.read)).toBe(true)
    const restored = notificationsReducer(allRead, { type: 'mark-all-failure', previous: loaded.items, error: new Error('boom') })
    expect(restored.items.map((n) => n.read)).toEqual([false, false, true])
    expect(restored.error).toBeInstanceOf(Error)
  })

  it('unread state converges from the single shared items array', () => {
    const loaded = notificationsReducer(initialNotificationsState, { type: 'load-success', items: [notif('a'), notif('b', true)] })
    const flipped = notificationsReducer(loaded, { type: 'mark-read-start', id: 'a' })
    // One store => every surface derives the same unread count.
    expect(flipped.items.filter((n) => !n.read)).toHaveLength(0)
  })
})
