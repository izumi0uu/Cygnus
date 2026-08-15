import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { ChevronLeft, ChevronRight, Pencil, Search, UserPlus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import AdminDialog from '@/components/AdminDialog'
import { RequestErrorState } from '@/components/RequestState'
import { PageSkeleton } from '@/components/Skeleton'
import { Button } from '@/components/ui/button'
import {
  createEmployee,
  fetchDepartments,
  fetchEmployees,
  fetchRoleCatalog,
  toggleEmployee,
  updateEmployee,
  type Department,
  type Employee,
  type GlobalRole,
  type RoleCatalog,
} from '@/lib/adminApi'

const PAGE_SIZE = 20

export default function EmployeeManagement() {
  const { t } = useTranslation()
  const [employees, setEmployees] = useState<Employee[]>([])
  const [departments, setDepartments] = useState<Department[]>([])
  const [catalog, setCatalog] = useState<RoleCatalog | null>(null)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [page, setPage] = useState(1)
  const [query, setQuery] = useState('')
  const [appliedQuery, setAppliedQuery] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)
  const [editing, setEditing] = useState<Employee | null>(null)
  const [editorOpen, setEditorOpen] = useState(false)
  const [toggleTarget, setToggleTarget] = useState<Employee | null>(null)
  const [notice, setNotice] = useState('')
  const requestKey = useRef(0)

  const load = useCallback(() => {
    const key = ++requestKey.current
    setLoading(true)
    setError(null)
    Promise.all([
      fetchEmployees({ search: appliedQuery, page, pageSize: PAGE_SIZE }),
      fetchDepartments(),
      fetchRoleCatalog(),
    ])
      .then(([employeePage, nextDepartments, nextCatalog]) => {
        if (key !== requestKey.current) return
        setEmployees(employeePage.items)
        setTotal(employeePage.total)
        setTotalPages(employeePage.total_pages)
        setDepartments(nextDepartments)
        setCatalog(nextCatalog)
      })
      .catch((nextError: unknown) => {
        if (key === requestKey.current) setError(nextError)
      })
      .finally(() => {
        if (key === requestKey.current) setLoading(false)
      })
  }, [appliedQuery, page])

  useEffect(() => {
    let active = true
    queueMicrotask(() => { if (active) load() })
    return () => {
      active = false
      requestKey.current += 1
    }
  }, [load])

  const openCreate = () => {
    setEditing(null)
    setEditorOpen(true)
  }
  const openEdit = (employee: Employee) => {
    setEditing(employee)
    setEditorOpen(true)
  }
  const refreshAfterMutation = (message: string) => {
    setNotice(message)
    load()
  }

  if (loading && employees.length === 0) return <PageSkeleton />
  if (error && employees.length === 0) return <RequestErrorState error={error} onRetry={load} />

  return (
    <div className="space-y-4">
      <header className="bp-panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="bp-label">{t('employees.eyebrow')}</div>
            <h1 className="mt-2 font-mono text-xl font-bold tracking-tight">{t('employees.title')}</h1>
            <p className="mt-2 max-w-3xl font-mono text-xs leading-relaxed text-muted-foreground">
              {t('employees.description')}
            </p>
          </div>
          <Button type="button" onClick={openCreate}>
            <UserPlus aria-hidden="true" size={15} />
            {t('employees.invite')}
          </Button>
        </div>
      </header>

      <div className="bp-panel p-4">
        <form
          role="search"
          className="flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault()
            setPage(1)
            setAppliedQuery(query.trim())
          }}
        >
          <label htmlFor="employee-search" className="sr-only">{t('employees.search')}</label>
          <div className="relative min-w-0 flex-1">
            <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" size={15} />
            <input
              id="employee-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t('employees.searchPlaceholder')}
              className="min-h-11 w-full border border-input bg-background py-2 pl-9 pr-3 font-mono text-sm outline-none focus:border-primary"
            />
          </div>
          <Button type="submit" variant="outline">{t('employees.search')}</Button>
        </form>
      </div>

      {error ? <RequestErrorState error={error} onRetry={load} compact stale /> : null}
      <div className="sr-only" role="status" aria-live="polite">{notice}</div>

      <section className="bp-panel overflow-hidden" aria-labelledby="employee-directory-title">
        <div className="flex flex-wrap items-baseline gap-2 px-4 py-3.5">
          <h2 id="employee-directory-title" className="bp-label">{t('employees.directory')}</h2>
          <span className="ml-auto font-mono text-[11px] text-faint">{t('employees.total', { count: total })}</span>
        </div>
        {employees.length === 0 ? (
          <div className="border-t border-border px-4 py-12 text-center">
            <p className="font-mono text-sm font-semibold">{t('employees.empty')}</p>
            <p className="mt-2 font-mono text-[11px] text-muted-foreground">{t('employees.emptyHint')}</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-left font-mono text-xs">
              <thead>
                <tr className="border-y border-border bg-muted/60 text-[10px] uppercase tracking-wide text-faint">
                  <th scope="col" className="px-4 py-2.5 font-semibold">{t('employees.person')}</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">{t('employees.role')}</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">{t('employees.departments')}</th>
                  <th scope="col" className="px-4 py-2.5 font-semibold">{t('employees.status')}</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-semibold">{t('employees.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((employee) => {
                  const protectedAdmin = employee.role === 'admin' || employee.global_role === 'admin'
                  const effectiveRole = protectedAdmin ? 'admin' : employee.global_role
                  return (
                    <tr key={employee.id} className="border-b border-border last:border-0">
                      <td className="px-4 py-3">
                        <div className="font-semibold text-foreground">{employee.name}</div>
                        <div className="mt-1 text-[11px] text-muted-foreground">{employee.email}</div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="bp-tol bp-tol-flat">{t(`roles.name.${effectiveRole}`)}</span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {employee.department_names.length > 0 ? employee.department_names.join(' · ') : t('employees.globalOnly')}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`bp-tol ${employee.is_active ? 'bp-tol-ok' : 'bp-tol-urgent'}`}>
                          {employee.is_active ? t('employees.active') : t('employees.inactive')}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <Button type="button" variant="ghost" size="sm" onClick={() => openEdit(employee)}>
                            <Pencil aria-hidden="true" size={13} />{t('employees.edit')}
                          </Button>
                          {protectedAdmin ? (
                            <span className="inline-flex min-h-8 items-center px-2 text-[10px] text-faint" title={t('employees.protectedHint')}>
                              {t('employees.protected')}
                            </span>
                          ) : (
                            <Button type="button" variant="ghost" size="sm" onClick={() => setToggleTarget(employee)}>
                              {employee.is_active ? t('employees.deactivate') : t('employees.activate')}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <nav className="flex items-center justify-between" aria-label={t('employees.pagination')}>
        <Button type="button" variant="ghost" size="sm" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
          <ChevronLeft aria-hidden="true" size={14} />{t('employees.previous')}
        </Button>
        <span className="font-mono text-[11px] text-faint">{t('employees.page', { page, total: totalPages })}</span>
        <Button type="button" variant="ghost" size="sm" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
          {t('employees.next')}<ChevronRight aria-hidden="true" size={14} />
        </Button>
      </nav>

      {editorOpen && catalog ? (
        <EmployeeEditor
          employee={editing}
          departments={departments}
          roles={catalog.roles.map((role) => role.id)}
          onClose={() => setEditorOpen(false)}
          onSaved={() => {
            setEditorOpen(false)
            refreshAfterMutation(editing ? t('employees.updated') : t('employees.invited'))
          }}
        />
      ) : null}

      {toggleTarget ? (
        <ToggleEmployeeDialog
          employee={toggleTarget}
          onClose={() => setToggleTarget(null)}
          onSaved={(isActive) => {
            setToggleTarget(null)
            refreshAfterMutation(isActive ? t('employees.activated') : t('employees.deactivated'))
          }}
        />
      ) : null}
    </div>
  )
}

function EmployeeEditor({
  employee,
  departments,
  roles,
  onClose,
  onSaved,
}: {
  employee: Employee | null
  departments: Department[]
  roles: GlobalRole[]
  onClose: () => void
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const nameRef = useRef<HTMLInputElement>(null)
  const initialRole: GlobalRole = employee?.role === 'admin' ? 'admin' : (employee?.global_role ?? 'viewer')
  const [name, setName] = useState(employee?.name ?? '')
  const [email, setEmail] = useState(employee?.email ?? '')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<GlobalRole>(initialRole)
  const [departmentIds, setDepartmentIds] = useState<string[]>(employee?.department_ids ?? [])
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState('')
  const isEdit = employee !== null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (pending) return
    setPending(true)
    setServerError('')
    const input = {
      name: name.trim(),
      email: email.trim(),
      ...(password ? { password } : {}),
      role: role === 'admin' ? 'admin' as const : 'employee' as const,
      global_role: role,
      department_ids: departmentIds,
    }
    try {
      if (employee) await updateEmployee(employee.id, input)
      else await createEmployee(input)
      onSaved()
    } catch (nextError) {
      setServerError(nextError instanceof Error ? nextError.message : String(nextError))
    } finally {
      setPending(false)
    }
  }

  return (
    <AdminDialog
      titleId="employee-editor-title"
      descriptionId="employee-editor-description"
      title={isEdit ? t('employees.editor.editTitle') : t('employees.editor.inviteTitle')}
      description={t('employees.editor.description')}
      pending={pending}
      initialFocusRef={nameRef}
      onClose={onClose}
    >
      <form className="mt-5 space-y-4" onSubmit={submit}>
        <div>
          <label htmlFor="employee-name" className="bp-label">{t('employees.editor.name')}</label>
          <input id="employee-name" ref={nameRef} value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} autoComplete="name" className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary" />
        </div>
        <div>
          <label htmlFor="employee-email" className="bp-label">{t('employees.editor.email')}</label>
          <input id="employee-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required maxLength={200} autoComplete="email" inputMode="email" className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary" />
        </div>
        <div>
          <label htmlFor="employee-password" className="bp-label">
            {isEdit ? t('employees.editor.passwordOptional') : t('employees.editor.password')}
          </label>
          <input id="employee-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required={!isEdit} minLength={8} autoComplete="new-password" className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary" />
          <p className="mt-1.5 font-mono text-[10px] text-faint">{t('employees.editor.passwordHint')}</p>
        </div>
        <div>
          <label htmlFor="employee-role" className="bp-label">{t('employees.editor.role')}</label>
          <select id="employee-role" value={role} onChange={(event) => setRole(event.target.value as GlobalRole)} className="mt-1.5 min-h-11 w-full border border-input bg-background px-3 font-mono text-sm outline-none focus:border-primary">
            {roles.map((roleId) => <option key={roleId} value={roleId}>{t(`roles.name.${roleId}`)}</option>)}
          </select>
          <p className="mt-1.5 font-mono text-[10px] text-faint">{t(`roles.description.${role}`)}</p>
        </div>
        <fieldset>
          <legend className="bp-label">{t('employees.editor.departments')}</legend>
          <p className="mt-1.5 font-mono text-[10px] text-faint">{t('employees.editor.departmentsHint')}</p>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {departments.map((department) => (
              <label key={department.id} className="flex min-h-11 cursor-pointer items-center gap-2 border border-border bg-card px-3 font-mono text-xs hover:bg-muted">
                <input
                  type="checkbox"
                  checked={departmentIds.includes(department.id)}
                  onChange={(event) => setDepartmentIds((current) => event.target.checked ? [...current, department.id] : current.filter((id) => id !== department.id))}
                />
                <span>{department.name}</span>
              </label>
            ))}
          </div>
        </fieldset>
        {serverError ? <div role="alert" className="border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-[11px] text-destructive">{serverError}</div> : null}
        <div className="flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-end">
          <Button type="button" variant="ghost" disabled={pending} className="min-h-11" onClick={onClose}>{t('employees.editor.cancel')}</Button>
          <Button type="submit" disabled={pending} className="min-h-11">{pending ? t('employees.editor.saving') : isEdit ? t('employees.editor.save') : t('employees.editor.sendInvite')}</Button>
        </div>
      </form>
    </AdminDialog>
  )
}

function ToggleEmployeeDialog({ employee, onClose, onSaved }: { employee: Employee; onClose: () => void; onSaved: (isActive: boolean) => void }) {
  const { t } = useTranslation()
  const [pending, setPending] = useState(false)
  const [serverError, setServerError] = useState('')
  const nextActive = !employee.is_active

  const execute = async () => {
    setPending(true)
    setServerError('')
    try {
      const result = await toggleEmployee(employee.id)
      onSaved(result.is_active)
    } catch (nextError) {
      setServerError(nextError instanceof Error ? nextError.message : String(nextError))
      setPending(false)
    }
  }

  return (
    <AdminDialog
      titleId="employee-toggle-title"
      descriptionId="employee-toggle-description"
      title={nextActive ? t('employees.toggle.activateTitle') : t('employees.toggle.deactivateTitle')}
      description={t('employees.toggle.description', { name: employee.name })}
      pending={pending}
      onClose={onClose}
    >
      {serverError ? <div role="alert" className="mt-4 border border-destructive/40 bg-destructive/10 px-3 py-2 font-mono text-[11px] text-destructive">{serverError}</div> : null}
      <div className="mt-5 flex flex-col-reverse gap-2 border-t border-border pt-4 sm:flex-row sm:justify-end">
        <Button type="button" variant="ghost" disabled={pending} className="min-h-11" onClick={onClose}>{t('employees.toggle.cancel')}</Button>
        <Button type="button" disabled={pending} className="min-h-11" onClick={execute}>
          {pending ? t('employees.toggle.saving') : nextActive ? t('employees.activate') : t('employees.deactivate')}
        </Button>
      </div>
    </AdminDialog>
  )
}
