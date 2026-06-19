import { useTranslation } from 'react-i18next'
import { Plug } from 'lucide-react'

export default function Placeholder({ sectionKey }: { sectionKey: string }) {
  const { t } = useTranslation()
  return (
    <div className="flex h-full items-center justify-center">
      <div className="max-w-sm rounded-xl border border-dashed border-border bg-card px-8 py-10 text-center shadow-card">
        <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-muted text-faint">
          <Plug size={18} />
        </div>
        <div className="font-mono text-xs uppercase tracking-widest text-faint">{t(`nav.${sectionKey}`)}</div>
        <div className="mt-2 font-semibold text-muted-foreground">{t('state.awaitBackend')}</div>
        <p className="mt-2 text-[12.5px] leading-relaxed text-faint">{t('state.awaitBackendNote')}</p>
      </div>
    </div>
  )
}
