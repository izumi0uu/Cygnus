import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useVocab } from '@/lib/vocab'
import { useToast } from '@/lib/toast'
import type { ReviewAssignmentAction, ReviewAssignmentCommandResult } from '@/lib/api'
import PublishPreviewModal from '@/components/PublishPreviewModal'
import AssignOwnerModal from '@/components/AssignOwnerModal'
import CreateDraftModal from '@/components/CreateDraftModal'

const PUBLISH_COMMANDS: Record<string, true> = {
  publish: true,
  republish: true,
  restrict_publish: true,
  hold_external: true,
  split_variant: true,
  republish_internal_only: true,
}

// Durable owner commands — the only keys wired to the review-assignment write
// path (POST /api/review-assignments/{signal_ref}/commands), and only when the
// caller supplies the assignment context. Everywhere else these keys keep the
// toast-preview behavior, as do all non-assignment commands.
const ASSIGNMENT_ACTIONS: Record<string, ReviewAssignmentAction> = {
  assign_owner: 'assign',
  escalate: 'escalate',
  release_owner: 'release',
}

/** Durable assignment context for one review signal, supplied by the drawer. */
export interface AssignmentCommandContext {
  signalRef: string
  version: number
  owner: string | null
  state: string
  onExecuted: (result: ReviewAssignmentCommandResult) => void
  onRefresh?: () => void
}

/** Durable promotion context supplied only by a qualifying ReviewQueue drawer. */
export interface DraftPromotionCommandContext {
  signalRef: string
  objectRef: string
  assignmentVersion: number
  onRefresh?: () => void
}

export function CmdButton({
  command,
  className,
  objectRef,
  assignment,
  draftPromotion,
}: {
  command: string
  className?: string
  objectRef?: string
  /** When present, routes assign_owner/escalate/release_owner to the durable endpoint. */
  assignment?: AssignmentCommandContext
  /** When present, routes create_draft to the durable ticket-cluster promotion endpoint. */
  draftPromotion?: DraftPromotionCommandContext
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const toast = useToast()
  const [publishOpen, setPublishOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)
  const [createDraftOpen, setCreateDraftOpen] = useState(false)

  const isPublishCommand = !!PUBLISH_COMMANDS[command] && !!objectRef
  const assignmentAction = assignment ? ASSIGNMENT_ACTIONS[command] : undefined
  const isDraftPromotion =
    command === 'create_draft' &&
    !!draftPromotion?.signalRef.trim() &&
    !!draftPromotion.objectRef.trim() &&
    Number.isInteger(draftPromotion.assignmentVersion) &&
    draftPromotion.assignmentVersion >= 1
  const commandLabel = command === 'create_draft' ? t('commands.createDraft') : v.command(command)

  return (
    <>
      <button
        className={cn('bp-cmd', className)}
        onClick={(e) => {
          e.stopPropagation()
          if (isPublishCommand) {
            setPublishOpen(true)
          } else if (assignmentAction) {
            setAssignOpen(true)
          } else if (isDraftPromotion) {
            setCreateDraftOpen(true)
          } else {
            toast(t('cmd.preview', { action: commandLabel }))
          }
        }}
      >
        {commandLabel} →
      </button>
      {isPublishCommand && publishOpen && (
        <PublishPreviewModal
          objectRef={objectRef!}
          initialActionKey={command}
          onClose={() => setPublishOpen(false)}
        />
      )}
      {assignmentAction && assignment && assignOpen && (
        <AssignOwnerModal
          action={assignmentAction}
          signalRef={assignment.signalRef}
          expectedVersion={assignment.version}
          currentOwner={assignment.owner}
          currentState={assignment.state}
          onExecuted={assignment.onExecuted}
          onRefresh={assignment.onRefresh}
          onClose={() => setAssignOpen(false)}
        />
      )}
      {isDraftPromotion && draftPromotion && createDraftOpen && (
        <CreateDraftModal
          signalRef={draftPromotion.signalRef}
          objectRef={draftPromotion.objectRef}
          expectedAssignmentVersion={draftPromotion.assignmentVersion}
          onRefresh={draftPromotion.onRefresh}
          onClose={() => setCreateDraftOpen(false)}
        />
      )}
    </>
  )
}
