import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useVocab } from '@/lib/vocab'
import { useToast } from '@/lib/toast'
import PublishPreviewModal from '@/components/PublishPreviewModal'

const PUBLISH_COMMANDS = new Set([
  'publish',
  'republish',
  'restrict_publish',
  'hold_external',
  'split_variant',
  'republish_internal_only',
])

export function CmdButton({
  command,
  className,
  objectRef,
}: {
  command: string
  className?: string
  objectRef?: string
}) {
  const { t } = useTranslation()
  const v = useVocab()
  const toast = useToast()
  const [modalOpen, setModalOpen] = useState(false)

  const isPublishCommand = PUBLISH_COMMANDS.has(command) && !!objectRef

  return (
    <>
      <button
        className={cn('bp-cmd', className)}
        onClick={(e) => {
          e.stopPropagation()
          if (isPublishCommand) {
            setModalOpen(true)
          } else {
            toast(t('cmd.preview', { action: v.command(command) }))
          }
        }}
      >
        {v.command(command)} →
      </button>
      {isPublishCommand && modalOpen && (
        <PublishPreviewModal
          objectRef={objectRef!}
          initialActionKey={command}
          onClose={() => setModalOpen(false)}
        />
      )}
    </>
  )
}
