import { useTranslation } from 'react-i18next'

export default function Placeholder({ sectionKey }: { sectionKey: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex h-full items-center justify-center">
      <div className="text-center">
        <div className="font-mono text-xs uppercase tracking-widest text-faint">{t(`nav.${sectionKey}`)}</div>
        <div className="mt-2 text-muted-foreground">{t('queue.soon')}</div>
      </div>
    </div>
  )
}
