import { describe, expect, it } from 'vitest'
import { auditEventRoute, governedObjectRoute } from '../src/lib/adminRoutes'

describe('admin deep-link routes', () => {
  it('routes a durable audit UUID to the event query consumed by Audit', () => {
    const eventId = '22222222-2222-4222-8222-222222222222'
    expect(auditEventRoute(eventId)).toBe(`/console/audit?event=${eventId}`)
    expect(new URL(`https://cygnus.local${auditEventRoute(eventId)}`).searchParams.get('event'))
      .toBe(eventId)
  })

  it('uses the object query consumed by KnowledgeObjects', () => {
    expect(governedObjectRoute('knowledge:billing/policy'))
      .toBe('/console/objects?object=knowledge%3Abilling%2Fpolicy')
    expect(new URL(`https://cygnus.local${governedObjectRoute('knowledge:billing/policy')}`).searchParams.get('object'))
      .toBe('knowledge:billing/policy')
  })
})
