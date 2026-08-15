import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronUp, FileUp, Link2, RotateCw, Search } from 'lucide-react'
import {
  addUrlSource,
  attestSourceFreshness,
  approveSourceCompilationPlan,
  approveSourceExtraction,
  fetchSourceBlindnessSurface,
  fetchSourceCompilationPlan,
  fetchSourceDepartments,
  fetchSourceKnowledgeTypes,
  fetchSourceProgress,
  fetchSources,
  regenerateSourceCompilationPlan,
  rejectSourceCompilationPlan,
  retrySource,
  updateSourceLanguage,
  uploadSource,
  type SourceBlindnessContext,
  type SourceBlindnessSurface,
  type SourceCompilationPlan,
  type SourceDepartment,
  type SourceKnowledgeType,
  type SourceFreshnessState,
  type SourceLanguage,
  type SourceOperationsPage,
  type SourceRecord,
  type SourceScopeType,
} from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Stat } from '@/components/Stat'
import { useVocab } from '@/lib/vocab'
import { CmdButton } from '@/components/CmdButton'
import { PageSkeleton } from '@/components/Skeleton'
import { ObservationBanner } from '@/components/ObservationBanner'
import AdminDialog from '@/components/AdminDialog'
import { SourceFailureCard } from '@/components/SourceFailureCard'
import { RequestErrorState } from '@/components/RequestState'
import { useAuth } from '@/lib/auth'
import { ApiError } from '@/lib/authApi'

const MAX_SOURCE_UPLOAD_BYTES = 25 * 1024 * 1024
const MAX_PROGRESS_POLLS = 6
const ACTIVE_SOURCE_STATUSES = new Set(['pending', 'processing'])
const STATUS_STYLE: Record<string, string> = {
  pending: 'bp-tol-flat',
  processing: 'bp-tol-high',
  awaiting_approval: 'bp-tol-high',
  plan_ready: 'bp-tol-high',
  ready: 'bp-tol-ok',
  error: 'bp-tol-urgent',
  deleting: 'bp-tol-flat',
}
const FIELD_CLASS = 'h-10 w-full rounded-lg border border-input bg-background px-3 font-mono text-sm outline-none placeholder:text-faint focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60'
const DATE_FORMAT = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })

type CommandReceipt = {
  label: string
  detail: string
  jobId?: string | null
}

export default function SourcesEvidence() {
  const { t } = useTranslation()
  const { user, canAccess } = useAuth()
  const [inventory, setInventory] = useState<SourceOperationsPage | null>(null)
  const [inventoryLoading, setInventoryLoading] = useState(true)
  const [inventoryError, setInventoryError] = useState<unknown>(null)
  const [inventoryRefreshError, setInventoryRefreshError] = useState<unknown>(null)
  const [inventoryRefreshing, setInventoryRefreshing] = useState(false)
  const [lastObservedAt, setLastObservedAt] = useState<Date | null>(null)
  const [pollStale, setPollStale] = useState(false)
  const [polling, setPolling] = useState(false)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [page, setPage] = useState(1)
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null)
  const [riskData, setRiskData] = useState<SourceBlindnessSurface | null>(null)
  const [riskLoading, setRiskLoading] = useState(true)
  const [riskError, setRiskError] = useState<unknown>(null)
  const [knowledgeTypes, setKnowledgeTypes] = useState<SourceKnowledgeType[]>([])
  const [departments, setDepartments] = useState<SourceDepartment[]>(() =>
    (user?.department_ids ?? []).map((id, index) => ({
      id,
      name: user?.department_names[index] ?? id,
      description: null,
      employee_count: 0,
    })),
  )
  const [metadataError, setMetadataError] = useState<unknown>(null)
  const inventoryRequestKey = useRef(0)
  const riskRequestKey = useRef(0)
  const pollKey = useRef(0)
  const pollAttempts = useRef(0)
  const canCreate = canAccess('doc', 'create')
  const canEdit = canAccess('doc', 'edit')

  const loadInventory = useCallback((background = false) => {
    const key = ++inventoryRequestKey.current
    if (background) {
      setInventoryRefreshing(true)
      setInventoryRefreshError(null)
    } else {
      setInventoryLoading(true)
      setInventoryError(null)
      setPollStale(false)
      pollAttempts.current = 0
    }
    fetchSources({ search, status: statusFilter, page, pageSize: 20 })
      .then((next) => {
        if (key !== inventoryRequestKey.current) return
        setInventory(next)
        setLastObservedAt(new Date())
      })
      .catch((error: unknown) => {
        if (key !== inventoryRequestKey.current) return
        if (background) setInventoryRefreshError(error)
        else setInventoryError(error)
      })
      .finally(() => {
        if (key !== inventoryRequestKey.current) return
        if (background) setInventoryRefreshing(false)
        else setInventoryLoading(false)
      })
  }, [page, search, statusFilter])

  const loadRisk = useCallback(() => {
    const key = ++riskRequestKey.current
    setRiskLoading(true)
    setRiskError(null)
    fetchSourceBlindnessSurface()
      .then((next) => {
        if (key === riskRequestKey.current) setRiskData(next)
      })
      .catch((error: unknown) => {
        if (key === riskRequestKey.current) setRiskError(error)
      })
      .finally(() => {
        if (key === riskRequestKey.current) setRiskLoading(false)
      })
  }, [])

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) loadInventory() })
    return () => {
      active = false
      inventoryRequestKey.current += 1
    }
  }, [loadInventory])

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) loadRisk() })
    return () => {
      active = false
      riskRequestKey.current += 1
    }
  }, [loadRisk])

  useEffect(() => {
    let current = true
    const metadataRequests: Promise<unknown>[] = [
      fetchSourceKnowledgeTypes().then((items) => {
        if (current) setKnowledgeTypes(items)
      }),
    ]
    if (user?.role === 'admin') {
      metadataRequests.push(fetchSourceDepartments().then((items) => {
        if (current) setDepartments(items)
      }))
    }
    Promise.all(metadataRequests)
      .then(() => {
        if (current) setMetadataError(null)
      })
      .catch((error: unknown) => {
        if (current) setMetadataError(error)
      })
    return () => { current = false }
  }, [user?.role])

  // Poll only currently active source IDs, with exponential backoff and a hard
  // stop. Waiting-for-human and terminal rows never create background traffic.
  useEffect(() => {
    const activeIds = inventory?.items
      .filter((source) => ACTIVE_SOURCE_STATUSES.has(source.status))
      .map((source) => source.id) ?? []
    if (activeIds.length === 0) {
      pollAttempts.current = 0
      return
    }
    if (pollAttempts.current >= MAX_PROGRESS_POLLS) {
      queueMicrotask(() => {
        setPollStale(true)
        setPolling(false)
      })
      return
    }

    const delay = Math.min(30_000, 4_000 * (2 ** pollAttempts.current))
    const key = ++pollKey.current
    const timer = window.setTimeout(() => {
      setPolling(true)
      pollAttempts.current += 1
      Promise.all(activeIds.map((sourceId) => fetchSourceProgress(sourceId)))
        .then((progressRows) => {
          if (key !== pollKey.current) return
          const progressById = new Map(progressRows.map((progress) => [progress.id, progress]))
          setInventory((currentInventory) => currentInventory ? {
            ...currentInventory,
            items: currentInventory.items.map((source) => {
              const progress = progressById.get(source.id)
              return progress ? {
                ...source,
                status: progress.status,
                progress: progress.progress,
                progress_message: progress.progress_message,
                page_count: progress.page_count,
                wiki_page_count: progress.wiki_page_count,
              } : source
            }),
          } : currentInventory)
          setLastObservedAt(new Date())
          setPollStale(false)
          if (progressRows.some((progress) => !ACTIVE_SOURCE_STATUSES.has(progress.status))) loadInventory(true)
        })
        .catch((error: unknown) => {
          if (key !== pollKey.current) return
          setInventoryRefreshError(error)
          setPollStale(true)
        })
        .finally(() => {
          if (key === pollKey.current) setPolling(false)
        })
    }, delay)
    return () => {
      window.clearTimeout(timer)
      pollKey.current += 1
    }
  }, [inventory, loadInventory])

  const handleSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextSearch = searchInput.trim()
    setPage(1)
    if (nextSearch === search && page === 1) loadInventory()
    else setSearch(nextSearch)
  }

  const selectedSource = inventory?.items.find((source) => source.id === selectedSourceId) ?? null
  const activeCount = inventory?.items.filter((source) => ACTIVE_SOURCE_STATUSES.has(source.status)).length ?? 0

  return (
    <div className="space-y-6">
      <header className="bp-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="bp-label">{t('sources.eyebrow')}</div>
            <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('sources.title')}</h1>
            <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.summary')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {polling || inventoryRefreshing ? (
              <span role="status" className="bp-tol bp-tol-flat inline-flex items-center gap-1.5">
                <RotateCw aria-hidden="true" size={12} className="animate-spin" /> {t('sources.refreshing')}
              </span>
            ) : null}
            {pollStale ? <span className="bp-tol bp-tol-urgent">{t('sources.stale')}</span> : null}
          </div>
        </div>
      </header>

      <section aria-labelledby="source-operations-heading" className="space-y-4">
        <div>
          <h2 id="source-operations-heading" className="font-mono text-lg font-bold">{t('sources.operations')}</h2>
          <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.operationsNote')}</p>
        </div>

        {canCreate ? (
          <SourceCreateForms
            knowledgeTypes={knowledgeTypes}
            departments={departments}
            metadataError={metadataError}
            onCreated={() => loadInventory()}
          />
        ) : (
          <section className="bp-panel p-4" aria-labelledby="sources-create-permission-heading">
            <h3 id="sources-create-permission-heading" className="font-mono text-sm font-bold">{t('sources.createPermissionTitle')}</h3>
            <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.createPermissionNote')}</p>
          </section>
        )}

        {inventoryRefreshError ? <RequestErrorState error={inventoryRefreshError} onRetry={() => loadInventory(true)} compact stale /> : null}
        {pollStale && !inventoryRefreshError ? (
          <section aria-live="polite" className="bp-panel p-4" style={{ borderColor: 'var(--high)' }}>
            <h3 className="font-mono text-sm font-bold">{t('sources.pollStoppedTitle')}</h3>
            <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.pollStoppedNote')}</p>
            <Button type="button" variant="ghost" className="mt-3" onClick={() => loadInventory()}>{t('state.retry')}</Button>
          </section>
        ) : null}

        <form onSubmit={handleSearch} className="bp-panel p-4">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_12rem_auto] md:items-end">
            <label className="block">
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.searchLabel')}</span>
              <input
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                className={FIELD_CLASS}
                placeholder={t('sources.searchPlaceholder')}
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.statusFilter')}</span>
              <select
                value={statusFilter}
                onChange={(event) => { setPage(1); setStatusFilter(event.target.value) }}
                className={FIELD_CLASS}
              >
                <option value="">{t('sources.statusAll')}</option>
                {['pending', 'processing', 'awaiting_approval', 'plan_ready', 'ready', 'error', 'deleting'].map((status) => (
                  <option key={status} value={status}>{t(`sources.status.${status}`)}</option>
                ))}
              </select>
            </label>
            <Button type="submit"><Search aria-hidden="true" size={14} /> {t('sources.search')}</Button>
          </div>
        </form>

        {inventoryLoading ? <PageSkeleton /> : null}
        {!inventoryLoading && inventoryError ? <RequestErrorState error={inventoryError} onRetry={() => loadInventory()} /> : null}
        {!inventoryLoading && inventory ? (
          <>
            <div className="flex flex-wrap gap-2.5">
              <Stat n={inventory.total} label={t('sources.total')} />
              <Stat n={activeCount} label={t('sources.active')} dot="var(--medium)" />
              <Stat n={inventory.items.filter((source) => source.status === 'error').length} label={t('sources.errors')} dot="var(--urgent)" />
            </div>
            <div className="bp-panel overflow-hidden">
              <div className="hidden bp-dim px-4 py-2.5 font-mono text-xs uppercase tracking-wide text-faint xl:grid xl:grid-cols-[minmax(0,1.5fr)_8rem_minmax(0,1fr)_9rem_10rem] xl:gap-4">
                <span>{t('sources.source')}</span>
                <span>{t('sources.statusLabel')}</span>
                <span>{t('sources.progress')}</span>
                <span>{t('sources.scope')}</span>
                <span>{t('sources.actions')}</span>
              </div>
              {inventory.items.map((source) => (
                <SourceInventoryRow
                  key={source.id}
                  source={source}
                  canEdit={canEdit}
                  selected={source.id === selectedSourceId}
                  onSelect={() => setSelectedSourceId((current) => current === source.id ? null : source.id)}
                  onChanged={() => loadInventory(true)}
                />
              ))}
              {inventory.items.length === 0 ? (
                <div className="px-4 py-10 text-center">
                  <h3 className="font-mono text-sm font-bold">{t('sources.emptyTitle')}</h3>
                  <p className="mx-auto mt-2 max-w-xl font-mono text-xs leading-relaxed text-muted-foreground">
                    {search || statusFilter ? t('sources.emptyFiltered') : t('sources.emptyUnfiltered')}
                  </p>
                </div>
              ) : null}
            </div>
            <nav aria-label={t('sources.pagination')} className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="ghost" size="sm" disabled={inventory.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>{t('sources.previous')}</Button>
              <span className="font-mono text-xs text-faint sm:mx-auto">{t('sources.page', { page: inventory.page, total: inventory.total_pages })}</span>
              <Button type="button" variant="ghost" size="sm" disabled={inventory.page >= inventory.total_pages} onClick={() => setPage((current) => current + 1)}>{t('sources.next')}</Button>
            </nav>
            <p className="font-mono text-xs text-faint">
              {lastObservedAt ? t('sources.observedAt', { time: DATE_FORMAT.format(lastObservedAt) }) : t('sources.notObserved')}
            </p>
          </>
        ) : null}

        {selectedSource ? (
          <div className="space-y-4">
            <SourceFreshnessPanel
              key={`freshness:${selectedSource.id}`}
              source={selectedSource}
              canEdit={canEdit}
              onChanged={() => loadInventory(true)}
            />
            <SourceLanguagePanel
              key={`language:${selectedSource.id}`}
              source={selectedSource}
              canEdit={canEdit}
              onChanged={() => loadInventory(true)}
            />
            <SourcePlanPanel
              key={`plan:${selectedSource.id}`}
              source={selectedSource}
              canEdit={canEdit}
              onChanged={() => loadInventory(true)}
            />
          </div>
        ) : null}
      </section>

      <SourceRiskObservations data={riskData} loading={riskLoading} error={riskError} onRetry={loadRisk} />
    </div>
  )
}

function SourceCreateForms({
  knowledgeTypes,
  departments,
  metadataError,
  onCreated,
}: {
  knowledgeTypes: SourceKnowledgeType[]
  departments: SourceDepartment[]
  metadataError: unknown
  onCreated: () => void
}) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [fileTitle, setFileTitle] = useState('')
  const [fileKnowledgeType, setFileKnowledgeType] = useState('')
  const [fileDepartments, setFileDepartments] = useState<string[]>([])
  const [fileLanguage, setFileLanguage] = useState<SourceLanguage | ''>('')
  const [urlOpen, setUrlOpen] = useState(false)
  const [scopeType, setScopeType] = useState<SourceScopeType>('global')
  const [scopeId, setScopeId] = useState('')
  const [fileVerbatim, setFileVerbatim] = useState(false)
  const [url, setUrl] = useState('')
  const [urlTitle, setUrlTitle] = useState('')
  const [urlKnowledgeType, setUrlKnowledgeType] = useState('')
  const [urlDepartments, setUrlDepartments] = useState<string[]>([])
  const [urlScopeType, setUrlScopeType] = useState<SourceScopeType>('global')
  const [urlLanguage, setUrlLanguage] = useState<SourceLanguage | ''>('')
  const [urlScopeId, setUrlScopeId] = useState('')
  const [urlVerbatim, setUrlVerbatim] = useState(false)
  const [pending, setPending] = useState<'file' | 'url' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null)

  const toggleDepartment = (current: string[], id: string) => current.includes(id)
    ? current.filter((value) => value !== id)
    : [...current, id]

  const submitFile = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!file) return
    if (file.size > MAX_SOURCE_UPLOAD_BYTES) {
      setError(new Error(t('sources.fileTooLarge')))
      return
    }
    if (!fileLanguage) {
      setError(new Error(t('sources.languageRequired')))
      return
    }
    if (scopeType === 'department' && !scopeId) {
      setError(new Error(t('sources.scopeRequired')))
      return
    }
    setPending('file')
    setError(null)
    setReceipt(null)
    uploadSource({
      file,
      title: fileTitle,
      knowledgeTypeId: fileKnowledgeType || undefined,
      departmentIds: fileDepartments,
      language: fileLanguage,
      scopeType,
      scopeId: scopeType === 'department' ? scopeId : undefined,
      preserveVerbatim: fileVerbatim,
    })
      .then((source) => {
        setReceipt({ label: t('sources.createCommitted'), detail: t('sources.createReceipt', { id: source.id, status: source.status }), jobId: source.job_id })
        setFile(null)
        onCreated()
      })
      .catch(setError)
      .finally(() => setPending(null))
  }

  const submitUrl = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!urlLanguage) {
      setError(new Error(t('sources.languageRequired')))
      return
    }
    if (urlScopeType === 'department' && !urlScopeId) {
      setError(new Error(t('sources.scopeRequired')))
      return
    }
    setPending('url')
    setError(null)
    setReceipt(null)
    addUrlSource({
      url,
      language: urlLanguage,
      title: urlTitle,
      knowledgeTypeId: urlKnowledgeType || undefined,
      departmentIds: urlDepartments,
      scopeType: urlScopeType,
      scopeId: urlScopeType === 'department' ? urlScopeId : undefined,
      preserveVerbatim: urlVerbatim,
    })
      .then((source) => {
        setReceipt({ label: t('sources.createCommitted'), detail: t('sources.createReceipt', { id: source.id, status: source.status }), jobId: source.job_id })
        setUrl('')
        setUrlOpen(false)
        onCreated()
      })
      .catch(setError)
      .finally(() => setPending(null))
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <form onSubmit={submitFile} className="bp-panel p-4" aria-labelledby="source-file-heading">
        <div className="flex items-center gap-2">
          <FileUp aria-hidden="true" size={16} className="text-primary" />
          <h3 id="source-file-heading" className="font-mono text-sm font-bold">{t('sources.uploadFile')}</h3>
          <span className="ml-auto bp-tol bp-tol-flat">{t('sources.fileType')}</span>
        </div>
        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.file')}</span>
            <input
              type="file"
              required
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              className="block w-full rounded-lg border border-input bg-background p-2 font-mono text-xs file:mr-3 file:rounded-full file:border-0 file:bg-secondary file:px-3 file:py-1.5 file:font-semibold file:text-secondary-foreground focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
          {file ? <p className="font-mono text-xs text-faint">{file.name} · {Math.ceil(file.size / 1024)} KB</p> : null}
          <TextField label={t('sources.optionalTitle')} value={fileTitle} onChange={setFileTitle} />
          <label className="block">
            <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.language')}</span>
            <select required value={fileLanguage} onChange={(event) => setFileLanguage(event.target.value as SourceLanguage)} className={FIELD_CLASS}>
              <option value="">{t('sources.selectLanguage')}</option>
              <option value="en">{t('sources.languageEn')}</option>
              <option value="zh">{t('sources.languageZh')}</option>
            </select>
          </label>
          <MetadataFields
            knowledgeTypes={knowledgeTypes}
            departments={departments}
            knowledgeType={fileKnowledgeType}
            onKnowledgeType={setFileKnowledgeType}
            selectedDepartments={fileDepartments}
            onToggleDepartment={(id) => setFileDepartments((current) => toggleDepartment(current, id))}
          />
          <div className="grid gap-3 sm:grid-cols-2">
            <label>
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.scope')}</span>
              <select value={scopeType} onChange={(event) => setScopeType(event.target.value as SourceScopeType)} className={FIELD_CLASS}>
                <option value="global">{t('sources.scopeGlobal')}</option>
                <option value="department">{t('sources.scopeDepartment')}</option>
              </select>
            </label>
            {scopeType === 'department' ? (
              <label>
                <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.scopeDepartment')}</span>
                <select required value={scopeId} onChange={(event) => setScopeId(event.target.value)} className={FIELD_CLASS}>
                  <option value="">{t('sources.selectDepartment')}</option>
                  {departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
                </select>
              </label>
            ) : null}
          </div>
          <CheckField checked={fileVerbatim} onChange={setFileVerbatim} label={t('sources.preserveVerbatim')} />
          <p className="font-mono text-xs text-faint">{t('sources.fileLimit')}</p>
          <Button type="submit" className="min-h-11" disabled={!file || !fileLanguage || pending !== null}>
            {pending === 'file' ? <RotateCw aria-hidden="true" size={14} className="animate-spin" /> : <FileUp aria-hidden="true" size={14} />}
            {pending === 'file' ? t('sources.submitting') : t('sources.upload')}
          </Button>
        </div>
      </form>
      <section className="bp-panel p-4" aria-labelledby="source-url-trigger-heading">
        <div className="flex items-center gap-2">
          <Link2 aria-hidden="true" size={16} className="text-primary" />
          <h3 id="source-url-trigger-heading" className="font-mono text-sm font-bold">{t('sources.addUrl')}</h3>
          <span className="ml-auto bp-tol bp-tol-flat">{t('sources.urlType')}</span>
        </div>
        <p className="mt-3 font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.urlDialogDescription')}</p>
        <Button type="button" className="mt-4 min-h-11" onClick={() => { setError(null); setUrlOpen(true) }}>
          <Link2 aria-hidden="true" size={14} /> {t('sources.openUrlDialog')}
        </Button>
      </section>

      {urlOpen ? (
        <AdminDialog
          titleId="source-url-dialog-title"
          descriptionId="source-url-dialog-description"
          title={t('sources.addUrl')}
          description={t('sources.urlDialogDescription')}
          pending={pending === 'url'}
          onClose={() => { setUrlOpen(false); setError(null) }}
        >
          <form onSubmit={submitUrl} className="mt-5 space-y-3">
            <label className="block">
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.url')}</span>
              <input data-autofocus type="url" inputMode="url" autoComplete="url" required value={url} onChange={(event) => setUrl(event.target.value)} className={FIELD_CLASS} placeholder="https://" />
            </label>
            <TextField label={t('sources.optionalTitle')} value={urlTitle} onChange={setUrlTitle} />
            <MetadataFields
              knowledgeTypes={knowledgeTypes}
              departments={departments}
              knowledgeType={urlKnowledgeType}
              onKnowledgeType={setUrlKnowledgeType}
              selectedDepartments={urlDepartments}
              onToggleDepartment={(id) => setUrlDepartments((current) => toggleDepartment(current, id))}
            />
            <label className="block">
              <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.language')}</span>
              <select required value={urlLanguage} onChange={(event) => setUrlLanguage(event.target.value as SourceLanguage)} className={FIELD_CLASS}>
                <option value="">{t('sources.selectLanguage')}</option>
                <option value="en">{t('sources.languageEn')}</option>
                <option value="zh">{t('sources.languageZh')}</option>
              </select>
            </label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label>
                <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.scope')}</span>
                <select value={urlScopeType} onChange={(event) => setUrlScopeType(event.target.value as SourceScopeType)} className={FIELD_CLASS}>
                  <option value="global">{t('sources.scopeGlobal')}</option>
                  <option value="department">{t('sources.scopeDepartment')}</option>
                </select>
              </label>
              {urlScopeType === 'department' ? (
                <label>
                  <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.scopeDepartment')}</span>
                  <select required value={urlScopeId} onChange={(event) => setUrlScopeId(event.target.value)} className={FIELD_CLASS}>
                    <option value="">{t('sources.selectDepartment')}</option>
                    {departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}
                  </select>
                </label>
              ) : null}
            </div>
            <CheckField checked={urlVerbatim} onChange={setUrlVerbatim} label={t('sources.preserveVerbatim')} />
            <p className="font-mono text-xs text-faint">{t('sources.urlBoundary')}</p>
            {error ? <RequestErrorState error={error} compact /> : null}
            <div className="flex flex-wrap justify-end gap-2 bp-dim pt-4">
              <Button type="button" variant="ghost" className="min-h-11" disabled={pending === 'url'} onClick={() => { setUrlOpen(false); setError(null) }}>{t('sources.cancel')}</Button>
              <Button type="submit" className="min-h-11" disabled={!url.trim() || !urlLanguage || pending !== null}>
                {pending === 'url' ? <RotateCw aria-hidden="true" size={14} className="animate-spin" /> : <Link2 aria-hidden="true" size={14} />}
                {pending === 'url' ? t('sources.submitting') : t('sources.add')}
              </Button>
            </div>
          </form>
        </AdminDialog>
      ) : null}

      {metadataError ? <div className="lg:col-span-2"><RequestErrorState error={metadataError} compact stale /></div> : null}
      {error ? <div className="lg:col-span-2"><RequestErrorState error={error} compact /></div> : null}
      {receipt ? <Receipt receipt={receipt} className="lg:col-span-2" /> : null}
    </div>
  )
}

function MetadataFields({
  knowledgeTypes,
  departments,
  knowledgeType,
  onKnowledgeType,
  selectedDepartments,
  onToggleDepartment,
}: {
  knowledgeTypes: SourceKnowledgeType[]
  departments: SourceDepartment[]
  knowledgeType: string
  onKnowledgeType: (value: string) => void
  selectedDepartments: string[]
  onToggleDepartment: (id: string) => void
}) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label>
        <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.knowledgeType')}</span>
        <select value={knowledgeType} onChange={(event) => onKnowledgeType(event.target.value)} className={FIELD_CLASS}>
          <option value="">{t('sources.knowledgeTypeNone')}</option>
          {knowledgeTypes.map((type) => <option key={type.id} value={type.id}>{type.name}</option>)}
        </select>
      </label>
      <fieldset>
        <legend className="mb-1.5 font-mono text-xs text-muted-foreground">{t('sources.departments')}</legend>
        <div className="max-h-28 space-y-1 overflow-y-auto rounded-lg border border-input bg-background p-2">
          {departments.map((department) => (
            <label key={department.id} className="flex min-h-8 items-center gap-2 font-mono text-xs">
              <input type="checkbox" checked={selectedDepartments.includes(department.id)} onChange={() => onToggleDepartment(department.id)} className="h-4 w-4 accent-primary" />
              <span>{department.name}</span>
            </label>
          ))}
          {departments.length === 0 ? <span className="font-mono text-xs text-faint">{t('sources.noDepartments')}</span> : null}
        </div>
      </fieldset>
    </div>
  )
}

function SourceInventoryRow({
  source,
  canEdit,
  selected,
  onSelect,
  onChanged,
}: {
  source: SourceRecord
  canEdit: boolean
  selected: boolean
  onSelect: () => void
  onChanged: () => void
}) {
  const { t } = useTranslation()
  const [pending, setPending] = useState<'retry' | 'extraction' | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null)
  const retryAllowed = source.status === 'error' || source.status === 'plan_ready'
  const extractionAllowed = source.status === 'awaiting_approval'

  const runRetry = () => {
    setPending('retry')
    setError(null)
    setReceipt(null)
    retrySource(source.id)
      .then((next) => {
        setReceipt({ label: t('sources.retryCommitted'), detail: t('sources.retryReceipt', { status: next.status }), jobId: next.job_id })
        onChanged()
      })
      .catch(setError)
      .finally(() => setPending(null))
  }

  const runExtractionApproval = () => {
    setPending('extraction')
    setError(null)
    setReceipt(null)
    approveSourceExtraction(source.id)
      .then((next) => {
        setReceipt({ label: t('sources.extractionCommitted'), detail: t('sources.extractionReceipt', { status: next.status }), jobId: next.job_id })
        onChanged()
      })
      .catch(setError)
      .finally(() => setPending(null))
  }

  return (
    <article className="bp-anno px-4 py-4">
      <div className="grid gap-3 xl:grid-cols-[minmax(0,1.5fr)_8rem_minmax(0,1fr)_9rem_10rem] xl:items-center xl:gap-4">
        <div className="min-w-0">
          <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('sources.source')}</span>
          <button type="button" onClick={onSelect} aria-expanded={selected} className="flex w-full items-start gap-2 text-left font-mono text-sm font-bold underline-offset-4 hover:text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span className="min-w-0 flex-1 break-words">{source.title ?? source.file_name ?? source.url ?? source.id}</span>
            {selected ? <ChevronUp aria-hidden="true" size={14} /> : <ChevronDown aria-hidden="true" size={14} />}
          </button>
          <p className="mt-1 break-all font-mono text-xs text-faint">{source.id} · {source.source_type ?? '—'} · {t('sources.languageTag', { language: source.language })}</p>
          {source.error_message ? <p className="mt-2 font-mono text-xs leading-relaxed" style={{ color: 'var(--urgent)' }}>{source.error_message}</p> : null}
        </div>
        <div>
          <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('sources.statusLabel')}</span>
          <span className={`bp-tol ${STATUS_STYLE[source.status] ?? 'bp-tol-flat'}`}>{t(`sources.status.${source.status}`)}</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <span className={`bp-tol ${source.freshness_active && !source.freshness_expired ? 'bp-tol-ok' : source.freshness_state === 'stale' || source.freshness_expired ? 'bp-tol-urgent' : 'bp-tol-high'}`}>
              {source.freshness_expired ? t('sources.freshnessExpired') : t(`sources.freshness.${source.freshness_state}`)}
            </span>
            <span className={`bp-tol ${source.freshness_active && !source.freshness_expired ? 'bp-tol-ok' : 'bp-tol-urgent'}`}>
              {source.freshness_active && !source.freshness_expired ? t('sources.publishEligible') : t('sources.publishBlocked')}
            </span>
          </div>
        </div>
        <div>
          <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('sources.progress')}</span>
          <div className="flex items-center gap-2">
            <progress className="h-2 min-w-0 flex-1 accent-primary" value={source.progress} max={100} aria-label={t('sources.progressLabel', { title: source.title ?? source.id })} />
            <span className="font-mono text-xs text-faint">{source.progress}%</span>
          </div>
          <p className="mt-1 line-clamp-2 font-mono text-xs text-muted-foreground">{source.progress_message ?? t('sources.noProgressMessage')}</p>
          <p className="mt-1 font-mono text-xs text-faint">{t('sources.extractionCounts', { pages: source.page_count, tokens: source.extracted_token_count ?? '—', wiki: source.wiki_page_count })}</p>
        </div>
        <div>
          <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('sources.scope')}</span>
          <p className="font-mono text-xs text-muted-foreground">{source.scope_type}</p>
          <p className="mt-1 line-clamp-2 font-mono text-xs text-faint">{source.department_names.join(', ') || t('sources.noDepartments')}</p>
        </div>
        <div>
          <span className="mb-1 block font-mono text-xs uppercase text-faint xl:hidden">{t('sources.actions')}</span>
          <div className="flex flex-wrap gap-2">
            {canEdit && retryAllowed ? <Button type="button" variant="ghost" size="sm" disabled={pending !== null} onClick={runRetry}>{pending === 'retry' ? t('sources.pending') : t('sources.retry')}</Button> : null}
            {canEdit && extractionAllowed ? <Button type="button" size="sm" disabled={pending !== null} onClick={runExtractionApproval}>{pending === 'extraction' ? t('sources.pending') : t('sources.approveExtraction')}</Button> : null}
            {!canEdit && (retryAllowed || extractionAllowed || source.status === 'plan_ready') ? <span className="bp-tol bp-tol-flat">{t('sources.readOnly')}</span> : null}
          </div>
        </div>
      </div>
      <p className="mt-2 font-mono text-xs text-faint">{t('sources.updatedAt', { time: DATE_FORMAT.format(new Date(source.updated_at)) })}</p>
      {error ? <div className="mt-3"><RequestErrorState error={error} compact /></div> : null}
      {receipt ? <Receipt receipt={receipt} className="mt-3" /> : null}
    </article>
  )
}

function SourceLanguagePanel({ source, canEdit, onChanged }: { source: SourceRecord; canEdit: boolean; onChanged: () => void }) {
  const { t } = useTranslation()
  const [language, setLanguage] = useState<SourceLanguage>(source.language)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [receipt, setReceipt] = useState<SourceRecord | null>(null)
  const locked = ACTIVE_SOURCE_STATUSES.has(source.status) || source.status === 'awaiting_approval' || source.status === 'plan_ready' || source.status === 'deleting'

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setPending(true)
    setError(null)
    setReceipt(null)
    updateSourceLanguage(source.id, language)
      .then((next) => {
        setReceipt(next)
        onChanged()
      })
      .catch((nextError: unknown) => setError(nextError))
      .finally(() => setPending(false))
  }

  return (
    <section aria-labelledby="source-language-heading" className="bp-panel p-4">
      <h3 id="source-language-heading" className="font-mono text-sm font-bold">{t('sources.languageTitle')}</h3>
      <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.languageNote')}</p>
      <p className="mt-3 font-mono text-xs text-faint">{t('sources.languageCurrent', { language: source.language })}</p>
      {canEdit ? (
        <form onSubmit={submit} className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end">
          <label className="min-w-0 flex-1">
            <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.language')}</span>
            <select value={language} onChange={(event) => setLanguage(event.target.value as SourceLanguage)} disabled={pending || locked} className={FIELD_CLASS}>
              <option value="en">{t('sources.languageEn')}</option>
              <option value="zh">{t('sources.languageZh')}</option>
            </select>
          </label>
          <Button type="submit" className="min-h-11" disabled={pending || locked || language === source.language}>
            {pending ? <RotateCw aria-hidden="true" size={14} className="animate-spin" /> : null}
            {pending ? t('sources.pending') : t('sources.updateLanguage')}
          </Button>
        </form>
      ) : <p className="mt-3 font-mono text-xs text-muted-foreground">{t('sources.readOnly')}</p>}
      {locked ? <p className="mt-2 font-mono text-xs text-faint">{t('sources.languageLocked')}</p> : null}
      {error ? <div className="mt-3"><RequestErrorState error={error} compact /></div> : null}
      {receipt ? <p role="status" className="mt-3 font-mono text-xs" style={{ color: 'var(--ok)' }}>{t('sources.languagePersisted', { language: receipt.language })}</p> : null}
    </section>
  )
}

function SourceFreshnessPanel({ source, canEdit, onChanged }: { source: SourceRecord; canEdit: boolean; onChanged: () => void }) {
  const { t } = useTranslation()
  const [freshnessState, setFreshnessState] = useState<SourceFreshnessState>(source.freshness_state)
  const [reason, setReason] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [receipt, setReceipt] = useState<SourceRecord | null>(null)
  const publishEligible = source.freshness_active && !source.freshness_expired

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!reason.trim()) {
      setError(new Error(t('sources.freshnessReasonRequired')))
      return
    }
    if (freshnessState === 'fresh' && !expiresAt) {
      setError(new Error(t('sources.freshnessExpiryRequired')))
      return
    }
    setPending(true)
    setError(null)
    setReceipt(null)
    attestSourceFreshness(source.id, {
      freshnessState,
      reason,
      expiresAt: freshnessState === 'fresh' ? new Date(expiresAt).toISOString() : undefined,
    })
      .then((next) => {
        setReceipt(next)
        onChanged()
      })
      .catch((nextError: unknown) => setError(nextError))
      .finally(() => setPending(false))
  }

  return (
    <section aria-labelledby="source-freshness-heading" className="bp-panel overflow-hidden">
      <div className="bp-dim flex flex-wrap items-center gap-2 px-4 py-3">
        <h3 id="source-freshness-heading" className="font-mono text-sm font-bold">{t('sources.freshnessTitle')}</h3>
        <span className="font-mono text-xs text-faint">{source.title ?? source.id}</span>
        <span className={`ml-auto bp-tol ${publishEligible ? 'bp-tol-ok' : 'bp-tol-urgent'}`}>
          {publishEligible ? t('sources.publishEligible') : t('sources.publishBlocked')}
        </span>
      </div>
      <div className="p-4">
        <dl className="grid gap-3 md:grid-cols-3">
          <Meta label={t('sources.freshnessState')} value={source.freshness_expired ? t('sources.freshnessExpired') : t(`sources.freshness.${source.freshness_state}`)} />
          <Meta label={t('sources.freshnessAttested')} value={source.freshness_attested_at ? DATE_FORMAT.format(new Date(source.freshness_attested_at)) : '—'} />
          <Meta label={t('sources.freshnessExpires')} value={source.freshness_expires_at ? DATE_FORMAT.format(new Date(source.freshness_expires_at)) : '—'} />
        </dl>
        <p className="mt-3 font-mono text-xs leading-relaxed text-muted-foreground">{source.freshness_reason ?? t('sources.freshnessNoReason')}</p>
        <p className="mt-2 font-mono text-xs text-faint">{t('sources.freshnessBoundary')}</p>

        {canEdit ? (
          <form onSubmit={submit} className="mt-4 bp-dim pt-4">
            <div className="grid gap-3 md:grid-cols-3">
              <label>
                <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.freshnessState')}</span>
                <select value={freshnessState} onChange={(event) => { const next = event.target.value as SourceFreshnessState; setFreshnessState(next); if (next !== 'fresh') setExpiresAt('') }} className={FIELD_CLASS} disabled={pending}>
                  <option value="fresh">{t('sources.freshness.fresh')}</option>
                  <option value="stale">{t('sources.freshness.stale')}</option>
                  <option value="unknown">{t('sources.freshness.unknown')}</option>
                </select>
              </label>
              <label className="md:col-span-2">
                <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.freshnessReason')}</span>
                <input value={reason} onChange={(event) => setReason(event.target.value)} maxLength={2000} required disabled={pending} className={FIELD_CLASS} />
              </label>
              {freshnessState === 'fresh' ? (
                <label>
                  <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.freshnessExpires')}</span>
                  <input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} required disabled={pending} className={FIELD_CLASS} />
                </label>
              ) : null}
            </div>
            <Button type="submit" className="mt-3 min-h-11" disabled={pending || !reason.trim() || (freshnessState === 'fresh' && !expiresAt)}>
              {pending ? <RotateCw aria-hidden="true" size={14} className="animate-spin" /> : null}
              {pending ? t('sources.pending') : t('sources.attestFreshness')}
            </Button>
          </form>
        ) : <p className="mt-4 font-mono text-xs text-muted-foreground">{t('sources.freshnessReadOnly')}</p>}

        {error ? <div className="mt-3"><RequestErrorState error={error} compact /></div> : null}
        {receipt ? (
          <section role="status" className="mt-3 bp-panel p-3" style={{ borderColor: 'color-mix(in srgb, var(--ok) 45%, transparent)' }}>
            <span className="bp-stamp" style={{ color: 'var(--ok)' }}>{t('sources.freshnessPersisted')}</span>
            <p className="mt-2 font-mono text-xs text-muted-foreground">{t('sources.freshnessReceipt', { state: receipt.freshness_state, active: String(receipt.freshness_active) })}</p>
          </section>
        ) : null}
      </div>
    </section>
  )
}

function SourcePlanPanel({ source, canEdit, onChanged }: { source: SourceRecord; canEdit: boolean; onChanged: () => void }) {
  const { t } = useTranslation()
  const [plan, setPlan] = useState<SourceCompilationPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [note, setNote] = useState('')
  const [pending, setPending] = useState<'approve' | 'reject' | 'regenerate' | null>(null)
  const [receipt, setReceipt] = useState<CommandReceipt | null>(null)
  const [planPollStale, setPlanPollStale] = useState(false)
  const requestKey = useRef(0)
  const planPollAttempts = useRef(0)

  const load = useCallback(() => {
    const key = ++requestKey.current
    setLoading(true)
    setError(null)
    fetchSourceCompilationPlan(source.id)
      .then((next) => {
        if (key !== requestKey.current) return
        setPlan(next)
        if (next.status !== 'regenerating') setPlanPollStale(false)
      })
      .catch((nextError: unknown) => {
        if (key === requestKey.current) setError(nextError)
      })
      .finally(() => {
        if (key === requestKey.current) setLoading(false)
      })
  }, [source.id])

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) load() })
    return () => {
      active = false
      requestKey.current += 1
    }
  }, [load])

  useEffect(() => {
    if (plan?.status !== 'regenerating') {
      planPollAttempts.current = 0
      return
    }
    if (planPollAttempts.current >= MAX_PROGRESS_POLLS) {
      queueMicrotask(() => setPlanPollStale(true))
      return
    }
    const delay = Math.min(30_000, 4_000 * (2 ** planPollAttempts.current))
    const timer = window.setTimeout(() => {
      planPollAttempts.current += 1
      load()
    }, delay)
    return () => window.clearTimeout(timer)
  }, [load, plan?.status])

  const runCommand = (action: 'approve' | 'reject' | 'regenerate') => {
    if ((action === 'reject' || action === 'regenerate') && !note.trim()) {
      setError(new Error(t('sources.noteRequired')))
      return
    }
    setPending(action)
    setError(null)
    setReceipt(null)
    const command = action === 'approve'
      ? approveSourceCompilationPlan(source.id, note)
      : action === 'reject'
        ? rejectSourceCompilationPlan(source.id, note)
        : regenerateSourceCompilationPlan(source.id, note)
    command
      .then((next) => {
        const jobId = 'job_id' in next ? next.job_id : null
        setReceipt({ label: t('sources.planCommandCommitted'), detail: t(`sources.planReceipt.${action}`), jobId })
        onChanged()
        load()
      })
      .catch(setError)
      .finally(() => setPending(null))
  }

  const noPlan = error instanceof ApiError && error.status === 404
  return (
    <section aria-labelledby="source-plan-heading" className="bp-panel overflow-hidden">
      <div className="bp-dim flex flex-wrap items-center gap-2 px-4 py-3">
        <h3 id="source-plan-heading" className="font-mono text-sm font-bold">{t('sources.planTitle')}</h3>
        <span className="font-mono text-xs text-faint">{source.title ?? source.id}</span>
        {plan ? <span className={`ml-auto bp-tol ${plan.status === 'approved' || plan.status === 'done' ? 'bp-tol-ok' : plan.status === 'rejected' ? 'bp-tol-urgent' : 'bp-tol-high'}`}>{plan.status}</span> : null}
      </div>
      <div className="p-4">
        {loading ? <p role="status" className="font-mono text-xs text-muted-foreground">{t('sources.planLoading')}</p> : null}
        {!loading && noPlan ? <p className="font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.noPlan')}</p> : null}
        {!loading && error && !noPlan ? <RequestErrorState error={error} onRetry={load} compact /> : null}
        {plan ? (
          <>
            <div className="grid gap-3 md:grid-cols-3">
              <Meta label={t('sources.planCreated')} value={DATE_FORMAT.format(new Date(plan.created_at))} />
              <Meta label={t('sources.planReviewed')} value={plan.reviewed_at ? DATE_FORMAT.format(new Date(plan.reviewed_at)) : '—'} />
              <Meta label={t('sources.planNote')} value={plan.review_note ?? '—'} />
            </div>
            <div className="mt-4 space-y-2">
              {(plan.plan.pages ?? []).map((page) => (
                <article key={`${page.action}:${page.slug}`} className="bp-dim px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="bp-tol bp-tol-flat">{page.action}</span>
                    <span className="font-mono text-xs font-bold">{page.title}</span>
                    {page.priority !== undefined ? <span className="ml-auto font-mono text-xs text-faint">P{page.priority}</span> : null}
                  </div>
                  <p className="mt-1 font-mono text-xs text-faint">{page.slug}</p>
                  {page.summary ? <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{page.summary}</p> : null}
                </article>
              ))}
              {(plan.plan.pages ?? []).length === 0 ? <p className="font-mono text-xs text-muted-foreground">{t('sources.planPagesEmpty')}</p> : null}
            </div>
            {canEdit && (plan.status === 'pending_review' || plan.status === 'rejected') ? (
              <div className="mt-4 bp-dim pt-4">
                <label>
                  <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{t('sources.reviewNote')}</span>
                  <textarea value={note} onChange={(event) => setNote(event.target.value)} maxLength={2000} rows={3} className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring" />
                </label>
                <div className="mt-3 flex flex-wrap gap-2">
                  {plan.status === 'pending_review' ? <Button type="button" disabled={pending !== null} onClick={() => runCommand('approve')}>{pending === 'approve' ? t('sources.pending') : t('sources.approvePlan')}</Button> : null}
                  <Button type="button" variant="ghost" disabled={pending !== null || !note.trim()} onClick={() => runCommand('regenerate')}>{pending === 'regenerate' ? t('sources.pending') : t('sources.regeneratePlan')}</Button>
                  {plan.status === 'pending_review' ? <Button type="button" variant="ghost" disabled={pending !== null || !note.trim()} onClick={() => runCommand('reject')}>{pending === 'reject' ? t('sources.pending') : t('sources.rejectPlan')}</Button> : null}
                </div>
                <p className="mt-2 font-mono text-xs text-faint">{t('sources.planCommandBoundary')}</p>
              </div>
            ) : null}
            {plan.status === 'regenerating' ? <p role="status" className="mt-4 font-mono text-xs text-muted-foreground">{t('sources.planRegenerating')}</p> : null}
            {planPollStale ? (
              <div className="mt-4 bp-panel p-3" style={{ borderColor: 'var(--high)' }}>
                <p className="font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.planPollStopped')}</p>
                <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={() => { planPollAttempts.current = 0; setPlanPollStale(false); load() }}>{t('state.retry')}</Button>
              </div>
            ) : null}
          </>
        ) : null}
        {receipt ? <Receipt receipt={receipt} className="mt-4" /> : null}
      </div>
    </section>
  )
}

function SourceRiskObservations({ data, loading, error, onRetry }: { data: SourceBlindnessSurface | null; loading: boolean; error: unknown; onRetry: () => void }) {
  const { t } = useTranslation()
  if (loading) return <PageSkeleton />
  if (error) return (
    <section aria-labelledby="source-risk-heading" className="space-y-3">
      <div>
        <h2 id="source-risk-heading" className="font-mono text-lg font-bold">{t('sources.riskObservations')}</h2>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{t('sources.riskObservationsNote')}</p>
      </div>
      <RequestErrorState error={error} onRetry={onRetry} />
    </section>
  )
  if (!data) return null

  const rows = data.contexts
  const failures = data.source_observations
  const surfaces = new Set(rows.flatMap((context) => context.affected_surfaces)).size
  const emptyCopyKey = failures.length > 0
    ? 'observation.sourceFactsOnly'
    : data.observation.state === 'ready'
      ? 'observation.sourceEmptyReady'
      : data.observation.state === 'partial'
        ? 'observation.sourceEmptyPartial'
        : 'observation.sourceEmptyUnavailable'

  return (
    <section aria-labelledby="source-risk-heading" className="space-y-4 bp-dim border-t border-border pt-6">
      <div>
        <h2 id="source-risk-heading" className="font-mono text-lg font-bold">{t('sources.riskObservations')}</h2>
        <p className="mt-1 font-mono text-xs leading-relaxed text-muted-foreground">{t('sources.riskObservationsNote')}</p>
      </div>
      <ObservationBanner observation={data.observation} />
      <p className="font-mono text-xs leading-relaxed text-muted-foreground">{data.summary}</p>
      <div className="flex flex-wrap gap-2.5">
        <Stat n={failures.length} label={t('observation.sourceFacts')} dot="var(--high)" />
        <Stat n={rows.length} label={t('observation.completeRisks')} dot="var(--urgent)" />
        <Stat n={surfaces} label={t('queue.statSurfaces')} />
      </div>
      {failures.length > 0 ? (
        <section aria-labelledby="source-facts-heading">
          <h3 id="source-facts-heading" className="mb-2 bp-label">{t('observation.sourceFacts')}</h3>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {failures.map((failure) => <SourceFailureCard key={failure.source_id} failure={failure} />)}
          </div>
        </section>
      ) : null}
      {rows.length > 0 ? (
        <section aria-labelledby="complete-source-risks-heading">
          <h3 id="complete-source-risks-heading" className="mb-2 bp-label">{t('observation.completeRisks')}</h3>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {rows.map((context) => <SourceRiskCard key={context.proposal_ref} context={context} command={data.available_commands[0]} />)}
          </div>
        </section>
      ) : (
        <div className="bp-panel px-4 py-8 text-center font-mono text-sm text-muted-foreground">{t(emptyCopyKey)}</div>
      )}
    </section>
  )
}

function SourceRiskCard({ context, command }: { context: SourceBlindnessContext; command: string }) {
  const { t } = useTranslation()
  const v = useVocab()
  const worstFreshness = context.freshness_states.includes('stale') ? 'stale' : context.freshness_states[0] ?? 'unknown'
  return (
    <article className="bp-panel overflow-hidden">
      <div className="bp-dim flex items-center gap-2 px-4 py-3">
        <span className="h-2 w-2 rotate-45" style={{ background: 'var(--urgent)' }} />
        <span className="font-mono text-xs font-bold uppercase tracking-wide" style={{ color: 'var(--urgent)' }}>{t('src.blind')}</span>
        <span className="bp-tol bp-tol-flat ml-auto">{v.freshness(worstFreshness)}</span>
      </div>
      <div className="flex flex-col gap-3 p-4">
        <div>
          <div className="font-mono text-sm font-semibold leading-tight">{context.title}</div>
          <div className="mt-1 font-mono text-xs text-muted-foreground">{context.proposal_ref} · {v.objectType(context.suggested_object_type)}</div>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">{context.business_consequence}</p>
        {context.source_refs.length > 0 ? (
          <div className="space-y-1">
            {context.source_refs.map((ref, index) => (
              <div key={ref} className="flex flex-wrap items-center gap-2 font-mono text-xs">
                <span className="h-1.5 w-1.5 rotate-45 bg-faint" />
                <span className="break-all text-muted-foreground">{ref}</span>
                <span className="text-faint">{v.evidenceSourceType(context.source_types[index] ?? '')} · {v.freshness(context.freshness_states[index] ?? 'unknown')}</span>
              </div>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap gap-1.5">
          {context.affected_surfaces.map((surface) => <span key={surface} className="bp-tol bp-tol-flat">{v.surface(surface)}</span>)}
        </div>
        <p className="bp-dim pt-3 font-mono text-xs leading-relaxed text-faint">{context.signal_loss_summary}</p>
        {command ? <div className="bp-dim flex justify-end pt-3"><CmdButton command={command} /></div> : null}
      </div>
    </article>
  )
}

function TextField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1.5 block font-mono text-xs text-muted-foreground">{label}</span>
      <input value={value} onChange={(event) => onChange(event.target.value)} maxLength={500} className={FIELD_CLASS} />
    </label>
  )
}

function CheckField({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return (
    <label className="flex min-h-10 items-center gap-2 font-mono text-xs text-muted-foreground">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} className="h-4 w-4 accent-primary" />
      <span>{label}</span>
    </label>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return <div><div className="font-mono text-xs text-faint">{label}</div><div className="mt-1 break-words font-mono text-xs">{value}</div></div>
}

function Receipt({ receipt, className = '' }: { receipt: CommandReceipt; className?: string }) {
  const { t } = useTranslation()
  return (
    <section role="status" className={`bp-panel p-3 ${className}`} style={{ borderColor: 'color-mix(in srgb, var(--ok) 45%, transparent)' }}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="bp-stamp" style={{ color: 'var(--ok)' }}>{receipt.label}</span>
        <span className="font-mono text-xs text-muted-foreground">{receipt.detail}</span>
      </div>
      {receipt.jobId ? <p className="mt-2 break-all font-mono text-xs text-faint">{t('sources.dispatchId')}: {receipt.jobId}</p> : null}
      <p className="mt-2 font-mono text-xs text-faint">{t('sources.receiptBoundary')}</p>
    </section>
  )
}
