import { describe, expect, it } from 'vitest'
import { isSystemAdmin } from '../src/lib/adminRoutes'

describe('admin route authorization', () => {
  it('admits only the system-admin role used by backend mutation guards', () => {
    expect(isSystemAdmin({ role: 'admin' })).toBe(true)
    expect(isSystemAdmin({ role: 'employee' })).toBe(false)
    expect(isSystemAdmin(null)).toBe(false)
  })
})
