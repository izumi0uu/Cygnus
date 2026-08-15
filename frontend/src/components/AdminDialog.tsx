import { useCallback, useEffect, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useFocusTrap } from '@/lib/useFocusTrap'

export default function AdminDialog({
  titleId,
  descriptionId,
  title,
  description,
  pending = false,
  initialFocusRef,
  onClose,
  children,
}: {
  titleId: string
  descriptionId?: string
  title: string
  description?: string
  pending?: boolean
  initialFocusRef?: RefObject<HTMLElement | null>
  onClose: () => void
  children: ReactNode
}) {
  const { t } = useTranslation()
  const dialogRef = useRef<HTMLDivElement>(null)
  const pendingRef = useRef(pending)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    pendingRef.current = pending
    onCloseRef.current = onClose
  }, [onClose, pending])

  const tryClose = useCallback(() => {
    if (!pendingRef.current) onCloseRef.current()
  }, [])

  useFocusTrap(dialogRef, true, tryClose)

  useEffect(() => {
    initialFocusRef?.current?.focus()
  }, [initialFocusRef])

  return createPortal(
    <div
      className="fixed inset-0 z-[130] flex items-start justify-center overflow-y-auto bg-foreground/30 px-4 pb-10 pt-[8vh]"
      onMouseDown={tryClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        className="bp-panel w-full max-w-[620px] bg-background p-5 outline-none"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="font-mono text-lg font-bold leading-tight">
              {title}
            </h2>
            {description ? (
              <p id={descriptionId} className="mt-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
                {description}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={tryClose}
            disabled={pending}
            className="inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center border border-border bg-card text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t('detail.close')}
          >
            <X aria-hidden="true" size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}
