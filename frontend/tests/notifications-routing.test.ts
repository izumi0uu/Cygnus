import { describe, expect, it } from 'vitest'
import { routeForRisk } from '../src/lib/notifications'

// CYG-133 exact-target routing contract. The queue's `?risk=` matches a
// priority_stack risk_id exactly; the audience surface consumes `?object_ref=`;
// sources/drift have no selection param yet and route to their base surface.

describe('routeForRisk exact-target routing', () => {
  it('routes queue-owned risks with a known riskId to ?risk=', () => {
    expect(routeForRisk('review_assignment', { riskId: 'review_assignment:signal-7' }).to)
      .toBe('/console/queue?risk=review_assignment%3Asignal-7')
    expect(routeForRisk('review_feedback', { riskId: 'review_feedback:signal-9' }).to)
      .toBe('/console/queue?risk=review_feedback%3Asignal-9')
  })

  it('falls back to the object ref for queue-owned risks when only it is known', () => {
    // Notifications carry the artifact UUID (target_id) but no riskId.
    expect(routeForRisk('review_approved', { objectRef: 'draft-1234' }).to)
      .toBe('/console/queue?risk=draft-1234')
  })

  it('prefers riskId over objectRef for queue-owned risks', () => {
    expect(routeForRisk('ticket_pressure', { riskId: 'risk-1', objectRef: 'draft-1' }).to)
      .toBe('/console/queue?risk=risk-1')
  })

  it('routes audience mismatch to the audience surface with ?object_ref=', () => {
    expect(routeForRisk('audience_mismatch', { objectRef: 'obj-ref-42' }).to)
      .toBe('/console/audience?object_ref=obj-ref-42')
  })

  it('routes sources and drift to their base surface while selection params are unsupported', () => {
    expect(routeForRisk('source_blindness', { objectRef: 'obj-1' }).to).toBe('/console/sources')
    expect(routeForRisk('drift', { objectRef: 'obj-2' }).to).toBe('/console/drift')
  })

  it('emits no query param when no target is available', () => {
    expect(routeForRisk('review_withdrawn').to).toBe('/console/queue')
  })

  it('falls back to the review queue for unknown risk kinds', () => {
    expect(routeForRisk('governance_notification').to).toBe('/console/queue')
    expect(routeForRisk('governance_notification', { objectRef: 'x' }).to).toBe('/console/queue?risk=x')
  })

  it('preserves navKey labels for each surface', () => {
    expect(routeForRisk('source_blindness').navKey).toBe('sources')
    expect(routeForRisk('drift').navKey).toBe('drift')
    expect(routeForRisk('audience_mismatch').navKey).toBe('audience')
    expect(routeForRisk('owner_gap').navKey).toBe('reviewQueue')
  })

  it('encodes ids so the round trip through URLSearchParams matches risk_id exactly', () => {
    const { to } = routeForRisk('review_assignment', { riskId: 'review_assignment:signal:1' })
    const param = new URL('http://cygnus.local' + to).searchParams.get('risk')
    expect(param).toBe('review_assignment:signal:1')
  })
})
