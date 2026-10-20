/** Read-only vocabulary for the current Profile catalog capability surface. */

export const AGENT_PROFILE_CATALOG_CONTRACT_VERSION = 'profile-json/1' as const

export type JsonValue = null | boolean | number | string | readonly JsonValue[] | { readonly [key: string]: JsonValue }

/** Exact identity of one immutable catalog manifest revision. */
export interface ProfileRef {
  readonly environmentNamespace: string
  readonly profileId: string
  readonly manifestRevision: number
  readonly contentDigest: string
}

/** Core-owned catalog projection; it is not the retired ProfileIdentityDto. */
export interface AgentProfileCatalogEntry {
  readonly profileId: string
  readonly catalogRevision: number
  readonly displayName: string
  readonly archivedAt: string | null
  readonly currentManifestRef: ProfileRef
}

/** Exact manifest returned for the supplied ProfileRef. */
export interface AgentProfileManifest {
  readonly ref: ProfileRef
  readonly content: { readonly [key: string]: JsonValue }
}

export interface AgentProfileCatalogCapabilities {
  readonly contractVersion: string
  readonly schemaDigest: string
  readonly schema: Readonly<Record<string, unknown>>
  readonly environmentNamespace: string
  readonly supports: Readonly<Record<string, unknown>>
  readonly supportedMethods: readonly string[]
}

export type AgentProfileCatalogOutcome<T> =
  | { readonly kind: 'ok'; readonly value: T }
  | { readonly kind: 'unavailable'; readonly reason: string }
  | { readonly kind: 'refused'; readonly reason: string }
  | { readonly kind: 'unknown'; readonly reason: string }

export interface AgentProfileCatalogClient {
  capabilities(): Promise<AgentProfileCatalogOutcome<AgentProfileCatalogCapabilities>>
  list(includeArchived?: boolean): Promise<AgentProfileCatalogOutcome<readonly AgentProfileCatalogEntry[]>>
  readEntry(profileId: string): Promise<AgentProfileCatalogOutcome<AgentProfileCatalogEntry>>
  read(ref: ProfileRef): Promise<AgentProfileCatalogOutcome<AgentProfileManifest>>
}
