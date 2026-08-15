import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { X, Loader2 } from 'lucide-react'
import {
  applyPublishAction,
  fetchPublishPreview,
  type PublishApplyResult,
  type PublishPreviewSurface,
  type BlastRadiusImpact,
} from '@/lib/api'
import { useVocab } from '@/lib/vocab'
import { useFocusTrap } from '@/lib/useFocusTrap'

const EFFECT_CHIP: Record<string, string> = {
  new_exposure: 'chip-high',
  continuing_exposure: 'chip',
  stopped_exposure: 'chip-medium',
  conflict: 'chip-urgent',
}
const EFFECT_DOT: Record<string, string> = {
  new_exposure: 'var(--high)',
  continuing_exposure: 'var(--faint)',
  stopped_exposure: 'var(--medium)',
  conflict: 'var(--urgent)',
}

type PreviewSnapshot = {
  requestId: number
  objectRef: string
  actionKey: string | undefined
  data: PublishPreviewSurface
}

type PublishApplyOutcome =
  | {
      kind: 'success'
      requestId: number
      previewRequestId: number
      objectRef: string
      actionKey: string
      commandId: string
      result: PublishApplyResult
    }
  | {
      kind: 'error'
      requestId: number
      previewRequestId: number
      objectRef: string
      actionKey: string
      commandId: string
      error: string
    }

export default function PublishPreviewModal({
  objectRef,
  initialActionKey,
  onClose,
}: {
  objectRef: string
  initialActionKey?: string
  onClose: () => void
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const navigate = useNavigate()
  const ref = useRef<HTMLDivElement>(null)
  const [preview, setPreview] = useState<PreviewSnapshot | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionKey, setActionKey] = useState<string | undefined>(initialActionKey)
  const [applyOutcome, setApplyOutcome] = useState<PublishApplyOutcome | null>(null)
  const [applying, setApplying] = useState(false)
  const pendingRef = useRef(false)
  const onCloseRef = useRef(onClose)
  const previewRequestIdRef = useRef(0)
  const applyRequestIdRef = useRef(0)
  const activeApplyRequestIdRef = useRef<number | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      activeApplyRequestIdRef.current = null
    }
  }, [])

  const tryClose = useCallback(() => {
    if (!pendingRef.current) onCloseRef.current()
  }, [])
  useFocusTrap(ref, true, tryClose)

  // The parent drawer also owns a document-level focus trap. Capture Escape
  // before it can close a modal whose durable write is still in flight.
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
    const requestId = ++previewRequestIdRef.current
    let active = true
    queueMicrotask(() => {
      if (!active) return
      setLoading(true)
      setError(null)
      setPreview(null)
      setApplyOutcome(null)
      fetchPublishPreview(objectRef, actionKey)
        .then((data) => {
          if (!active) return
          if (actionKey && data.selected_action !== actionKey) {
            setError('The server returned a preview for a different publish action.')
            return
          }
          setPreview({ requestId, objectRef, actionKey, data })
        })
        .catch((nextError) => {
          if (active) setError(String(nextError))
        })
        .finally(() => {
          if (active) setLoading(false)
        })
    })
    return () => {
      active = false
    }
  }, [actionKey, objectRef])

  const previewMatchesCurrentAction =
    preview !== null && preview.objectRef === objectRef && preview.actionKey === actionKey
  const data = previewMatchesCurrentAction ? preview.data : null
  const selectedKey = actionKey ?? data?.selected_action ?? null
  const durableCommand =
    data?.durable_command && selectedKey && data.durable_command.action_key === selectedKey
      ? data.durable_command
      : null
  const outcomeMatchesCurrentPreview =
    applyOutcome !== null &&
    previewMatchesCurrentAction &&
    preview !== null &&
    applyOutcome.previewRequestId === preview.requestId &&
    applyOutcome.objectRef === objectRef &&
    applyOutcome.actionKey === selectedKey &&
    durableCommand?.action_key === applyOutcome.actionKey &&
    durableCommand.command_id === applyOutcome.commandId
  const applyResult =
    outcomeMatchesCurrentPreview && applyOutcome.kind === 'success' ? applyOutcome.result : null
  const applyError =
    outcomeMatchesCurrentPreview && applyOutcome.kind === 'error' ? applyOutcome.error : null

  const runApply = () => {
    if (pendingRef.current || !durableCommand || !preview) return
    const requestId = ++applyRequestIdRef.current
    const request = {
      requestId,
      previewRequestId: preview.requestId,
      objectRef,
      actionKey: durableCommand.action_key,
      commandId: durableCommand.command_id,
    }
    activeApplyRequestIdRef.current = requestId
    pendingRef.current = true
    setApplying(true)
    setApplyOutcome(null)
    applyPublishAction(objectRef, request.actionKey, durableCommand)
      .then((result) => {
        if (!mountedRef.current || activeApplyRequestIdRef.current !== requestId) return
        if (result.selected_action !== request.actionKey || result.command_id !== request.commandId) {
          setApplyOutcome({
            kind: 'error',
            ...request,
            error: 'The server returned a receipt for a different publish action.',
          })
          return
        }
        setApplyOutcome({ kind: 'success', ...request, result })
      })
      .catch((nextError) => {
        if (!mountedRef.current || activeApplyRequestIdRef.current !== requestId) return
        setApplyOutcome({ kind: 'error', ...request, error: String(nextError) })
      })
      .finally(() => {
        if (!mountedRef.current || activeApplyRequestIdRef.current !== requestId) return
        activeApplyRequestIdRef.current = null
        pendingRef.current = false
        setApplying(false)
      })
  }

  const selectPreset = (key: string) => {
    if (pendingRef.current || key === selectedKey) return
    setActionKey(key)
  }

  const gotoPropagation = () => {
    if (pendingRef.current) return
    onCloseRef.current()
    const params = new URLSearchParams()
    if (applyResult?.persisted && applyResult.publication_record_id) {
      params.set('publication_id', applyResult.publication_record_id)
    } else {
      params.set('object_ref', objectRef)
    }
    navigate(`/console/propagation?${params.toString()}`)
  }

  return createPortal(
    <div className="fixed inset-0 z-[120] flex items-start justify-center overflow-y-auto bg-foreground/30 pt-[8vh] pb-10" onMouseDown={tryClose}>
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t('publish.blastRadius')}
        tabIndex={-1}
        className="w-full max-w-[720px] overflow-hidden rounded-xl border border-border bg-card shadow-soft outline-none"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 border-b border-border px-5 py-3.5">
          <span className="chip chip-high">{t('publish.blastRadius')}</span>
          {data && (
            <span className="font-mono text-[11px] text-faint">{data.selected_preview?.object_id} · {v.objectType(data.selected_preview?.object_type ?? '')}</span>
          )}
          <button
            className="ml-auto flex h-8 w-8 items-center justify-center rounded-full border border-border text-muted-foreground hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={t('detail.close')}
            onClick={tryClose}
            disabled={applying}
          >
            <X size={15} />
          </button>
        </div>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" />{t('state.loading')}
          </div>
        )}
        {error && (
          <div className="px-5 py-10 text-center text-sm" style={{ color: 'var(--urgent)' }}>
            {error}
          </div>
        )}
        {data && !loading && !error && (
          <PublishBody
            data={data}
            selectedAction={selectedKey}
            canApply={!!durableCommand}
            applying={applying}
            applyResult={applyResult}
            applyError={applyError}
            onApply={runApply}
            onSelectPreset={selectPreset}
            onGotoPropagation={gotoPropagation}
          />
        )}
      </div>
    </div>,
    document.body,
  )
}

function PublishBody({
  data,
  selectedAction,
  canApply,
  applying,
  applyResult,
  applyError,
  onApply,
  onSelectPreset,
  onGotoPropagation,
}: {
  data: PublishPreviewSurface
  selectedAction: string | null
  canApply: boolean
  applying: boolean
  applyResult: PublishApplyResult | null
  applyError: string | null
  onApply: () => void
  onSelectPreset: (key: string) => void
  onGotoPropagation: () => void
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const sf = data.situation_frame
  const preview = data.selected_preview
  if (!preview) return <div className="px-5 py-10 text-center text-sm text-faint">{t('state.empty')}</div>

  return (
    <div className="thin-scroll max-h-[72vh] overflow-y-auto">
      {/* situation frame */}
      <div className="border-b border-border px-5 py-4">
        <h2 className="text-[15px] font-bold leading-tight">{data.headline}</h2>
        <p className="mt-1.5 text-[13px] leading-relaxed text-muted-foreground">{data.summary}</p>
        <div className="mt-3 flex flex-wrap gap-2.5">
          <PathCounter n={sf.new_paths} label={t('publish.newPaths')} color="var(--high)" />
          <PathCounter n={sf.blocked_paths} label={t('publish.blockedPaths')} color="var(--urgent)" />
          <PathCounter n={sf.stopped_paths} label={t('publish.stoppedPaths')} color="var(--medium)" />
        </div>
      </div>

      {/* action presets */}
      <div className="border-b border-border px-5 py-4">
        <div className="mb-2.5 font-mono text-[10px] uppercase tracking-widest text-faint">{t('publish.presets')}</div>
        <div className="flex flex-col gap-2">
          {data.action_presets.map((preset) => {
            const isActive = selectedAction === preset.command_key
            return (
              <button
                key={preset.command_key}
                type="button"
                onClick={() => onSelectPreset(preset.command_key)}
                disabled={applying}
                className="rounded-lg border px-3.5 py-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                style={{
                  borderColor: isActive ? 'var(--primary)' : 'var(--border)',
                  background: isActive ? 'var(--accent)' : 'transparent',
                }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[13px] font-semibold">{v.command(preset.command_key)}</span>
                  {preset.recommended && <span className="chip chip-high">{t('publish.recommended')}</span>}
                </div>
                <p className="mt-1 text-[12px] leading-relaxed text-muted-foreground">{preset.summary}</p>
                <p className="mt-0.5 font-mono text-[10px] leading-relaxed text-faint">{preset.consequence_hint}</p>
              </button>
            )
          })}
        </div>
      </div>

      {/* channel gate matrix */}
      {preview.channel_gate_matrix.length > 0 && (
        <div className="border-b border-border px-5 py-4">
          <div className="mb-2.5 font-mono text-[10px] uppercase tracking-widest text-faint">{t('publish.channelGate')}</div>
          <div className="overflow-hidden rounded-lg border border-border">
            <div className="grid grid-cols-[1fr_50px_50px_50px_50px] border-b border-border bg-muted px-3 py-2 font-mono text-[9px] uppercase tracking-wide text-faint">
              <span>{t('publish.channelGate')}</span>
              <span className="text-center" style={{ color: 'var(--high)' }}>{t('publish.new')}</span>
              <span className="text-center text-faint">{t('publish.continuing')}</span>
              <span className="text-center" style={{ color: 'var(--medium)' }}>{t('publish.stopped')}</span>
              <span className="text-center" style={{ color: 'var(--urgent)' }}>{t('publish.conflict')}</span>
            </div>
            {preview.channel_gate_matrix.map((gate) => (
              <div key={gate.channel} className="grid grid-cols-[1fr_50px_50px_50px_50px] border-b border-border px-3 py-2 last:border-b-0">
                <span className="text-[12px] font-medium">{v.surface(gate.channel)}</span>
                <GateCell n={gate.new_exposure} color="var(--high)" />
                <GateCell n={gate.continuing_exposure} color="var(--faint)" />
                <GateCell n={gate.stopped_exposure} color="var(--medium)" />
                <GateCell n={gate.conflicts} color="var(--urgent)" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* impact details */}
      <div className="border-b border-border px-5 py-4">
        <div className="mb-2.5 font-mono text-[10px] uppercase tracking-widest text-faint">{t('publish.impacts')}</div>
        <div className="flex flex-col gap-1.5">
          {preview.impacts.map((impact, i) => (
            <ImpactRow key={i} impact={impact} />
          ))}
        </div>
      </div>

      {/* action echo */}
      {data.action_echo && (
        <div className="border-b border-border px-5 py-4">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">{t('prop.actionEcho')}</div>
          <p className="text-[13px] font-medium">{data.action_echo.summary}</p>
          {data.action_echo.action_log.length > 0 && (
            <ul className="mt-2 space-y-1">
              {data.action_echo.action_log.map((log, i) => (
                <li key={i} className="font-mono text-[10.5px] leading-relaxed text-muted-foreground">· {log}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* context notes */}
      {data.context_notes.length > 0 && (
        <div className="border-b border-border px-5 py-4">
          <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">{t('publish.contextNotes')}</div>
          <ul className="space-y-1.5">
            {data.context_notes.map((note, i) => (
              <li key={i} className="text-[12px] leading-relaxed text-muted-foreground">{note}</li>
            ))}
          </ul>
        </div>
      )}

      {/* warnings */}
      {preview.warnings.length > 0 && (
        <div className="px-5 py-3.5">
          {preview.warnings.map((w, i) => (
            <div key={i} className="rounded-lg px-3 py-2 text-[12px]" style={{ color: 'var(--urgent)', background: 'color-mix(in srgb, var(--urgent) 8%, transparent)' }}>
              {w}
            </div>
          ))}
        </div>
      )}

      <div aria-live="polite" aria-atomic="true">
        {(applyResult || applyError) && (
          <div className="border-b border-border px-5 py-4">
            <div className="mb-2 font-mono text-[10px] uppercase tracking-widest text-faint">{t('publish.applyResult')}</div>
            {applyError && (
              <div className="rounded-lg px-3 py-2 text-[12px]" style={{ color: 'var(--urgent)', background: 'color-mix(in srgb, var(--urgent) 8%, transparent)' }}>
                {t('publish.applyError')}: {applyError}
              </div>
            )}
            {applyResult && (
              <div className="space-y-2">
                <div className="flex flex-wrap gap-2">
                  <PathCounter n={applyResult.opened_bindings.length} label={t('publish.openedPaths')} color="var(--high)" />
                  <PathCounter n={applyResult.removed_bindings.length} label={t('publish.removedPaths')} color="var(--medium)" />
                  <PathCounter n={applyResult.held_bindings.length} label={t('publish.heldPaths')} color="var(--urgent)" />
                </div>
                {applyResult.action_log.length > 0 && (
                  <ul className="space-y-1">
                    {applyResult.action_log.map((log, i) => (
                      <li key={i} className="font-mono text-[10.5px] leading-relaxed text-muted-foreground">· {log}</li>
                    ))}
                  </ul>
                )}
                {applyResult.persisted ? (
                  <p className="font-mono text-[10px] leading-relaxed" style={{ color: 'var(--ok)' }}>
                    {t('publish.persisted')}
                    {applyResult.command_id ? ` · ${applyResult.command_id}` : ''}
                    {applyResult.replayed ? ` · ${t('publish.replayed')}` : ''}
                  </p>
                ) : (
                  <p className="font-mono text-[10px] leading-relaxed text-faint">{t('publish.notPersisted')}</p>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* footer: apply (write path) + propagation link */}
      <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3.5">
        {!canApply && (
          <span className="mr-auto font-mono text-[10px] leading-relaxed text-faint">
            {t('publish.durableOnly')}
          </span>
        )}
        <button
          type="button"
          onClick={onApply}
          disabled={!canApply || applying}
          className="cmd inline-flex items-center gap-1.5 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {applying ? t('publish.applying') : t('publish.apply')}
        </button>
        <button
          type="button"
          onClick={onGotoPropagation}
          disabled={applying}
          className="cmd disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t('publish.viewPropagation')}
        </button>
      </div>
    </div>
  )
}

function PathCounter({ n, label, color }: { n: number; label: string; color: string }) {
  return (
    <div className="flex items-center gap-1.5 rounded-lg border border-border bg-muted px-2.5 py-1.5">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      <span className="font-mono text-[14px] font-bold" style={{ color }}>{n}</span>
      <span className="font-mono text-[10px] uppercase text-muted-foreground">{label}</span>
    </div>
  )
}

function GateCell({ n, color }: { n: number; color: string }) {
  return (
    <span className="text-center font-mono text-[12px] font-semibold" style={{ color: n > 0 ? color : 'var(--faint)' }}>
      {n > 0 ? n : '—'}
    </span>
  )
}

function ImpactRow({ impact }: { impact: BlastRadiusImpact }) {
  const v = useVocab()
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-border px-3 py-2">
      <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ background: EFFECT_DOT[impact.effect] ?? 'var(--faint)' }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[12.5px] font-medium truncate">{impact.audience_label}</span>
          <span className="chip" style={{ fontSize: '9px' }}>{v.surface(impact.channel)}</span>
          <span className={`chip ${EFFECT_CHIP[impact.effect] ?? 'chip'}`}>{v.blastEffect(impact.effect)}</span>
        </div>
        <p className="mt-1 font-mono text-[10px] leading-relaxed text-faint">{impact.reason}</p>
      </div>
    </div>
  )
}
