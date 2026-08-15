import { describe, expect, it } from 'vitest'
import { modelApiKeyConfigKey } from '../src/lib/adminApi'

describe('model API-key ownership', () => {
  it('keeps embedding credentials provider-scoped', () => {
    expect(modelApiKeyConfigKey('embedding', 'openai')).toBe('embedding_api_key__openai')
    expect(modelApiKeyConfigKey('embedding', 'voyage')).toBe('embedding_api_key__voyage')
  })

  it('uses the capability-owned key for LLM and vision catalogs', () => {
    expect(modelApiKeyConfigKey('llm', 'openai')).toBe('llm_api_key')
    expect(modelApiKeyConfigKey('vision', 'google')).toBe('vision_api_key')
  })
})
