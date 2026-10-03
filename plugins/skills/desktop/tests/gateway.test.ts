import { describe, expect, it } from 'vitest'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL as NodeURL } from 'node:url'
import { createSkillsGateway, SKILLS_WIRE_METHODS, type WireCaller } from '../src/gateway'
import { sha256Hex } from '../src/sha256'
import { fakeSkillsGateway } from './fakes'

const asset = { assetId: 'demo', name: 'demo', description: 'description', latestRevision: 2, digest: 'sha256:x', source: 'local:import' }
const row = { serverScope: 'server', principal: 'user', scopeKind: 'user_global', scopeId: '', harnessId: null, assetId: 'demo', decision: 'enable', revision: 1, rowVersion: 3 }
const target = { projectId: null, harnessId: null, profileId: null }
const layer = { kind: 'user-global' as const, scopeId: null, harnessId: null }
const options = { assetId: null, originScope: 'public' as const, originOwner: null, operationKey: 'op', expectedVersion: 0 }
const preview = { name: 'new-skill', description: 'd', metadata: {}, files: [{ path: 'SKILL.md', bytes: 2 }], scripts: [], treeDigest: 'sha256:x' }
function spyWire(responder: (method: string, params: Record<string, unknown>) => unknown = envelope) {
  const sent: { method: string; params: Record<string, unknown> }[] = []
  const wire: WireCaller = { async call(method, params) {
    // Every real descriptor requires requestId. Test it on each send, then
    // inspect the domain params independently of a nondeterministic UUID.
    expect(params.requestId).toEqual(expect.any(String))
    const { requestId: _requestId, ...domainParams } = params
    sent.push({ method, params: domainParams })
    return responder(method, params)
  } }
  return { wire, sent }
}
function envelope(method: string): unknown {
  switch (method) {
    case 'skills.list': return { items: [asset], nextCursor: null }
    case 'skills.get': return asset
    case 'skills.revisions': return { assetId: 'demo', items: [
      { revision: 1, treeDigest: 'sha256:old', approvalRecord: { approvedAt: 'now', approvedBy: 'user' } },
      { revision: 2, treeDigest: 'sha256:x', approvalRecord: null },
    ] }
    case 'skills.preview': return { path: 'scripts/run.sh', text: 'secret script body', script: true, bytes: 18 }
    case 'skills.diff': return { assetId: 'demo', fromRevision: 1, toRevision: 2, added: ['new.md'], removed: [], changed: ['SKILL.md'] }
    case 'skills.importBegin': return { importId: 'import_1', effect: 'stored' }
    case 'skills.importChunk': return { importId: 'import_1', receivedBytes: 2 }
    case 'skills.importPreview': return preview
    case 'skills.importCommit': return { asset: { ...asset, assetId: 'new-skill', latestRevision: 1 }, effect: 'stored' }
    case 'skills.importCancel': return { importId: 'import_1', cancelled: true }
    case 'skills.approveRevision': return { approval: { revision: 2 }, effect: 'stored' }
    case 'skills.assignmentsList': return { items: [row, { ...row, harnessId: 'pi' }] }
    case 'skills.assignmentsUpsert': return { assignment: { ...row, rowVersion: 4 }, effect: 'stored' }
    case 'skills.assignmentsRemove': return { removed: { removed: true, previousRowVersion: 3 }, effect: 'stored' }
    case 'skills.resolve': case 'skills.previewEffective': return {
      target, serverScope: 'server', assignmentRevisions: { row: 3 }, diagnostics: [{ kind: 'policy_unknown', note: 'policy unavailable' }],
      resolvedSkills: [{ assetId: 'demo', nativeName: 'demo', revision: 1, treeDigest: 'sha256:old', originScope: 'public', selectedBy: { layer: 'user_global_any' }, capabilityEvidence: { effect: 'selected' } }],
      excludedSkills: [{ assetId: 'disabled', excludedBy: { layer: 'project_any', scopeId: 'project' } }, { assetId: 'inherited', excludedBy: null }],
    }
    case 'skills.invokeDescriptor': return { invocation: 'unknown', browseOnly: true }
    case 'skills.discoverNative': throw Error('NATIVE_TARGET_ROOT_UNAVAILABLE')
    default: throw Error(`unpublished method: ${method}`)
  }
}

describe('skills wire gateway: actual backend contract', () => {
  it('matches the backend method descriptor table, rather than a second invented list', () => {
    const backend = readFileSync(fileURLToPath(new NodeURL('../../src/ordessa_skills/wire.py', import.meta.url)), 'utf8')
    const table = [...backend.matchAll(/row\("(skills\.[^"]+)"/g)].map(match => match[1])
    expect([...SKILLS_WIRE_METHODS]).toEqual(table)
  })
  it('normalizes bare asset/revision DTOs and derives approval only from approval records', async () => {
    const { wire, sent } = spyWire()
    const gateway = createSkillsGateway(wire)
    expect((await gateway.catalogue())[0]).toMatchObject({ nativeName: 'demo', latestInstalledRevision: 2, approvedRevision: 1, updateCandidateRevision: 2 })
    expect((await gateway.get('demo')).nativeName).toBe('demo')
    expect((await gateway.revisions('demo')).map(item => item.approved)).toEqual([true, false])
    expect(sent[0]).toEqual({ method: 'skills.list', params: {} })
    expect(await gateway.diff('demo', 1, 2)).toMatchObject({ changed: ['SKILL.md'], hunks: [] })
  })
  it('uses source ownership for target selection without sending nonexistent target params to skills.list', async () => {
    const { wire, sent } = spyWire(method => method === 'skills.list'
      ? { items: [asset, { ...asset, assetId: 'private', source: 'project:other|local:import' }] } : envelope(method))
    expect((await createSkillsGateway(wire).list({ projectId: 'project', harnessId: 'pi' })).map(item => item.assetId)).toEqual(['demo'])
    expect(sent[0].params).toEqual({})
  })
  it('sends flat assignment params and retains each row CAS token; any-harness reads exclude brand rows', async () => {
    const { wire, sent } = spyWire()
    const gateway = createSkillsGateway(wire)
    expect((await gateway.assignmentsList({ layer })).rows).toHaveLength(1)
    const draft = { assetId: 'demo', layer, decision: 'enable' as const, revision: 1 }
    expect(await gateway.assignmentsUpsert(draft, { expectedVersion: 3, operationKey: 'op' })).toMatchObject({ kind: 'applied', assignmentRevision: 4 })
    expect(sent[1]).toEqual({ method: 'skills.assignmentsUpsert', params: { scopeKind: 'user_global', scopeId: null, harnessId: null, assetId: 'demo', decision: 'enable', revision: 1, expectedVersion: 3, operationKey: 'op' } })
    await gateway.assignmentsRemove('demo', layer, { expectedVersion: 3, operationKey: 'remove' })
    expect(sent[2].params).toMatchObject({ assetId: 'demo', scopeKind: 'user_global', expectedVersion: 3 })
  })
  it('carries selected, excluded and absent resolution facts and diagnostics with flat targets', async () => {
    const { wire, sent } = spyWire()
    const gateway = createSkillsGateway(wire)
    const view = await gateway.resolve(target)
    expect(view.resolved[0]).toMatchObject({ evidence: 'selected', proofs: ['assignment_decision'], diagnostics: [{ code: 'policy_unknown', message: 'policy unavailable', assetId: null }] })
    expect(view.resolved[1].excludedBy?.layer).toBe('project')
    expect(view.resolved[2].excludedBy).toBeNull()
    expect(sent[0].params).toEqual(target)
    await gateway.previewEffective(target, [])
    expect(sent[1].method).toBe('skills.previewEffective')
  })
  it('aligns the bounded transfer and commit DTOs and never exposes received script bodies', async () => {
    const { wire, sent } = spyWire()
    const gateway = createSkillsGateway(wire)
    expect(await gateway.importBegin([{ path: 'SKILL.md', bytes: 2, sha256: 'sha256:x' }], 2)).toMatchObject({ importId: 'import_1' })
    await gateway.importChunk('import_1', 0, new Uint8Array([97, 98]), 'sha256:x')
    expect(sent[1].params).toEqual({ importId: 'import_1', chunkIndex: 0, payloadBase64: 'YWI=', sha256: 'sha256:x' })
    await gateway.importPreview('import_1', { type: 'local-transfer', origin: 'desktop:picker' })
    expect(sent[2].params).toEqual({ importId: 'import_1', source: { kind: 'local' } })
    expect(await gateway.importCommit('import_1', options)).toEqual({ assetId: 'new-skill', revision: 1, effect: 'stored', treeDigest: 'sha256:x' })
    expect(sent[3].params).toEqual({ importId: 'import_1', assetId: 'new-skill', revision: 1 })
    await gateway.importCancel('import_1')
    expect(await gateway.preview('demo', 1, 'scripts/run.sh')).toEqual({ path: 'scripts/run.sh', text: null, script: true, truncated: false })
    expect(await gateway.approveRevision('demo', 2, 'op')).toMatchObject({ approvedRevision: 2, kind: 'applied' })
    expect(sent.at(-1)?.params).toEqual({ assetId: 'demo', revision: 2 })
  })
  it('refuses unsupported source mapping, guarded update, private import and layer draft preview without sending fake methods', async () => {
    const { wire, sent } = spyWire()
    const gateway = createSkillsGateway(wire)
    await expect(gateway.sources()).rejects.toThrow('SOURCES_UNAVAILABLE')
    await expect(gateway.checkUpdate('demo')).rejects.toThrow('SOURCE_ID_UNAVAILABLE')
    await expect(gateway.importCommit('import_1', { ...options, originScope: 'project', originOwner: 'project' })).rejects.toThrow('IMPORT_OWNERSHIP_UNAVAILABLE')
    await expect(gateway.importCommit('import_1', { ...options, assetId: 'demo', expectedVersion: 2 })).rejects.toThrow('IMPORT_CAS_UNAVAILABLE')
    await expect(gateway.previewEffective(target, [{ assetId: 'demo', layer, decision: 'inherit', revision: null }])).rejects.toThrow('DRAFT_PREVIEW_UNAVAILABLE')
    expect(sent).toEqual([])
  })
  it('propagates typed failures unchanged and only treats explicit browse-only evidence as no invocation route', async () => {
    const error = { code: 'ASSIGNMENT_VERSION_CONFLICT', message: 'version stale' }
    const failure: WireCaller = { async call() { throw error } }
    await expect(createSkillsGateway(failure).assignmentsUpsert({ assetId: 'demo', layer, decision: 'disable', revision: null }, { expectedVersion: 3, operationKey: 'op' })).rejects.toBe(error)
    const { wire, sent } = spyWire()
    const gateway = createSkillsGateway(wire)
    await expect(gateway.discoverNative({ harnessId: 'pi', runtimeVersion: '1', projectId: null })).rejects.toThrow('NATIVE_TARGET_ROOT_UNAVAILABLE')
    expect(await gateway.invokeDescriptor({ projectId: null, harnessId: 'pi' }, 'demo')).toBeNull()
    expect(sent.at(-1)?.params).toEqual({ harnessId: 'pi' })
    await expect(createSkillsGateway(spyWire(() => ({})).wire).invokeDescriptor({ projectId: null, harnessId: 'pi' }, 'demo')).rejects.toThrow('INVOKE_DESCRIPTOR_UNKNOWN')
    await expect(createSkillsGateway(spyWire(() => null).wire).catalogue()).rejects.toThrow('empty wire response')
    await expect(createSkillsGateway(spyWire(() => ({})).wire).catalogue()).rejects.toThrow('INVALID_WIRE_RESPONSE')
  })
})

describe('import digest declaration', () => {
  it('matches the platform hash across empty, short and padding-boundary vectors', () => {
    for (const input of ['', 'abc', 'a'.repeat(55), 'b'.repeat(64)]) {
      expect(sha256Hex(new TextEncoder().encode(input))).toBe('sha256:' + createHash('sha256').update(input).digest('hex'))
    }
  })
})
describe('fake gateway completeness', () => {
  it('implements every member of the view gateway', () => {
    const { gateway } = fakeSkillsGateway()
    expect(Object.keys(gateway).sort()).toEqual([
      'approveRevision', 'assignmentsList', 'assignmentsRemove', 'assignmentsUpsert', 'catalogue', 'checkUpdate',
      'diff', 'discoverNative', 'get', 'importBegin', 'importCancel', 'importChunk', 'importCommit',
      'importPreview', 'invokeDescriptor', 'list', 'preview', 'previewEffective', 'resolve', 'revisions', 'sources',
    ])
    expect(Object.values(gateway).every(value => typeof value === 'function')).toBe(true)
  })
})
