import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Minus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { RequestErrorState } from '@/components/RequestState'
import { PageSkeleton } from '@/components/Skeleton'
import { fetchRoleCatalog, type RoleCatalog } from '@/lib/adminApi'

export default function RoleManagement() {
  const { t } = useTranslation()
  const [catalog, setCatalog] = useState<RoleCatalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const requestKey = useRef(0)

  const load = useCallback(() => {
    const key = ++requestKey.current
    setLoading(true)
    setError(null)
    fetchRoleCatalog()
      .then((nextCatalog) => {
        if (key === requestKey.current) setCatalog(nextCatalog)
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

  if (loading && !catalog) return <PageSkeleton />
  if (error && !catalog) return <RequestErrorState error={error} onRetry={load} />
  if (!catalog) return null

  const permissionCount = catalog.groups.reduce((count, group) => count + group.permissions.length, 0)

  return (
    <div className="space-y-4">
      <header className="bp-panel p-5">
        <div className="bp-label">{t('roles.eyebrow')}</div>
        <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('roles.title')}</h1>
        <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">
          {t('roles.summary')}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <span className="bp-tol bp-tol-ok">{t('roles.fixed')}</span>
          <span className="bp-tol bp-tol-flat">{t('roles.roleCount', { count: catalog.roles.length })}</span>
          <span className="bp-tol bp-tol-flat">{t('roles.permissionCount', { count: permissionCount })}</span>
        </div>
      </header>

      {error ? <RequestErrorState error={error} onRetry={load} compact stale /> : null}

      <section className="bp-panel overflow-hidden" aria-labelledby="role-matrix-title" aria-describedby="role-matrix-description">
        <div className="px-4 py-3.5">
          <h2 id="role-matrix-title" className="bp-label">{t('roles.matrix')}</h2>
          <p id="role-matrix-description" className="mt-2 max-w-3xl font-mono text-[11px] leading-relaxed text-muted-foreground">
            {t('roles.matrixHint')}
          </p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] border-collapse text-left font-mono text-xs">
            <thead>
              <tr className="border-y border-border bg-muted/60">
                <th scope="col" className="w-[42%] px-4 py-3 text-[10px] uppercase tracking-wide text-faint">
                  {t('roles.permission')}
                </th>
                {catalog.roles.map((role) => (
                  <th key={role.id} scope="col" className="min-w-36 px-3 py-3 text-center align-top">
                    <span className="block text-xs font-bold text-foreground">{t(`roles.name.${role.id}`)}</span>
                    <span className="mt-1 block text-[9px] font-normal leading-relaxed text-faint">{t(`roles.short.${role.id}`)}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {catalog.groups.map((group) => (
                <RolePermissionGroup key={group.id} group={group} catalog={catalog} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <aside className="bp-panel border-l-4 p-4" style={{ borderLeftColor: 'var(--primary)' }}>
        <h2 className="font-mono text-sm font-bold">{t('roles.assignmentTitle')}</h2>
        <p className="mt-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {t('roles.assignmentHint')}
        </p>
      </aside>
    </div>
  )
}

function RolePermissionGroup({ group, catalog }: { group: RoleCatalog['groups'][number]; catalog: RoleCatalog }) {
  const { t } = useTranslation()
  return (
    <>
      <tr>
        <th colSpan={catalog.roles.length + 1} scope="colgroup" className="border-y border-border bg-secondary/45 px-4 py-2 text-[10px] uppercase tracking-wide text-muted-foreground">
          {t(`roles.group.${group.id}`, { defaultValue: group.id })}
        </th>
      </tr>
      {group.permissions.map((permission) => (
        <tr key={permission.key} className="border-b border-border last:border-0">
          <th scope="row" className="px-4 py-3 font-normal">
            <span className="block font-semibold text-foreground">{permission.label}</span>
            <span className="mt-1 block text-[10px] leading-relaxed text-muted-foreground">{permission.description}</span>
            <code className="mt-1.5 inline-block text-[9px] text-faint">{permission.key}</code>
          </th>
          {catalog.roles.map((role) => {
            const granted = role.permissions.includes(permission.key)
            return (
              <td key={role.id} className="px-3 py-3 text-center">
                <span className="sr-only">
                  {granted
                    ? t('roles.grantedTo', { permission: permission.label, role: t(`roles.name.${role.id}`) })
                    : t('roles.notGrantedTo', { permission: permission.label, role: t(`roles.name.${role.id}`) })}
                </span>
                {granted
                  ? <Check aria-hidden="true" className="mx-auto" size={16} style={{ color: 'var(--ok)' }} />
                  : <Minus aria-hidden="true" className="mx-auto text-faint" size={14} />}
              </td>
            )
          })}
        </tr>
      ))}
    </>
  )
}
