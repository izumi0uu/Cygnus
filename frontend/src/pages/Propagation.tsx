import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import {
  fetchPublishPropagation,
  type PublishPropagationSurface,
  type SurfacePropagationRecord,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'

const STATUS_DOT: Record<string, string> = {
  synced: 'var(--ok)',
  pending: 'var(--medium)',
  failed: 'var(--urgent)',
  manual_action_required: 'var(--high)',
}
const STATUS_CHIP: Record<string, string> = {
  synced: 'bp-tol-ok',
  pending: 'bp-tol-high',
  failed: 'bp-tol-urgent',
  manual_action_required: 'bp-tol-high',
}
const STATUS_LANE_STYLE: Record<string, string> = {
  synced: 'var(--ok)',
  pending: 'var(--medium)',
  failed: 'var(--urgent)',
  manual_action_required: 'var(--high)',
}

export default function Propagation() {
  const { t } = useTranslation()
  const v = useVocab()
  const [searchParams, setSearchParams] = useSearchParams()
  const [data, setData] = useState<PublishPropagationSurface | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const objectRef = searchParams.get('object_ref') || undefined
  const actionKey = searchParams.get('action_key') || undefined

  useEffect(() => {
    fetchPublishPropagation(objectRef, actionKey)
      .then(setData)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [objectRef, actionKey])

  const gotoObject = (ref: string) =>
    setSearchParams((p) => { const n = new URLSearchParams(p); n.set('object_ref', ref); return n }, { replace: true })

  if (loading) return <PageSkeleton />
  if (error)
    return (
      <div className="bp-panel p-4">
        <div className="font-mono text-sm" style={{ color: 'var(--urgent)' }}>⚠ {t('state.error')}</div>
        <Button
          variant="ghost"
          className="mt-3"
          onClick={() => {
            setLoading(true)
            setError(null)
            fetchPublishPropagation(objectRef, actionKey)
              .then(setData)
              .catch((e) => setError(String(e)))
              .finally(() => setLoading(false))
          }}
        >
          {t('state.retry')}
        </Button>
      </div>
    )
  if (!data) return null

  const ledger = data.propagation_ledger
  const summary = ledger.summary

  return (
    <>
      <p className="mb-3 font-mono text-[12px] leading-relaxed text-muted-foreground">{data.summary}</p>

      {/* stat row */}
      <div className="mb-4 flex flex-wrap gap-2.5">
        <Stat n={summary.synced} label={t('prop.statusSynced')} dot="var(--ok)" />
        <Stat n={summary.pending} label={t('prop.statusPending')} dot="var(--medium)" />
        <Stat n={summary.failed} label={t('prop.statusFailed')} dot="var(--urgent)" />
        <Stat n={summary.manual_action_required} label={t('prop.statusManual')} dot="var(--high)" />
      </div>

      {/* status lanes */}
      <div className="mb-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {data.status_lanes.map((lane) => (
          <div
            key={lane.status}
            className="bp-panel p-4"
            style={{ borderTopColor: STATUS_LANE_STYLE[lane.status], borderTopWidth: 2 }}
          >
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rotate-45" style={{ background: STATUS_LANE_STYLE[lane.status] }} />
              <span className="font-mono text-[13px] font-bold">{v.propStatus(lane.status)}</span>
              <span className="ml-auto font-mono text-[18px] font-bold" style={{ color: STATUS_LANE_STYLE[lane.status] }}>{lane.count}</span>
            </div>
            <p className="mt-1.5 font-mono text-[11.5px] leading-relaxed text-muted-foreground">{lane.note}</p>
            {lane.surface_ids.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {lane.surface_ids.map((s) => <span key={s} className="bp-tol bp-tol-flat">{v.surface(s)}</span>)}
              </div>
            )}
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
        {/* left: propagation ledger records */}
        <div className="bp-panel overflow-hidden">
          <div className="flex items-baseline px-4 pt-3.5">
            <div className="bp-label">{t('prop.ledger')}</div>
            <span className="ml-2 font-mono text-[11px] text-faint">{ledger.object_id}</span>
          </div>
          <div className="mt-1.5">
            {ledger.records.map((record) => (
              <RecordRow key={record.surface_id} record={record} />
            ))}
          </div>
        </div>

        {/* right: action echo + unresolved + continue commands */}
        <div className="flex flex-col gap-4">
          {data.action_echo && (
            <div className="bp-panel p-4">
              <div className="mb-2 bp-label">{t('prop.actionEcho')}</div>
              <div className="flex items-center gap-2">
                <span className="bp-tol bp-tol-high">{v.command(data.action_echo.selected_action)}</span>
              </div>
              <p className="mt-2 font-mono text-[12.5px] leading-relaxed text-muted-foreground">{data.action_echo.summary}</p>
              {data.action_echo.action_log.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {data.action_echo.action_log.map((log, i) => (
                    <li key={i} className="font-mono text-[10px] leading-relaxed text-faint">· {log}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {ledger.unresolved_surfaces.length > 0 && (
            <div className="bp-panel p-4">
              <div className="mb-2 bp-label">{t('prop.unresolved')}</div>
              <div className="flex flex-wrap gap-1.5">
                {ledger.unresolved_surfaces.map((s) => <span key={s} className="bp-tol bp-tol-high">{v.surface(s)}</span>)}
              </div>
            </div>
          )}

          {ledger.continue_commands.length > 0 && (
            <div className="bp-panel p-4">
              <div className="mb-2 bp-label">{t('prop.continueCmds')}</div>
              <div className="flex flex-wrap gap-2">
                {ledger.continue_commands.map((cmd) => <CmdButton key={cmd} command={cmd} />)}
              </div>
            </div>
          )}

          {/* context notes */}
          {data.context_notes.length > 0 && (
            <div className="bp-panel p-4">
              <div className="mb-1.5 bp-label">{t('publish.contextNotes')}</div>
              <ul className="space-y-1">
                {data.context_notes.map((note, i) => (
                  <li key={i} className="font-mono text-[12px] leading-relaxed text-muted-foreground">{note}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>

      {/* prev / next navigation */}
      <div className="bp-dim mt-5 flex items-center justify-between pt-4">
        {data.previous_object_ref ? (
          <button
            onClick={() => gotoObject(data.previous_object_ref!)}
            className="flex items-center gap-1.5 font-mono text-[12px] font-semibold text-primary hover:underline"
          >
            <ArrowLeft size={14} />{t('prop.prev')}
          </button>
        ) : <span />}
        <span className="font-mono text-[11px] text-faint">
          {data.selected_position + 1} / {data.total_items}
        </span>
        {data.next_object_ref ? (
          <button
            onClick={() => gotoObject(data.next_object_ref!)}
            className="flex items-center gap-1.5 font-mono text-[12px] font-semibold text-primary hover:underline"
          >
            {t('prop.next')}<ArrowRight size={14} />
          </button>
        ) : <span />}
      </div>
    </>
  )
}

function RecordRow({ record }: { record: SurfacePropagationRecord }) {
  const { t } = useTranslation()
  const v = useVocab()
  return (
    <div className="bp-anno flex flex-col gap-1.5 !items-stretch px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="h-2 w-2 shrink-0 rotate-45" style={{ background: STATUS_DOT[record.status] ?? 'var(--faint)' }} />
        <span className="font-mono text-[13px] font-semibold">{v.surface(record.surface_id)}</span>
        <span className={`bp-tol ${STATUS_CHIP[record.status] ?? 'bp-tol-flat'} ml-auto`}>{v.propStatus(record.status)}</span>
      </div>
      <p className="font-mono text-[12px] leading-relaxed text-muted-foreground">{record.reason}</p>
      {record.channel_refs.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {record.channel_refs.map((ch) => <span key={ch} className="bp-tol bp-tol-flat">{v.surface(ch)}</span>)}
        </div>
      )}
      {record.follow_up_commands.length > 0 && (
        <div className="bp-dim mt-2 flex flex-wrap items-center gap-2 pt-2">
          <span className="font-mono text-[10px] uppercase text-faint">{t('prop.followUp')}</span>
          {record.follow_up_commands.map((cmd) => <CmdButton key={cmd} command={cmd} className="text-[10px]" />)}
        </div>
      )}
    </div>
  )
}
