import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useVocab } from '@/lib/vocab'
import { useToast } from '@/lib/toast'
import type { ReviewAssignmentAction, ReviewAssignmentCommandResult } from '@/lib/api'
import PublishPreviewModal from '@/components/PublishPreviewModal'
import AssignOwnerModal from '@/components/AssignOwnerModal'

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

export function CmdButton({
  command,
  className,
  objectRef,
  assignment,
}: {
  command: string
  className?: string
  objectRef?: string
  /** When present, routes assign_owner/escalate/release_owner to the durable endpoint. */
  assignment?: AssignmentCommandContext
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const toast = useToast()
  const [publishOpen, setPublishOpen] = useState(false)
  const [assignOpen, setAssignOpen] = useState(false)

  const isPublishCommand = !!PUBLISH_COMMANDS[command] && !!objectRef
  const assignmentAction = assignment ? ASSIGNMENT_ACTIONS[command] : undefined

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
          } else {
            toast(t('cmd.preview', { action: v.command(command) }))
          }
        }}
      >
        {v.command(command)} →
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
    </>
  )
}
