import { expect, it, vi } from 'vitest'
import type { WirePort, WireResult } from '@extensions/ordessa.contracts/contract.js'
import {
  AGENT_PROFILE_CATALOG_CONTRACT_VERSION,
  profileSchemaMirror,
  type AgentProfileCatalogCapabilities,
  type AgentProfileCatalogEntry,
  type ProfileRef,
} from '@extensions/ordessa.profile-api/contract.js'
import { createWireClient } from '../src/wire-client'

const namespace = 'local'
const ref: ProfileRef = {
  environmentNamespace: namespace,
  profileId: 'profile-a',
  manifestRevision: 3,
  contentDigest: `sha256:${'a'.repeat(64)}`,
}
const entry: AgentProfileCatalogEntry = {
  profileId: ref.profileId,
  catalogRevision: 5,
  displayName: 'Profile A',
  archivedAt: null,
  currentManifestRef: ref,
}

function capabilities(overrides: Record<string, unknown> = {}): AgentProfileCatalogCapabilities {
  if (!profileSchemaMirror) throw new Error('generated Agent schema mirror is unavailable')
  return {
    contractVersion: AGENT_PROFILE_CATALOG_CONTRACT_VERSION,
    schemaDigest: profileSchemaMirror.schemaDigest,
    schema: profileSchemaMirror.schema,
    environmentNamespace: namespace,
    supports: { profileCatalog: true },
    supportedMethods: ['agents.profiles.capabilities', 'agents.profiles.list', 'agents.profiles.readEntry', 'agents.profiles.read'],
    ...overrides,
  } as AgentProfileCatalogCapabilities
}

function accepted(result: unknown): WireResult {
  return { kind: 'Accepted', requestId: 'request-1', result: result as Record<string, unknown> }
}

function makeWire(handler: (method: string, params: Readonly<Record<string, unknown>>) => Promise<WireResult> | WireResult,
                 state: { ready?: boolean; scope?: string | null } = {}) {
  const call = vi.fn(async (method: string, params: Readonly<Record<string, unknown>>): Promise<WireResult> => {
    expect(method).toBe('operations.call')
    expect(Object.keys(params).sort()).toEqual(['input', 'operationId'])
    const answer = await handler(String(params.operationId), params.input as Readonly<Record<string, unknown>>)
    if (answer.kind !== 'Accepted') return answer
    return accepted({ apiVersion: 'agent-tools/1', requestId: 'request-1', command: params.operationId,
      status: 'completed', data: answer.result, error: null, operationRef: null, evidenceRefs: [] })
  })
  const wire = { ready: state.ready ?? true, scope: state.scope === undefined ? 'server-1' : state.scope, call } as unknown as WirePort
  return { wire, call }
}

it('requires exact contract version, digest, schema, support=true and all read methods before querying data', async () => {
  const variants: Array<[string, Record<string, unknown>]> = [
    ['version', { contractVersion: 'agent-assembly/2' }],
    ['digest', { schemaDigest: 'sha256:bad' }],
    ['schema', { schema: { contractVersion: 'profile-json/1' } }],
    ['support', { supports: { profileCatalog: false } }],
    ['methods', { supportedMethods: ['agents.profiles.capabilities'] }],
    ['malformed support facts', { supportedMethods: ['agents.profiles.capabilities', 1] }],
    ['namespace', { environmentNamespace: '' }],
  ]
  for (const [name, override] of variants) {
    const { wire, call } = makeWire(method => method === 'agents.profiles.capabilities'
      ? accepted(capabilities(override)) : accepted({ entries: [] }))
    const result = await createWireClient(wire).list()
    expect(result.kind, name).toBe('unavailable')
    expect(call.mock.calls.map(([, params]) => params.operationId)).toEqual(['agents.profiles.capabilities'])
  }
  const absent = makeWire(() => accepted(capabilities()))
  expect((await createWireClient(absent.wire, null).list()).kind).toBe('unavailable')
  expect(absent.call).not.toHaveBeenCalled()
})

it('distinguishes an empty catalog from an unavailable port and preserves refused/unknown outcomes', async () => {
  const empty = makeWire(method => method === 'agents.profiles.capabilities'
    ? accepted(capabilities()) : accepted({ entries: [] }))
  expect(await createWireClient(empty.wire).list()).toEqual({ kind: 'ok', value: [] })

  const absent = makeWire(() => accepted(capabilities()), { ready: false, scope: null })
  expect((await createWireClient(absent.wire).list()).kind).toBe('unavailable')
  expect(absent.call).not.toHaveBeenCalled()

  for (const [kind, response] of [
    ['refused', { kind: 'Refused', requestId: 'r', reason: 'policy', retryable: false }],
    ['unknown', { kind: 'Unknown', requestId: 'r', reason: 'transport lost' }],
  ] as const) {
    const { wire } = makeWire(method => method === 'agents.profiles.capabilities'
      ? accepted(capabilities()) : response)
    expect((await createWireClient(wire).list()).kind).toBe(kind)
  }
})

it('reads only exact ProfileRefs, validates returned manifest identity, and calls no write or legacy method', async () => {
  const methods: string[] = []
  const { wire, call } = makeWire((method, params) => {
    methods.push(method)
    if (method === 'agents.profiles.capabilities') return accepted(capabilities())
    if (method === 'agents.profiles.list') return accepted({ entries: [entry] })
    if (method === 'agents.profiles.readEntry') return accepted(entry)
    if (method === 'agents.profiles.read') return accepted({ ref: params.profileRef, content: { model: 'm' } })
    throw new Error(`unexpected method ${method}`)
  })
  expect(await createWireClient(wire).list()).toEqual({ kind: 'ok', value: [entry] })
  expect(await createWireClient(wire).readEntry(entry.profileId)).toEqual({ kind: 'ok', value: entry })
  expect(await createWireClient(wire).read(ref)).toEqual({ kind: 'ok', value: { ref, content: { model: 'm' } } })
  const readCall = call.mock.calls.find(([, params]) => params.operationId === 'agents.profiles.read')
  expect(readCall?.[1]).toEqual({ operationId: 'agents.profiles.read', input: { profileRef: ref } })
  expect(methods.every(method => ['agents.profiles.capabilities', 'agents.profiles.list', 'agents.profiles.readEntry', 'agents.profiles.read'].includes(method))).toBe(true)
  expect(methods).not.toContain('profiles.v2.read')
  expect(methods).not.toContain('agent.config.submitOperation')

  const foreignRead = makeWire(method => method === 'agents.profiles.capabilities' ? accepted(capabilities())
    : accepted({ ref: { ...ref, environmentNamespace: 'other' }, content: { model: 'foreign' } }))
  expect((await createWireClient(foreignRead.wire).read({ ...ref, environmentNamespace: 'other' })).kind).toBe('unknown')
  expect(foreignRead.call.mock.calls.map(([, params]) => params.operationId)).toEqual(['agents.profiles.capabilities'])
  const mismatched = makeWire(method => method === 'agents.profiles.capabilities' ? accepted(capabilities())
    : accepted({ ref: { ...ref, manifestRevision: 4 }, content: { secret: 'must-not-display' } }))
  expect((await createWireClient(mismatched.wire).read(ref)).kind).toBe('unknown')
})

it('rejects malformed and cross-namespace catalog entries instead of presenting them', async () => {
  const malformed = makeWire(method => method === 'agents.profiles.capabilities' ? accepted(capabilities())
    : accepted({ entries: [{ ...entry, currentManifestRef: { ...ref, environmentNamespace: 'foreign' } }] }))
  expect((await createWireClient(malformed.wire).list()).kind).toBe('unknown')

  const malformedShape = makeWire(method => method === 'agents.profiles.capabilities' ? accepted(capabilities())
    : accepted({ entries: [{ ...entry, unexpected: true }] }))
  expect((await createWireClient(malformedShape.wire).list()).kind).toBe('unknown')
})
