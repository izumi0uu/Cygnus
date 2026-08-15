import { useEffect, useRef, type RefObject } from 'react'

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[contenteditable="true"],[tabindex]:not([tabindex="-1"])'

// Traps Tab focus within `ref` while `active`, focuses the first focusable on open,
// calls onEscape on Esc, and restores focus to the prior element on close.
export function useFocusTrap(ref: RefObject<HTMLElement | null>, active: boolean, onEscape?: () => void) {
  const onEscapeRef = useRef(onEscape)
  useEffect(() => {
    onEscapeRef.current = onEscape
  }, [onEscape])

  useEffect(() => {
    if (!active) return
    const element = ref.current
    if (!element) return
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null
    const focusableItems = () => Array.from(element.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((node) => {
      const style = window.getComputedStyle(node)
      return node.getClientRects().length > 0
        && node.getAttribute('aria-hidden') !== 'true'
        && !node.closest('[inert]')
        && style.display !== 'none'
        && style.visibility !== 'hidden'
    })
    const initial = element.querySelector<HTMLElement>('[data-autofocus]') ?? focusableItems()[0] ?? element
    initial.focus({ preventScroll: true })

    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      if (event.key === 'Escape') {
        event.preventDefault()
        onEscapeRef.current?.()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusableItems()
      if (items.length === 0) {
        event.preventDefault()
        element.focus({ preventScroll: true })
        return
      }
      const first = items[0]
      const last = items[items.length - 1]
      if (!element.contains(document.activeElement)) {
        event.preventDefault()
        first.focus()
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      const previousStyle = previous ? window.getComputedStyle(previous) : null
      const canRestore = previous?.isConnected
        && !previous.closest('[inert]')
        && previousStyle?.display !== 'none'
        && previousStyle?.visibility !== 'hidden'
      if (canRestore) previous.focus({ preventScroll: true })
      else document.getElementById('main-content')?.focus({ preventScroll: true })
    }
  }, [active, ref])
}
