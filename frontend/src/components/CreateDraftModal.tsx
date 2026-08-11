import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'
import {
  promoteTicketClusterToDraft,
  TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH,
  type TicketDraftPromotionResult,
} from '@/lib/api'
import { ApiError } from '@/lib/authApi'
import { useFocusTrap } from '@/lib/useFocusTrap'
import { useVocab } from '@/lib/vocab'

/**
 * Reviewer-controlled promotion of one qualifying ticket-cluster signal into a
 * durable draft. One modal opening owns one stable command ID, so an exact
 * retry remains an idempotent replay. The modal stays open after success and
 * shows the server receipt before the reviewer refreshes the queue on close.
 */
export default function CreateDraftModal({
  signalRef,
  objectRef,
  expectedAssignmentVersion,
  onRefresh,
  onClose,
}: {
  signalRef: string
  objectRef: string
  expectedAssignmentVersion: number
  /** Authoritative background re-read after a 409 or after closing success. */
  onRefresh?: () => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const dialogRef = useRef<HTMLDivElement>(null)
  const reasonRef = useRef<HTMLTextAreaElement>(null)
  const receiptCloseRef = useRef<HTMLButtonElement>(null)
  const [reason, setReason] = useState('')
  const [reasonMissing, setReasonMissing] = useState(false)
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState<string | null>(null)
  const [staleConflict, setStaleConflict] = useState(false)
  const [result, setResult] = useState<TicketDraftPromotionResult | null>(null)
  const [commandId] = useState(() => `ticket-draft-promotion:${crypto.randomUUID()}`)

  // Mutable refs keep close semantics current without changing the focus trap's
  // callback identity after a background queue refresh.
  const pendingRef = useRef(false)
  const resultRef = useRef<TicketDraftPromotionResult | null>(null)
  const refreshRequestedRef = useRef(false)
  const onRefreshRef = useRef(onRefresh)
  const onCloseRef = useRef(onClose)
  useEffect(() => {
    onRefreshRef.current = onRefresh
    onCloseRef.current = onClose
  }, [onRefresh, onClose])

  const tryClose = useCallback(() => {
    if (pendingRef.current) return
    if (resultRef.current && !refreshRequestedRef.current) {
      refreshRequestedRef.current = true
      onRefreshRef.current?.()
    }
    onCloseRef.current()
  }, [])
  useFocusTrap(dialogRef, true, tryClose)

  // The ReviewQueue drawer also owns a focus trap. Intercept Escape before its
  // document listener so the parent drawer cannot unmount a pending command.
  useEffect(() => {
    const interceptEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      event.stopImmediatePropagation()
      tryClose()
    }
    document.addEventListener('keydown', interceptEscape, true)
    return () => document.removeEventListener('keydown', interceptEscape, true)
  }, [tryClose])

  useEffect(() => {
    reasonRef.current?.focus()
  }, [])

  useEffect(() => {
    if (result && !pending) receiptCloseRef.current?.focus()
  }, [pending, result])

  const submit = () => {
    if (pending || result) return
    const normalizedReason = reason.trim()
    if (!normalizedReason) {
      setReasonMissing(true)
      reasonRef.current?.focus()
      return
    }

    pendingRef.current = true
    setPending(true)
    setServerError(null)
    setStaleConflict(false)
    promoteTicketClusterToDraft(signalRef, {
      command_id: commandId,
      reason: normalizedReason,
      expected_assignment_version: expectedAssignmentVersion,
    })
      .then((nextResult) => {
        resultRef.current = nextResult
        setResult(nextResult)
      })
      .catch((error) => {
        setServerError(error instanceof Error ? error.message : String(error))
        if (error instanceof ApiError && error.status === 409) {
          setStaleConflict(true)
          onRefreshRef.current?.()
        }
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
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="create-draft-title"
        aria-describedby="create-draft-description"
        tabIndex={-1}
        className="bp-panel w-full max-w-[480px] bg-background p-5 outline-none"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2">
          <span className="bp-tol bp-tol-high">{t('draftPromotion.eyebrow')}</span>
          <button
            type="button"
            className="ml-auto flex h-8 w-8 items-center justify-center bp-panel text-muted-foreground hover:bg-muted disabled:opacity-50"
            aria-label={t('detail.close')}
            onClick={tryClose}
            disabled={pending}
          >
            <X size={15} />
          </button>
        </div>
        <h2 id="create-draft-title" className="mt-3 font-mono text-base font-bold leading-tight">
          {result ? t('draftPromotion.successTitle') : t('draftPromotion.title')}
        </h2>
        <div className="mt-1 font-mono text-[10px] leading-relaxed text-faint">
          <span className="break-all">{signalRef}</span> · {t('draftPromotion.assignmentVersion')}{' '}
          {expectedAssignmentVersion}
          <br />
          <span className="break-all">{objectRef}</span>
        </div>
        <p id="create-draft-description" className="mt-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {t('draftPromotion.description')}
        </p>

        {result ? (
          <div className="mt-4" role="status" aria-live="polite">
            <div
              className="border px-3 py-3"
              style={{
                borderColor: 'color-mix(in srgb, var(--ok) 40%, transparent)',
                background: 'color-mix(in srgb, var(--ok) 6%, transparent)',
              }}
            >
              <div className="flex flex-wrap items-center gap-2">
                {result.promotion.persisted && (
                  <span className="bp-stamp" style={{ color: 'var(--ok)' }}>
                    {t('draftPromotion.persisted')}
                  </span>
                )}
                <span className="bp-tol bp-tol-flat">
                  {result.replayed ? t('draftPromotion.replayed') : t('draftPromotion.firstExecution')}
                </span>
              </div>
              <div className="mt-3 font-mono text-[12.5px] font-semibold leading-snug">{result.draft.title}</div>
              <div className="mt-1 font-mono text-[10px] text-faint">{v.objectType(result.draft.object_type)}</div>
              <dl className="mt-3 space-y-1.5 font-mono text-[10.5px] leading-relaxed text-muted-foreground">
                <ReceiptRow label={t('draftPromotion.draftId')} value={result.draft.draft_id} breakValue />
                <ReceiptRow label={t('draftPromotion.draftVersion')} value={String(result.draft.draft_version)} />
                <ReceiptRow label={t('draftPromotion.commandId')} value={result.promotion.command_id} breakValue />
                <ReceiptRow label={t('draftPromotion.trace')} value={result.promotion.trace_ref} breakValue />
                <ReceiptRow
                  label={t('draftPromotion.replayStatus')}
                  value={result.replayed ? t('draftPromotion.replayed') : t('draftPromotion.firstExecution')}
                />
              </dl>
            </div>

            <div
              className="mt-3 border px-3 py-3"
              style={{
                borderColor: 'color-mix(in srgb, var(--high) 40%, transparent)',
                background: 'color-mix(in srgb, var(--high) 6%, transparent)',
              }}
            >
              <div className="flex flex-wrap gap-2">
                <span className="bp-tol bp-tol-high">
                  {result.review_state === 'not_submitted' ? t('draftPromotion.notSubmitted') : result.review_state}
                </span>
                <span className="bp-tol bp-tol-high">
                  {result.publication_state === 'not_published' ? t('draftPromotion.notPublished') : result.publication_state}
                </span>
              </div>
              <p className="mt-2 font-mono text-[10.5px] leading-relaxed text-muted-foreground">
                {t('draftPromotion.truthNote')}
              </p>
              <p className="mt-1.5 font-mono text-[10px] leading-relaxed text-faint">
                {result.next_step === 'update_draft_or_request_review' ? t('draftPromotion.nextStep') : result.next_step}
              </p>
            </div>

            <div className="mt-5 flex justify-end">
              <button ref={receiptCloseRef} type="button" onClick={tryClose} className="bp-cmd">
                {t('draftPromotion.closeAndRefresh')}
              </button>
            </div>
          </div>
        ) : (
          <form
            className="mt-4"
            noValidate
            onSubmit={(event) => {
              event.preventDefault()
              submit()
            }}
          >
            <label htmlFor="create-draft-reason" className="bp-label">
              {t('draftPromotion.reason')}
            </label>
            <textarea
              id="create-draft-reason"
              ref={reasonRef}
              rows={4}
              value={reason}
              onChange={(event) => {
                setReason(event.target.value)
                if (event.target.value.trim()) setReasonMissing(false)
              }}
              disabled={pending}
              required
              maxLength={TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH}
              placeholder={t('draftPromotion.reasonPlaceholder')}
              aria-invalid={reasonMissing || undefined}
              aria-describedby={`create-draft-reason-limit${reasonMissing ? ' create-draft-reason-error' : ''}`}
              className="mt-1.5 w-full resize-y border border-border bg-transparent px-2.5 py-2 font-mono text-[12.5px] leading-relaxed outline-none transition-colors focus:border-[var(--primary)] disabled:opacity-50"
            />
            <div className="mt-1.5 flex items-start justify-between gap-3 font-mono text-[10px] leading-relaxed text-faint">
              <span id="create-draft-reason-limit">{t('draftPromotion.reasonLimit')}</span>
              <span aria-hidden="true">
                {reason.length}/{TICKET_DRAFT_PROMOTION_REASON_MAX_LENGTH}
              </span>
            </div>
            {reasonMissing && (
              <p id="create-draft-reason-error" role="alert" className="mt-1.5 font-mono text-[10.5px]" style={{ color: 'var(--urgent)' }}>
                {t('draftPromotion.reasonRequired')}
              </p>
            )}

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
                {t('draftPromotion.failed')}: {serverError}
                {staleConflict && (
                  <p className="mt-1.5 text-muted-foreground">{t('draftPromotion.conflictRefresh')}</p>
                )}
              </div>
            )}

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={tryClose}
                disabled={pending}
                className="bp-panel px-3 py-1.5 font-mono text-[11px] text-muted-foreground hover:bg-muted disabled:opacity-50"
              >
                {t('draftPromotion.cancel')}
              </button>
              <button type="submit" disabled={pending} className="bp-cmd disabled:cursor-not-allowed disabled:opacity-50">
                {pending ? t('draftPromotion.creating') : t('draftPromotion.create')}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  )
}

function ReceiptRow({ label, value, breakValue = false }: { label: string; value: string; breakValue?: boolean }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="shrink-0 text-faint">{label}</dt>
      <dd className={`${breakValue ? 'break-all' : ''} text-right`}>{value}</dd>
    </div>
  )
}
