import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'
import { useVocab } from '@/lib/vocab'
import { useToast } from '@/lib/toast'

// A command button in preview state: echoes an honest toast instead of executing.
// The write path (real command execution) is not wired yet — see detail.commandNote.
export function CmdButton({ command, className }: { command: string; className?: string }) {
  const { t } = useTranslation()
  const v = useVocab()
  const toast = useToast()
  return (
    <button
      className={cn('cmd', className)}
      onClick={(e) => {
        e.stopPropagation()
        toast(t('cmd.preview', { action: v.command(command) }))
      }}
    >
      {v.command(command)} →
    </button>
  )
}
