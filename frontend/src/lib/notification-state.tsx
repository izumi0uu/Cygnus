import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react'
import { notificationSource, type CygnusNotification } from '@/lib/notifications'

// One shared, error-aware notification store for the bell, revision clouds and
// the coordinate-bar summary button. All surfaces read the same items/status/
// error, so their unread state always converges and a fetch failure is never
// presented as "no notifications".

export type NotificationsStatus = 'loading' | 'ready' | 'error'

export type NotificationsState = {
  items: CygnusNotification[]
  status: NotificationsStatus
  error: unknown
}

// eslint-disable-next-line react-refresh/only-export-components
export const initialNotificationsState: NotificationsState = {
  items: [],
  status: 'loading',
  error: null,
}

export type NotificationsAction =
  | { type: 'load-start' }
  | { type: 'load-success'; items: CygnusNotification[] }
  | { type: 'load-failure'; error: unknown }
  | { type: 'mark-read-start'; id: string }
  | { type: 'mark-read-failure'; id: string; error: unknown }
  | { type: 'mark-all-start' }
  | { type: 'mark-all-failure'; previous: CygnusNotification[]; error: unknown }

// eslint-disable-next-line react-refresh/only-export-components
export function notificationsReducer(state: NotificationsState, action: NotificationsAction): NotificationsState {
  switch (action.type) {
    case 'load-start':
      // Keep any stale items during a reload so surfaces never flash empty.
      return { ...state, status: 'loading', error: null }
    case 'load-success':
      return { items: action.items, status: 'ready', error: null }
    case 'load-failure':
      // Never false-empty: with stale items we stay 'ready' (outage banner on
      // top); with nothing loaded we flip to 'error' so surfaces show retry
      // instead of an empty state.
      return { ...state, status: state.items.length > 0 ? 'ready' : 'error', error: action.error }
    case 'mark-read-start':
      return { ...state, items: state.items.map((n) => (n.id === action.id ? { ...n, read: true } : n)) }
    case 'mark-read-failure':
      return {
        ...state,
        items: state.items.map((n) => (n.id === action.id ? { ...n, read: false } : n)),
        error: action.error,
      }
    case 'mark-all-start':
      return { ...state, items: state.items.map((n) => ({ ...n, read: true })) }
    case 'mark-all-failure':
      return { ...state, items: action.previous, error: action.error }
  }
}

type NotificationsContextValue = NotificationsState & {
  unreadCount: number
  /** Re-fetch the notification list; surfaces use this as their retry action. */
  reload: () => void
  /**
   * Optimistic read. The item flips immediately; on failure it reverts and the
   * error surfaces. Callers must navigate BEFORE awaiting/using this — a
   * mark-read failure never blocks navigation.
   */
  markRead: (id: string) => void
  /** Optimistic mark-all-read; on failure the previous state is restored. */
  markAllRead: () => void
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null)

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(notificationsReducer, initialNotificationsState)
  const itemsRef = useRef(state.items)
  useEffect(() => {
    itemsRef.current = state.items
  }, [state.items])

  const reload = useCallback(async () => {
    dispatch({ type: 'load-start' })
    try {
      const items = await notificationSource.list()
      dispatch({ type: 'load-success', items })
    } catch (error) {
      dispatch({ type: 'load-failure', error })
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const markRead = useCallback((id: string) => {
    dispatch({ type: 'mark-read-start', id })
    notificationSource.markRead(id).catch((error) => dispatch({ type: 'mark-read-failure', id, error }))
  }, [])

  const markAllRead = useCallback(() => {
    const previous = itemsRef.current
    dispatch({ type: 'mark-all-start' })
    notificationSource.markAllRead().catch((error) => dispatch({ type: 'mark-all-failure', previous, error }))
  }, [])

  const value = useMemo<NotificationsContextValue>(
    () => ({
      ...state,
      unreadCount: state.items.filter((n) => !n.read).length,
      reload,
      markRead,
      markAllRead,
    }),
    [state, reload, markRead, markAllRead],
  )

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext)
  if (!ctx) throw new Error('useNotifications must be used within NotificationProvider')
  return ctx
}
