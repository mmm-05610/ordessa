import type {
  AgentProfileCatalogClient,
  AgentProfileCatalogCapabilities,
  AgentProfileCatalogEntry,
  AgentProfileCatalogOutcome,
  AgentProfileManifest,
  ProfileRef,
} from './contract'

export type {
  AgentProfileCatalogClient,
  AgentProfileCatalogCapabilities,
  AgentProfileCatalogEntry,
  AgentProfileCatalogOutcome,
  AgentProfileManifest,
  ProfileRef,
}

/** New semantic token: old ProfileServiceClient consumers cannot bind to it. */
export type AgentProfileCatalogApi = AgentProfileCatalogClient
export type AgentProfileCatalogStatus = AgentProfileCatalogOutcome<AgentProfileCatalogCapabilities>
export type AgentProfileListResult = AgentProfileCatalogOutcome<readonly AgentProfileCatalogEntry[]>
export type AgentProfileReadResult = AgentProfileCatalogOutcome<AgentProfileManifest>
