import { Token } from '@ordessa/extension-api'
import type { AgentProfileCatalogClient } from './contract'

/** Only the new, read-only Pacthold catalog client can bind this token. */
export const AgentProfileCatalogToken = new Token<AgentProfileCatalogClient>(
  'ordessa.agent-profile-catalog.v1',
)
