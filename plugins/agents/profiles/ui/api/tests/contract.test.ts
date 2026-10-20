import { expect, it } from 'vitest'
import * as api from '../src/index'

it('exports the versioned read-only Agent catalog contract without a legacy Profile service token', () => {
  expect(api.AGENT_PROFILE_CATALOG_CONTRACT_VERSION).toBe('profile-json/1')
  expect(api.AgentProfileCatalogToken.name).toBe('ordessa.agent-profile-catalog.v1')
  expect(api).not.toHaveProperty('ProfileServiceToken')
  expect(api).not.toHaveProperty('createProfileService')
  expect(api.profileSchemaMirror?.contractVersion).toBe('profile-json/1')
  expect(api.profileSchemaMirror?.schemaDigest).toMatch(/^sha256:[0-9a-f]{64}$/)
})
