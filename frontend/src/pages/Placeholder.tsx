import { useTranslation } from 'react-i18next'

// A reserved drawing sheet — the audit surface has no backend endpoint yet, so
// it renders as an engineering-drawing "not yet drawn" sheet rather than a
// rounded SaaS empty card. Keeps it consistent with the rest of the drawing set.
export default function Placeholder({ sectionKey }: { sectionKey: string }) {
  const { t } = useTranslation()
  return (
    <div className="bp-grid relative flex h-full items-center justify-center overflow-hidden p-6">
      {/* corner registration marks */}
      <span className="pointer-events-none absolute left-3 top-3 h-3 w-3 border-l border-t border-primary opacity-40" />
      <span className="pointer-events-none absolute right-3 top-3 h-3 w-3 border-r border-t border-primary opacity-40" />
      <span className="pointer-events-none absolute bottom-3 left-3 h-3 w-3 border-b border-l border-primary opacity-40" />
      <span className="pointer-events-none absolute bottom-3 right-3 h-3 w-3 border-b border-r border-primary opacity-40" />

      <div className="w-full max-w-md">
        <div className="mb-3 flex items-baseline justify-between">
          <span className="bp-label">DWG-TBR · RESERVED SHEET</span>
          <span className="bp-label" style={{ opacity: 0.4 }}>{t(`nav.${sectionKey}`)}</span>
        </div>

        <div className="bp-panel p-8 text-center">
          {/* reserved-sheet stamp */}
          <div className="mb-4 flex justify-center">
            <span
              className="bp-stamp"
              style={{ color: 'var(--medium)', borderColor: 'color-mix(in srgb, var(--medium) 45%, transparent)' }}
            >
              {t('placeholder.reserved')}
            </span>
          </div>

          {/* empty drawing frame — a hollow rectangle with a diagonal "not drawn" line */}
          <div className="relative mx-auto mb-4 h-20 w-28">
            <div className="absolute inset-0 border border-dashed" style={{ borderColor: 'color-mix(in srgb, var(--primary) 30%, transparent)' }} />
            <div className="absolute inset-0" style={{ borderTop: '1px solid color-mix(in srgb, var(--faint) 35%, transparent)', transform: 'rotate(-12deg)', transformOrigin: 'center' }} />
          </div>

          <div className="font-mono text-[13px] font-semibold">{t('state.awaitBackend')}</div>
          <p className="mt-2 font-mono text-[11px] leading-relaxed text-faint">{t('state.awaitBackendNote')}</p>
        </div>

        <div className="mt-4 flex items-center justify-between">
          <span className="bp-label" style={{ opacity: 0.4 }}>SCALE 1:1 · DWG-TBR</span>
          <span className="bp-label" style={{ opacity: 0.4 }}>{t('placeholder.noData')}</span>
        </div>
      </div>
    </div>
  )
}
