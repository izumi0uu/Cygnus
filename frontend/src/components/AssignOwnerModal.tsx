import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import {
  executeReviewAssignment,
  REVIEW_ASSIGNMENT_REASON_MAX_LENGTH,
  REVIEW_ASSIGNMENT_REF_MAX_LENGTH,
  type ReviewAssignmentAction,
  type ReviewAssignmentCommandResult,
} from '@/lib/api'
import { ApiError } from '@/lib/authApi'
import { useVocab } from '@/lib/vocab'
import { useFocusTrap } from '@/lib/useFocusTrap'

/**
 * AssignOwnerModal — durable owner command dialog for one governance signal.
 *
 * Sends assign/escalate/release to POST /api/review-assignments/{signal_ref}/commands
 * with the exact payload contract ({command_id, action, owner_ref, reason,
 * expected_version}). Success is never claimed optimistically: the response
 * receipt is handed to the caller (onExecuted) only after the server answers,
 * and the dialog closes so the drawer can show the durable receipt stamp and
 * re-read authoritative state. Client-side validation blocks blank owner
 * (assign/escalate) and blank reason before any request is sent.
 */
export default function AssignOwnerModal({
  action,
  signalRef,
  expectedVersion,
  currentOwner,
  currentState,
  onExecuted,
  onRefresh,
  onClose,
}: {
  action: ReviewAssignmentAction
  signalRef: string
  expectedVersion: number
  currentOwner: string | null
  currentState: string
  onExecuted: (result: ReviewAssignmentCommandResult) => void
  /** Background re-read request, e.g. after a 409 expected_version conflict. */
  onRefresh?: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const ref = useRef<HTMLDivElement>(null)
  const ownerRef = useRef<HTMLInputElement>(null)
  const reasonRef = useRef<HTMLTextAreaElement>(null)
  const needsOwner = action !== 'release'
  // Prefill the durable current owner for reassignment/escalation; release
  // always sends owner_ref: null and renders no owner field.
  const [owner, setOwner] = useState(needsOwner ? (currentOwner ?? '') : '')
  const [reason, setReason] = useState('')
  const [errors, setErrors] = useState({ owner: false, reason: false })
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  // One command id per dialog opening: a retry after a transport failure is an
  // idempotent replay of the same durable command, never a second write.
  const [commandId] = useState(() => `review-assignment:${action}:${crypto.randomUUID()}`)

  // Close is blocked mid-flight so a durable write is never abandoned
  // silently. The identity must stay stable across keystroke re-renders —
  // useFocusTrap re-runs (and steals focus) whenever its onEscape changes.
  // pendingRef is written only where pending flips, never during render.
  const pendingRef = useRef(false)
  const tryClose = useCallback(() => {
    if (!pendingRef.current) onClose()
  }, [onClose])
  useFocusTrap(ref, true, tryClose)

  // Initial focus lands on the first editable field (the trap's default is the
  // header close button, which is a poor starting point for a form).
  useEffect(() => {
    ;(needsOwner ? ownerRef.current : reasonRef.current)?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const submit = () => {
    if (pending) return
    const next = { owner: needsOwner && !owner.trim(), reason: !reason.trim() }
    setErrors(next)
    if (next.owner) {
      ownerRef.current?.focus()
      return
    }
    if (next.reason) {
      reasonRef.current?.focus()
      return
    }
    pendingRef.current = true
    setPending(true)
    setServerError(null)
    executeReviewAssignment(signalRef, {
      command_id: commandId,
      action,
      owner_ref: needsOwner ? owner.trim() : null,
      reason: reason.trim(),
      expected_version: expectedVersion,
    })
      .then((result) => {
        onExecuted(result)
        onClose()
      })
      .catch((e) => {
        setServerError(e instanceof Error ? e.message : String(e))
        // Stale expected_version: the durable state moved on, so ask the queue
        // to re-read before the next attempt.
        if (e instanceof ApiError && e.status === 409) onRefresh?.()
      })
      .finally(() => {
        pendingRef.current = false
        setPending(false)
      })
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[120] flex items-start justify-center overflow-y-auto bg-foreground/30 px-4 pb-10 pt-[10vh]"
      onMouseDown={tryClose}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby="assign-cmd-title"
        tabIndex={-1}
        className="bp-panel w-full max-w-[440px] bg-background p-5 outline-none"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <span className={`bp-tol ${action === 'escalate' ? 'bp-tol-urgent' : 'bp-tol-high'}`}>{t('assign.eyebrow')}</span>
          <button
            className="ml-auto flex h-8 w-8 items-center justify-center bp-panel text-muted-foreground hover:bg-muted disabled:opacity-50"
            aria-label={t('detail.close')}
            onClick={tryClose}
            disabled={pending}
          >
            <X size={15} />
          </button>
        </div>
        <h2 id="assign-cmd-title" className="mt-3 font-mono text-base font-bold leading-tight">
          {t(`assign.title.${action}`)}
        </h2>
        <div className="mt-1 font-mono text-[10px] text-faint">
          {signalRef} · {t('assign.version')} {expectedVersion}
        </div>

        <div className="bp-dim mt-4 pt-3.5">
          <div className="mb-2 bp-label">{t('assign.currentState')}</div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`bp-tol ${
                currentState === 'escalated' ? 'bp-tol-urgent' : currentState === 'assigned' ? 'bp-tol-ok' : 'bp-tol-high'
              }`}
            >
              {v.assignmentState(currentState)}
            </span>
            {currentOwner && <span className="font-mono text-[11px] text-muted-foreground">@{currentOwner}</span>}
          </div>
        </div>

        <form
          className="mt-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          {needsOwner && (
            <div>
              <label htmlFor="assign-owner" className="bp-label">
                {t('assign.owner')}
              </label>
              <input
                id="assign-owner"
                ref={ownerRef}
                value={owner}
                onChange={(e) => {
                  setOwner(e.target.value)
                  if (e.target.value.trim()) setErrors((p) => ({ ...p, owner: false }))
                }}
                disabled={pending}
                required
                maxLength={REVIEW_ASSIGNMENT_REF_MAX_LENGTH}
                autoComplete="off"
                spellCheck={false}
                placeholder={t('assign.ownerPlaceholder')}
                aria-invalid={errors.owner || undefined}
                aria-describedby={errors.owner ? 'assign-owner-err' : undefined}
                className="mt-1.5 w-full border border-border bg-transparent px-2.5 py-2 font-mono text-[12.5px] outline-none transition-colors focus:border-[var(--primary)] disabled:opacity-50"
              />
              {errors.owner && (
                <p id="assign-owner-err" role="alert" className="mt-1.5 font-mono text-[10.5px]" style={{ color: 'var(--urgent)' }}>
                  {t('assign.ownerRequired')}
                </p>
              )}
            </div>
          )}
          {action === 'release' && (
            <p className="font-mono text-[10.5px] leading-relaxed text-muted-foreground">{t('assign.releaseNote')}</p>
          )}
          <div className="mt-3.5">
            <label htmlFor="assign-reason" className="bp-label">
              {t('assign.reason')}
            </label>
            <textarea
              id="assign-reason"
              ref={reasonRef}
              rows={3}
              value={reason}
              onChange={(e) => {
                setReason(e.target.value)
                if (e.target.value.trim()) setErrors((p) => ({ ...p, reason: false }))
              }}
              disabled={pending}
              required
              maxLength={REVIEW_ASSIGNMENT_REASON_MAX_LENGTH}
              placeholder={t('assign.reasonPlaceholder')}
              aria-invalid={errors.reason || undefined}
              aria-describedby={errors.reason ? 'assign-reason-err' : undefined}
              className="mt-1.5 w-full resize-y border border-border bg-transparent px-2.5 py-2 font-mono text-[12.5px] leading-relaxed outline-none transition-colors focus:border-[var(--primary)] disabled:opacity-50"
            />
            {errors.reason && (
              <p id="assign-reason-err" role="alert" className="mt-1.5 font-mono text-[10.5px]" style={{ color: 'var(--urgent)' }}>
                {t('assign.reasonRequired')}
              </p>
            )}
          </div>

          {serverError && (
            <div
              role="alert"
              className="mt-3.5 border px-3 py-2 font-mono text-[11px] leading-relaxed"
              style={{
                color: 'var(--urgent)',
                borderColor: 'color-mix(in srgb, var(--urgent) 40%, transparent)',
                background: 'color-mix(in srgb, var(--urgent) 8%, transparent)',
              }}
            >
              {t('assign.failed')}: {serverError}
            </div>
          )}

          <div className="mt-5 flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={tryClose}
              disabled={pending}
              className="bp-panel px-3 py-1.5 font-mono text-[11px] text-muted-foreground hover:bg-muted disabled:opacity-50"
            >
              {t('assign.cancel')}
            </button>
            <button type="submit" disabled={pending} className="bp-cmd disabled:cursor-not-allowed disabled:opacity-50">
              {pending ? t('assign.executing') : t('assign.execute')}
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  )
}
