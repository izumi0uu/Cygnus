import { useTranslation } from 'react-i18next'
import type { SourceFailureObservation } from '@/lib/api'

export function SourceFailureCard({ failure }: { failure: SourceFailureObservation }) {
  const { t } = useTranslation()
  return (
    <article className="bp-panel overflow-hidden">
      <div className="bp-dim flex items-center gap-2 px-4 py-3">
        <span className="h-2 w-2 rotate-45" style={{ background: 'var(--high)' }} />
        <span className="font-mono text-[11px] font-bold uppercase tracking-wide" style={{ color: 'var(--high)' }}>
          {t('observation.sourceFailure')}
        </span>
        <span className="bp-tol bp-tol-high ml-auto">{t('observation.statusError')}</span>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <div>
          <div className="font-mono text-[13px] font-semibold leading-tight">{failure.title}</div>
          <div className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">{failure.source_ref}</div>
        </div>
        <p className="font-mono text-[11px] leading-relaxed" style={{ color: 'var(--high)' }}>{failure.error_message}</p>
        <LinkedRefs label={t('observation.linkedWiki')} refs={failure.linked_wiki_refs} />
        <LinkedRefs label={t('observation.linkedObjects')} refs={failure.linked_object_refs} />
        <div className="bp-dim flex flex-wrap items-center gap-2 pt-3 font-mono text-[10px] text-faint">
          <span className="bp-tol bp-tol-flat">{t('observation.impactUnknown')}</span>
          {failure.observed_at && <span className="ml-auto">{t('observation.observedAt')} · {failure.observed_at}</span>}
        </div>
      </div>
    </article>
  )
}

function LinkedRefs({ label, refs }: { label: string; refs: string[] }) {
  const { t } = useTranslation()
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-faint">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {refs.length > 0
          ? refs.map((ref) => <span key={ref} className="bp-tol bp-tol-flat max-w-full whitespace-normal break-all">{ref}</span>)
          : <span className="font-mono text-[10px] text-faint">{t('observation.none')}</span>}
      </div>
    </div>
  )
}
