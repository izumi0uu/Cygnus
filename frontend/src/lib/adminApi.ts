import { authApi } from '@/lib/authApi'

export type GlobalRole = 'viewer' | 'contributor' | 'knowledge_manager' | 'admin'

export interface PermissionCatalogItem {
  key: string
  label: string
  description: string
}

export interface PermissionCatalogGroup {
  id: string
  permissions: PermissionCatalogItem[]
}

export interface FixedRoleCatalogItem {
  id: GlobalRole
  permissions: string[]
}

export interface RoleCatalog {
  roles: FixedRoleCatalogItem[]
  groups: PermissionCatalogGroup[]
}

export interface Department {
  id: string
  name: string
  description: string | null
  employee_count: number
}

export interface Employee {
  id: string
  name: string
  email: string
  role: 'admin' | 'employee'
  global_role: GlobalRole
  department_ids: string[]
  department_names: string[]
  is_active: boolean
  has_token: boolean
  last_connected: string | null
}

export interface EmployeePage {
  items: Employee[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface EmployeeInput {
  name: string
  email: string
  password?: string
  role: 'admin' | 'employee'
  global_role: GlobalRole
  department_ids: string[]
}

export async function fetchRoleCatalog(): Promise<RoleCatalog> {
  return authApi<RoleCatalog>('/api/roles/catalog')
}

export async function fetchDepartments(): Promise<Department[]> {
  return authApi<Department[]>('/api/departments')
}

export async function fetchEmployees({
  search,
  page = 1,
  pageSize = 20,
}: {
  search?: string
  page?: number
  pageSize?: number
} = {}): Promise<EmployeePage> {
  const params = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
  if (search?.trim()) params.set('search', search.trim())
  return authApi<EmployeePage>(`/api/employees?${params.toString()}`)
}

export async function createEmployee(input: EmployeeInput): Promise<{ id: string; name: string; email: string }> {
  return authApi('/api/employees', { method: 'POST', body: input })
}

export async function updateEmployee(employeeId: string, input: EmployeeInput): Promise<{ id: string; name: string }> {
  return authApi(`/api/employees/${encodeURIComponent(employeeId)}`, { method: 'PUT', body: input })
}

export async function toggleEmployee(employeeId: string): Promise<{ id: string; is_active: boolean }> {
  return authApi(`/api/employees/${encodeURIComponent(employeeId)}/toggle`, { method: 'PATCH' })
}

export interface ModelSpec {
  id: string
  provider: string
  model_id: string
  label: string
  notes: string | null
  api_key_configured: boolean
  context_window_tokens?: number
  max_output_tokens?: number
  supports_tools?: boolean
  supports_vision?: boolean
  cost_per_1m_input_tokens?: number | null
  cost_per_1m_output_tokens?: number | null
  max_image_size_mb?: number
  cost_per_image?: number | null
  dimension?: number
  cost_per_1m_tokens?: number | null
}

export interface ModelCatalog {
  active_spec_id: string | null
  specs: ModelSpec[]
}

export interface LLMCatalog extends ModelCatalog {
  active_mode: 'catalog' | 'custom'
  custom: {
    enabled: boolean
    provider: string
    model_id: string
    base_url: string
    api_key_configured: boolean
    context_window_tokens: number
    max_output_tokens: number
    reasoning_effort: string | null
    has_any_value: boolean
  }
}

export async function fetchModelCatalog(capability: 'embedding' | 'llm' | 'vision'): Promise<ModelCatalog | LLMCatalog> {
  const segment = capability === 'embedding' ? 'embeddings' : capability
  return authApi<ModelCatalog | LLMCatalog>(`/api/settings/${segment}/catalog`)
}

export async function saveModelApiKey(configKey: string, apiKey: string): Promise<void> {
  await authApi('/api/settings', {
    method: 'PUT',
    body: { settings: { [configKey]: apiKey } },
  })
}

export async function switchModel(
  capability: 'embedding' | 'llm' | 'vision',
  modelSpecId: string,
): Promise<{ active_spec_id?: string; job_id?: string }> {
  const segment = capability === 'embedding' ? 'embeddings' : capability
  return authApi(`/api/settings/${segment}/switch`, {
    method: 'POST',
    body: { model_spec_id: modelSpecId },
  })
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<{ message: string }> {
  return authApi('/api/auth/change-password', {
    method: 'POST',
    body: { current_password: currentPassword, new_password: newPassword },
  })
}

export function modelApiKeyConfigKey(capability: 'embedding' | 'llm' | 'vision', provider: string): string {
  if (capability === 'embedding') return `embedding_api_key__${provider}`
  return `${capability}_api_key`
}
