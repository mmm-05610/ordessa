import type { WirePort } from '@extensions/ordessa.contracts/contract.js'
import {
  AGENT_PROFILE_CATALOG_CONTRACT_VERSION,
  profileSchemaMirror,
  type AgentProfileCatalogCapabilities,
  type AgentProfileCatalogClient,
  type AgentProfileCatalogEntry,
  type AgentProfileCatalogOutcome,
  type AgentProfileManifest,
  type AgentProfileCatalogSchemaMirror,
  type ProfileRef,
} from '@extensions/ordessa.profile-api/contract.js'

type JsonObject = Readonly<Record<string, unknown>>
type CoreResult<T> = AgentProfileCatalogOutcome<T>

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isJsonValue(value: unknown): boolean {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return true
  if (typeof value === 'number') return Number.isFinite(value)
  if (Array.isArray(value)) return value.every(isJsonValue)
  return isRecord(value) && Object.values(value).every(isJsonValue)
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value) ?? 'undefined'
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`
  const record = value as Record<string, unknown>
  return `{${Object.keys(record).sort().map(key => `${JSON.stringify(key)}:${canonical(record[key])}`).join(',')}}`
}

function sameRef(left: ProfileRef, right: ProfileRef): boolean {
  return left.environmentNamespace === right.environmentNamespace
    && left.profileId === right.profileId
    && left.manifestRevision === right.manifestRevision
    && left.contentDigest === right.contentDigest
}

function parseRef(value: unknown): ProfileRef | null {
  if (!isRecord(value) || Object.keys(value).sort().join(',') !==
      'contentDigest,environmentNamespace,manifestRevision,profileId') return null
  if (typeof value.environmentNamespace !== 'string' || !value.environmentNamespace
      || typeof value.profileId !== 'string' || !value.profileId
      || !Number.isSafeInteger(value.manifestRevision) || (value.manifestRevision as number) < 1
      || typeof value.contentDigest !== 'string' || !/^sha256:[0-9a-f]{64}$/.test(value.contentDigest)) return null
  return {
    environmentNamespace: value.environmentNamespace,
    profileId: value.profileId,
    manifestRevision: value.manifestRevision as number,
    contentDigest: value.contentDigest,
  }
}

function parseEntry(value: unknown, environmentNamespace: string): AgentProfileCatalogEntry | null {
  if (!isRecord(value) || Object.keys(value).sort().join(',') !==
      'archivedAt,catalogRevision,currentManifestRef,displayName,profileId') return null
  const ref = parseRef(value.currentManifestRef)
  if (!ref || ref.environmentNamespace !== environmentNamespace
      || typeof value.profileId !== 'string' || !value.profileId
      || !Number.isSafeInteger(value.catalogRevision) || (value.catalogRevision as number) < 1
      || typeof value.displayName !== 'string'
      || !(value.archivedAt === null || typeof value.archivedAt === 'string')) return null
  return {
    profileId: value.profileId,
    catalogRevision: value.catalogRevision as number,
    displayName: value.displayName,
    archivedAt: value.archivedAt,
    currentManifestRef: ref,
  }
}

function parseManifest(value: unknown, requested: ProfileRef): AgentProfileManifest | null {
  if (!isRecord(value) || Object.keys(value).sort().join(',') !== 'content,ref') return null
  const ref = parseRef(value.ref)
  if (!ref || !sameRef(ref, requested) || !isRecord(value.content)
      || !Object.values(value.content).every(isJsonValue)) return null
  return { ref, content: value.content as AgentProfileManifest['content'] }
}

function unavailable<T>(reason: string): CoreResult<T> {
  return { kind: 'unavailable', reason }
}

function fromWire<T>(answer: Awaited<ReturnType<WirePort['call']>>): CoreResult<T> {
  if (answer.kind === 'Refused') return { kind: 'refused', reason: answer.reason }
  if (answer.kind === 'Unknown') return { kind: 'unknown', reason: answer.reason }
  const envelope = answer.result
  if (!isRecord(envelope) || envelope.apiVersion !== 'agent-tools/1'
      || !['completed', 'refused', 'unknown', 'accepted'].includes(String(envelope.status)))
    return { kind: 'unknown', reason: 'capability envelope was malformed' }
  if (envelope.status === 'refused') return { kind: 'refused', reason: 'Profile capability refused' }
  if (envelope.status !== 'completed') return { kind: 'unknown', reason: 'Profile observation did not complete' }
  if (!isRecord(envelope.data)) return { kind: 'unknown', reason: 'capability data was not an object' }
  return { kind: 'ok', value: envelope.data as T }
}

function mirrorMismatch(capabilities: unknown, mirror: AgentProfileCatalogSchemaMirror): string | null {
  if (!isRecord(capabilities)) return 'capability response was malformed'
  if (capabilities.contractVersion !== AGENT_PROFILE_CATALOG_CONTRACT_VERSION
      || capabilities.contractVersion !== mirror.contractVersion) return 'contract version mismatch'
  if (capabilities.schemaDigest !== mirror.schemaDigest) return 'schema digest mismatch'
  if (!isRecord(capabilities.schema) || canonical(capabilities.schema) !== canonical(mirror.schema))
    return 'core schema differs from the generated local mirror'
  if (typeof capabilities.environmentNamespace !== 'string' || !capabilities.environmentNamespace)
    return 'environment namespace was missing'
  const supportedMethods = capabilities.supportedMethods
  if (!isRecord(capabilities.supports) || !Array.isArray(supportedMethods)
      || !supportedMethods.every(item => typeof item === 'string'))
    return 'capability support facts were malformed'
  const requiredMethods = [
    'profiles.capabilities', 'profiles.list', 'profiles.readEntry', 'profiles.read',
  ]
  if (!requiredMethods.every(method => supportedMethods.includes(method)))
    return 'core did not advertise every required read method'
  if (capabilities.supports.profileCatalog !== true)
    return 'supports.profileCatalog is not true'
  return null
}

/** Read-only Profile consumer through the generic capability transport. */
export function createWireClient(
  wire: WirePort,
  mirror: AgentProfileCatalogSchemaMirror | null = profileSchemaMirror,
): AgentProfileCatalogClient {
  const raw = async (method: string, params: JsonObject) => {
    if (!wire.ready || !wire.scope) return unavailable<unknown>('Server wire is not ready')
    try {
      return fromWire<unknown>(await wire.call('operations.call', { operationId: method, input: params }))
    } catch (cause) {
      return { kind: 'unknown', reason: cause instanceof Error ? cause.message : String(cause) } as const
    }
  }

  const verifiedCapabilities = async (): Promise<CoreResult<AgentProfileCatalogCapabilities>> => {
    if (!mirror) return unavailable('profile-json/1 schema mirror has not been generated')
    const response = await raw('profiles.capabilities', {})
    if (response.kind !== 'ok') return response
    const mismatch = mirrorMismatch(response.value, mirror)
    if (mismatch) return unavailable(mismatch)
    return { kind: 'ok', value: response.value as AgentProfileCatalogCapabilities }
  }

  return {
    capabilities: verifiedCapabilities,
    async list(includeArchived = false) {
      if (typeof includeArchived !== 'boolean') return unavailable('includeArchived must be boolean')
      const gate = await verifiedCapabilities()
      if (gate.kind !== 'ok') return gate
      const result = await raw('profiles.list', { includeArchived })
      if (result.kind !== 'ok') return result
      if (!isRecord(result.value) || Object.keys(result.value).sort().join(',') !== 'entries'
          || !Array.isArray(result.value.entries)) return { kind: 'unknown', reason: 'profile list response was malformed' }
      const entries = result.value.entries.map(entry => parseEntry(entry, gate.value.environmentNamespace))
      if (entries.some(entry => entry === null)) return { kind: 'unknown', reason: 'profile catalog entry was malformed' }
      return { kind: 'ok', value: entries as AgentProfileCatalogEntry[] }
    },
    async readEntry(profileId) {
      if (typeof profileId !== 'string' || !profileId) return unavailable('profileId must be nonempty')
      const gate = await verifiedCapabilities()
      if (gate.kind !== 'ok') return gate
      const result = await raw('profiles.readEntry', { profileId })
      if (result.kind !== 'ok') return result
      const entry = parseEntry(result.value, gate.value.environmentNamespace)
      return entry ? { kind: 'ok', value: entry } : { kind: 'unknown', reason: 'profile entry response was malformed' }
    },
    async read(ref) {
      const parsed = parseRef(ref)
      if (!parsed) return unavailable('ProfileRef was incomplete or malformed')
      const gate = await verifiedCapabilities()
      if (gate.kind !== 'ok') return gate
      if (parsed.environmentNamespace !== gate.value.environmentNamespace) {
        return { kind: 'unknown', reason: 'ProfileRef belongs to another environment namespace' }
      }
      const result = await raw('profiles.read', { profileRef: parsed })
      if (result.kind !== 'ok') return result
      const manifest = parseManifest(result.value, parsed)
      return manifest ? { kind: 'ok', value: manifest } : { kind: 'unknown', reason: 'exact manifest response was malformed' }
    },
  }
}
