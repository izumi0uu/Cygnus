import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  applyPublishAction,
  type DurablePublishCommandEnvelope,
} from './api'

function installTransportMock() {
  const fetchMock = vi.fn(
    async (...args: [RequestInfo | URL, RequestInit?]): Promise<Response> => {
      void args
      return new Response('{}', {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    },
  )
  vi.stubGlobal('localStorage', {
    getItem: vi.fn(() => 'test-token'),
    setItem: vi.fn(),
    removeItem: vi.fn(),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('applyPublishAction', () => {
  it('forwards the complete server-qualified durable command verbatim', async () => {
    const fetchMock = installTransportMock()
    const command: DurablePublishCommandEnvelope = {
      draft_id: 'f6c4fb2f-0c55-4ef4-aab8-0a6095fb516f',
      approval_ref: '03fd38de-9d92-4a38-981d-1520a07a4cb3',
      approval_digest: 'a'.repeat(64),
      scope_digest: 'b'.repeat(64),
      signal_id: '431781d0-3027-4f5e-95c9-726c71962ce1',
      signal_freshness: 'fresh',
      command_id: 'publish-preview:guarded-command',
      action_key: 'republish',
      target_channels: ['agent-copilot', 'internal-search'],
      expected_version: 7,
      reason: 'Verified governed republish.',
    }

    await applyPublishAction(undefined, command.action_key, command)

    expect(fetchMock).toHaveBeenCalledOnce()
    const [path, request] = fetchMock.mock.calls[0]
    expect(path).toBe('/api/publish/apply')
    expect(request?.method).toBe('POST')
    expect(JSON.parse(String(request?.body))).toEqual(command)
  })

  it('keeps the explicit rehearsal path free of durable guard fields', async () => {
    const fetchMock = installTransportMock()

    await applyPublishAction('ko-rehearsal', 'restrict_publish')

    const [, request] = fetchMock.mock.calls[0]
    expect(JSON.parse(String(request?.body))).toEqual({
      object_ref: 'ko-rehearsal',
      action_key: 'restrict_publish',
    })
  })
})
