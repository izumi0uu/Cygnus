import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { Check, KeyRound, ShieldCheck } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import AdminDialog from '@/components/AdminDialog'
import { RequestErrorState } from '@/components/RequestState'
import { PageSkeleton } from '@/components/Skeleton'
import { Button } from '@/components/ui/button'
import {
  changePassword,
  fetchModelCatalog,
  modelApiKeyConfigKey,
  saveModelApiKey,
  switchModel,
  type LLMCatalog,
  type ModelCatalog,
  type ModelSpec,
} from '@/lib/adminApi'

type ModelCapability = 'embedding' | 'llm' | 'vision'
type Catalogs = Record<ModelCapability, ModelCatalog>
const CAPABILITIES: ModelCapability[] = ['embedding', 'llm', 'vision']

export default function Settings() {
  const { t } = useTranslation()
  const [catalogs, setCatalogs] = useState<Catalogs | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [action, setAction] = useState<{ capability: ModelCapability; spec: ModelSpec } | null>(null)
  const requestKey = useRef(0)

  const load = useCallback((background = false) => {
    const key = ++requestKey.current
    if (!background) setLoading(true)
    setError(null)
    Promise.all(CAPABILITIES.map((capability) => fetchModelCatalog(capability)))
      .then(([embedding, llm, vision]) => {
        if (key !== requestKey.current) return
        setCatalogs({ embedding, llm, vision })
      })
      .catch((nextError: unknown) => {
        if (key === requestKey.current) setError(nextError)
      })
      .finally(() => {
        if (key === requestKey.current) setLoading(false)
      })
  }, [])

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) load() })
    return () => {
      active = false
      requestKey.current += 1
    }
  }, [load])

  if (loading && !catalogs) return <PageSkeleton />
  if (error && !catalogs) return <RequestErrorState error={error} onRetry={() => load()} />
  if (!catalogs) return null

  return (
    <div className="space-y-4">
      <header className="bp-panel p-5">
        <div className="bp-label">{t('settings.eyebrow')}</div>
        <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('settings.title')}</h1>
        <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">
          {t('settings.description')}
        </p>
      </header>

      {error ? <RequestErrorState error={error} onRetry={() => load()} compact stale /> : null}

      <section className="space-y-3" aria-labelledby="model-settings-title">
        <div className="px-1">
          <h2 id="model-settings-title" className="font-mono text-sm font-bold">{t('settings.models.title')}</h2>
          <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">{t('settings.models.description')}</p>
        </div>
        {CAPABILITIES.map((capability) => (
          <ModelCatalogCard
            key={capability}
            capability={capability}
            catalog={catalogs[capability]}
            onConfigure={(spec) => setAction({ capability, spec })}
          />
        ))}
      </section>

      <PasswordSettings />

      {action ? (
        <ModelActionDialog
          capability={action.capability}
          spec={action.spec}
          activeSpecId={action.capability === 'llm' && (catalogs.llm as LLMCatalog).active_mode === 'custom' ? null : catalogs[action.capability].active_spec_id}
          onClose={() => setAction(null)}
          onCompleted={() => load(true)}
        />
      ) : null}
    </div>
  )
}

function ModelCatalogCard({
  capability,
  catalog,
  onConfigure,
}: {
  capability: ModelCapability
  catalog: ModelCatalog
  onConfigure: (spec: ModelSpec) => void
}) {
  const { t } = useTranslation()
  const initial = catalog.active_spec_id ?? catalog.specs[0]?.id ?? ''
  const [selectedId, setSelectedId] = useState(initial)


  const resolvedSelectedId = catalog.specs.some((spec) => spec.id === selectedId) ? selectedId : initial
  const selected = catalog.specs.find((spec) => spec.id === resolvedSelectedId) ?? null
  const llmCustomActive = capability === 'llm' && (catalog as LLMCatalog).active_mode === 'custom'

  return (
    <div className="bp-panel p-4">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="font-mono text-sm font-bold">{t(`settings.models.${capability}.title`)}</h3>
          <p className="mt-1 font-mono text-[10.5px] leading-relaxed text-muted-foreground">{t(`settings.models.${capability}.description`)}</p>
        </div>
        {llmCustomActive ? <span className="bp-tol bp-tol-high">{t('settings.models.customActive')}</span> : null}
      </div>

      {catalog.specs.length === 0 ? (
        <p className="mt-4 border border-border bg-muted px-3 py-4 font-mono text-[11px] text-muted-foreground">
          {t('settings.models.empty')}
        </p>
      ) : (
        <fieldset className="mt-4">
          <legend className="sr-only">{t('settings.models.select', { capability: t(`settings.models.${capability}.title`) })}</legend>
          <div className="grid gap-2 lg:grid-cols-2">
            {catalog.specs.map((spec) => {
              const selectedSpec = spec.id === resolvedSelectedId
              const active = spec.id === catalog.active_spec_id && !llmCustomActive
              return (
                <label
                  key={spec.id}
                  className={`min-h-11 cursor-pointer border p-3 transition-colors ${selectedSpec ? 'border-primary bg-accent' : 'border-border bg-card hover:bg-muted'}`}
                >
                  <div className="flex items-start gap-3">
                    <input className="mt-1" type="radio" name={`${capability}-model`} value={spec.id} checked={selectedSpec} onChange={() => setSelectedId(spec.id)} />
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="font-mono text-xs font-bold text-foreground">{spec.label}</span>
                        <span className="bp-tol bp-tol-flat">{spec.provider}</span>
                        {active ? <span className="bp-tol bp-tol-ok">{t('settings.models.active')}</span> : null}
                      </span>
                      <span className="mt-1.5 block break-all font-mono text-[10px] text-muted-foreground">{spec.model_id}</span>
                      <ModelMetadata capability={capability} spec={spec} />
                      {spec.notes ? <span className="mt-1.5 block font-mono text-[10px] leading-relaxed text-faint">{spec.notes}</span> : null}
                    </span>
                  </div>
                </label>
              )
            })}
          </div>
        </fieldset>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-border pt-4">
        <Button type="button" disabled={!selected} onClick={() => selected && onConfigure(selected)}>
          <KeyRound aria-hidden="true" size={14} />
          {selected?.id === catalog.active_spec_id && !llmCustomActive
            ? t('settings.models.manageKey')
            : t('settings.models.configureSwitch')}
        </Button>
        {selected ? (
          <span className="font-mono text-[10px] text-faint">
            {selected.api_key_configured ? t('settings.models.keyConfigured') : t('settings.models.keyRequired')}
          </span>
        ) : null}
      </div>
    </div>
  )
}

function ModelMetadata({ capability, spec }: { capability: ModelCapability; spec: ModelSpec }) {
  const { t } = useTranslation()
  const values: string[] = []
  if (capability === 'embedding' && spec.dimension) values.push(t('settings.models.dimension', { count: spec.dimension }))
  if (capability === 'llm' && spec.context_window_tokens) values.push(t('settings.models.context', { count: spec.context_window_tokens.toLocaleString() }))
  if (capability === 'llm' && spec.max_output_tokens) values.push(t('settings.models.output', { count: spec.max_output_tokens.toLocaleString() }))
  if (capability === 'llm' && spec.supports_tools) values.push(t('settings.models.tools'))
  if (capability === 'llm' && spec.supports_vision) values.push(t('settings.models.visionCapable'))
  if (capability === 'vision' && spec.max_image_size_mb) values.push(t('settings.models.imageSize', { count: spec.max_image_size_mb }))
  if (values.length === 0) return null
  return <span className="mt-1.5 block font-mono text-[9.5px] text-faint">{values.join(' · ')}</span>
}

function ModelActionDialog({
  capability,
  spec,
  activeSpecId,
  onClose,
  onCompleted,
}: {
  capability: ModelCapability
  spec: ModelSpec
  activeSpecId: string | null
  onClose: () => void
  onCompleted: () => void
}) {
  const { t } = useTranslation()
  const keyRef = useRef<HTMLInputElement>(null)
  const receiptRef = useRef<HTMLDivElement>(null)
  const [apiKey, setApiKey] = useState('')
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState('')
  const [receipt, setReceipt] = useState<{ jobId?: string } | null>(null)
  const switching = spec.id !== activeSpecId
  const keyRequired = !spec.api_key_configured
  const canSubmit = switching ? spec.api_key_configured || apiKey.trim().length > 0 : apiKey.trim().length > 0

  useEffect(() => {
    if (receipt) receiptRef.current?.focus()
  }, [receipt])

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!canSubmit || pending || receipt) return
    setPending(true)
    setServerError('')
    let keyPersisted = false
    try {
      const normalizedKey = apiKey.trim()
      if (normalizedKey) {
        await saveModelApiKey(modelApiKeyConfigKey(capability, spec.provider), normalizedKey)
        keyPersisted = true
      }
      const result = switching ? await switchModel(capability, spec.id) : {}
      setReceipt({ jobId: result.job_id })
      onCompleted()
    } catch (nextError) {
      const detail = nextError instanceof Error ? nextError.message : String(nextError)
      setServerError(keyPersisted && switching ? `${t('settings.modelDialog.partialFailure')} ${detail}` : detail)
    } finally {
      setPending(false)
    }
  }

  return (
    <AdminDialog
      titleId="model-action-title"
      descriptionId="model-action-description"
      title={switching ? t('settings.modelDialog.switchTitle', { model: spec.label }) : t('settings.modelDialog.keyTitle', { model: spec.label })}
      description={capability === 'embedding' && switching ? t('settings.modelDialog.embeddingWarning') : t('settings.modelDialog.description')}
      pending={pending}
      initialFocusRef={keyRef}
      onClose={onClose}
    >
      {receipt ? (
        <div ref={receiptRef} tabIndex={-1} className="mt-5 outline-none" role="status" aria-live="polite">
          <div className="border border-border bg-muted p-4">
            <div className="flex items-center gap-2 font-mono text-sm font-bold" style={{ color: 'var(--ok)' }}>
              <Check aria-hidden="true" size={16} />
              {switching ? t('settings.modelDialog.switchAccepted') : t('settings.modelDialog.keySaved')}
            </div>
            {receipt.jobId ? (
              <p className="mt-2 break-all font-mono text-[11px] leading-relaxed text-muted-foreground">
                {t('settings.modelDialog.jobQueued', { id: receipt.jobId })}
              </p>
            ) : null}
          </div>
          <div className="mt-5 flex justify-end border-t border-border pt-4">
            <Button type="button" className="min-h-11" onClick={onClose}>{t('settings.modelDialog.close')}</Button>
          </div>
        </div>
      ) : (
        <form className="mt-5" onSubmit={submit}>
          <div className="border border-border bg-muted p-3 font-mono text-[11px] leading-relaxed text-muted-foreground">
            <div><span className="text-faint">{t('settings.modelDialog.capability')}:</span> {t(`settings.models.${capability}.title`)}</div>
            <div className="mt-1"><span className="text-faint">{t('settings.modelDialog.provider')}:</span> {spec.provider}</div>
            <div className="mt-1 break-all"><span className="text-faint">{t('settings.modelDialog.model')}:</span> {spec.model_id}</div>
          </div>
          <div className="mt-4">
            <label htmlFor="model-api-key" className="bp-label">
              {t('settings.modelDialog.apiKey', { provider: spec.provider })}
            </label>
            <input
              id="model-api-key"
              ref={keyRef}
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              required={keyRequired || !switching}
              autoComplete="off"
              spellCheck={false}
              placeholder={spec.api_key_configured ? t('settings.modelDialog.keepExisting') : t('settings.modelDialog.enterKey')}
              aria-describedby="model-api-key-hint"
              className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary"
            />
            <p id="model-api-key-hint" className="mt-1.5 font-mono text-[10px] leading-relaxed text-faint">
              {spec.api_key_configured ? t('settings.modelDialog.savedKeyHint') : t('settings.modelDialog.requiredKeyHint')}
            </p>
          </div>
          {serverError ? <div role="alert" className="mt-4 border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-[11px] text-destructive">{serverError}</div> : null}
          <div className="mt-5 flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-end">
            <Button type="button" variant="ghost" disabled={pending} className="min-h-11" onClick={onClose}>{t('settings.modelDialog.cancel')}</Button>
            <Button type="submit" disabled={!canSubmit || pending} className="min-h-11">
              {pending ? t('settings.modelDialog.saving') : switching ? t('settings.modelDialog.saveSwitch') : t('settings.modelDialog.saveKey')}
            </Button>
          </div>
        </form>
      )}
    </AdminDialog>
  )
}

function PasswordSettings() {
  const { t } = useTranslation()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const mismatch = confirmPassword.length > 0 && newPassword !== confirmPassword

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (mismatch || pending) return
    setPending(true)
    setError('')
    setSuccess('')
    try {
      await changePassword(currentPassword, newPassword)
      setSuccess(t('settings.password.updated'))
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="bp-panel p-4" aria-labelledby="password-settings-title">
      <div className="flex items-start gap-3">
        <ShieldCheck aria-hidden="true" className="mt-0.5 shrink-0 text-primary" size={18} />
        <div>
          <h2 id="password-settings-title" className="font-mono text-sm font-bold">{t('settings.password.title')}</h2>
          <p className="mt-1 font-mono text-[10.5px] leading-relaxed text-muted-foreground">{t('settings.password.description')}</p>
        </div>
      </div>
      <form className="mt-4 grid gap-4 lg:grid-cols-3" onSubmit={submit}>
        <div>
          <label htmlFor="current-password" className="bp-label">{t('settings.password.current')}</label>
          <input id="current-password" type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} required autoComplete="current-password" className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary" />
        </div>
        <div>
          <label htmlFor="new-password" className="bp-label">{t('settings.password.new')}</label>
          <input id="new-password" type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} required minLength={6} autoComplete="new-password" className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary" />
        </div>
        <div>
          <label htmlFor="confirm-password" className="bp-label">{t('settings.password.confirm')}</label>
          <input id="confirm-password" type="password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} required minLength={6} autoComplete="new-password" aria-invalid={mismatch || undefined} aria-describedby={mismatch ? 'password-mismatch' : undefined} className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary" />
          {mismatch ? <p id="password-mismatch" role="alert" className="mt-1.5 font-mono text-[10px] text-destructive">{t('settings.password.mismatch')}</p> : null}
        </div>
        <div className="lg:col-span-3">
          {error ? <div role="alert" className="mb-3 border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-[11px] text-destructive">{error}</div> : null}
          {success ? <div role="status" className="mb-3 border px-3 py-2 font-mono text-[11px]" style={{ color: 'var(--ok)', borderColor: 'color-mix(in srgb, var(--ok) 40%, transparent)' }}>{success}</div> : null}
          <Button type="submit" disabled={pending || mismatch} className="min-h-11">{pending ? t('settings.password.saving') : t('settings.password.save')}</Button>
        </div>
      </form>
    </section>
  )
}
