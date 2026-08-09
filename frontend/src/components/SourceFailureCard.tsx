import { useTranslation } from 'react-i18next'
import type { SourceAudienceImpact, SourceFailureObservation, SourceImpactState, SourcePropagationImpact } from '@/lib/api'
import { useVocab } from '@/lib/vocab'

// impact_state → tol heat: mapped = impact truth resolved in scope; unmapped =
// provider completed but nothing governed is mapped — a coverage gap, never "healthy".
const IMPACT_BADGE: Record<SourceImpactState, { tol: string; key: string }> = {
  mapped: { tol: 'bp-tol-ok', key: 'observation.impactMapped' },
  unmapped: { tol: 'bp-tol-high', key: 'observation.impactUnmapped' },
}

// propagation status → heat, same convention as the propagation ledger lanes.
const PROP_DOT: Record<string, string> = {
  synced: 'var(--ok)',
  pending: 'var(--medium)',
  failed: 'var(--urgent)',
  manual_action_required: 'var(--high)',
}
const PROP_TOL: Record<string, string> = {
  synced: 'bp-tol-ok',
  pending: 'bp-tol-high',
  failed: 'bp-tol-urgent',
  manual_action_required: 'bp-tol-high',
}

// Raw source-failure fact: durable impact truth is displayed, but no governance
// command is ever offered here — commands belong to compiled governance risks.
export function SourceFailureCard({ failure }: { failure: SourceFailureObservation }) {
  const { t } = useTranslation()
  const badge = IMPACT_BADGE[failure.impact_state]
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
        {failure.impact_state === 'unmapped' && (
          <p className="font-mono text-[10px] leading-relaxed text-muted-foreground">{t('observation.impactUnmappedNote')}</p>
        )}
        <LinkedRefs label={t('observation.linkedWiki')} refs={failure.linked_wiki_refs} />
        <LinkedRefs label={t('observation.linkedObjects')} refs={failure.linked_object_refs} />
        {failure.audience_impacts.length > 0 && <AudienceImpacts impacts={failure.audience_impacts} />}
        {failure.propagation_impacts.length > 0 && <PropagationImpacts impacts={failure.propagation_impacts} />}
        <div className="bp-dim flex flex-wrap items-center gap-2 pt-3 font-mono text-[10px] text-faint">
          <span className={`bp-tol ${badge.tol}`}>{t(badge.key)}</span>
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

// Durable audience/channel effects — one row per persisted binding, with the
// binding provenance (object · variant · binding ref · durable version) below.
function AudienceImpacts({ impacts }: { impacts: SourceAudienceImpact[] }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-faint">{t('observation.audienceImpacts')}</div>
      <div className="space-y-1.5">
        {impacts.map((impact) => (
          <div key={impact.binding_ref} className="flex items-start gap-2 font-mono text-[10px]">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rotate-45" style={{ background: 'var(--medium)' }} />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="bp-tol bp-tol-flat max-w-full whitespace-normal break-all">{v.surface(impact.channel)}</span>
                <span className="break-words text-muted-foreground">{v.audienceSegment(impact.audience)}</span>
              </div>
              <div className="mt-0.5 break-all text-[9px] leading-relaxed text-faint">
                {impact.object_ref} · {impact.variant_ref} · {impact.binding_ref} · v{impact.version}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// Durable propagation evidence — surface + ledger status per record, channel
// refs as chips, and the propagation/publication provenance below.
function PropagationImpacts({ impacts }: { impacts: SourcePropagationImpact[] }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9px] uppercase tracking-[0.12em] text-faint">{t('observation.propagationImpacts')}</div>
      <div className="space-y-1.5">
        {impacts.map((impact) => (
          <div key={impact.propagation_ref} className="flex items-start gap-2 font-mono text-[10px]">
            <span className="mt-1 h-1.5 w-1.5 shrink-0 rotate-45" style={{ background: PROP_DOT[impact.status] ?? 'var(--faint)' }} />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="break-words text-muted-foreground">{v.surface(impact.surface_id)}</span>
                <span className={`bp-tol ${PROP_TOL[impact.status] ?? 'bp-tol-flat'}`}>{v.propStatus(impact.status)}</span>
                {impact.channel_refs.map((ch) => (
                  <span key={ch} className="bp-tol bp-tol-flat max-w-full whitespace-normal break-all">{v.surface(ch)}</span>
                ))}
              </div>
              <div className="mt-0.5 break-all text-[9px] leading-relaxed text-faint">
                {impact.object_ref} · {impact.publication_ref} · {impact.propagation_ref} · v{impact.version}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
