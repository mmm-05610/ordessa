import { describe, expect, it } from 'vitest'
import { createHash } from 'node:crypto'
import { createSkillsGateway, SKILLS_WIRE_METHODS, type WireCaller } from '../src/gateway'
import { sha256Hex } from '../src/sha256'
import { fakeSkillsGateway } from './fakes'

/** Records every wire call and answers with a shaped envelope per method. */
function spyWire(responder: (method: string, params: Record<string, unknown>) => unknown = () => ({})) {
  const sent: { method: string; params: Record<string, unknown> }[] = []
  const wire: WireCaller = {
    async call(method, params) {
      sent.push({ method, params })
      const value = responder(method, params)
      if (value === undefined) throw Error(`unanswered method: ${method}`)
      return value
    },
  }
  return { wire, sent }
}

describe('skills wire gateway', () => {
  it('calls exactly the published skills.* family, one method per gateway call', async () => {
    const { wire, sent } = spyWire(method => envelope(method))
    const gateway = createSkillsGateway(wire)
    await gateway.catalogue()
    await gateway.list({ projectId: null, harnessId: 'pi' })
    await gateway.get('demo')
    await gateway.revisions('demo')
    await gateway.preview('demo', 1, 'SKILL.md')
    await gateway.diff('demo', 1, 2)
    const opened = await gateway.importBegin([{ path: 'SKILL.md', bytes: 2, sha256: 'sha256:x' }], 2)
    await gateway.importChunk(opened.importId, 0, new Uint8Array([1, 2]), 'sha256:x')
    await gateway.importPreview(opened.importId, { type: 'local-transfer', origin: 'desktop:picker' })
    await gateway.importCommit(opened.importId, {
      assetId: null, originScope: 'public', originOwner: null, operationKey: 'op', expectedVersion: 0,
    })
    await gateway.importCancel(opened.importId)
    await gateway.sources()
    await gateway.checkUpdate('demo')
    await gateway.approveRevision('demo', 2, 'op')
    await gateway.assignmentsList({ layer: { kind: 'user-global', scopeId: null, harnessId: null } })
    await gateway.assignmentsUpsert(
      { assetId: 'demo', layer: { kind: 'user-global', scopeId: null, harnessId: null }, decision: 'enable', revision: 1 },
      { expectedVersion: 7, operationKey: 'op' },
    )
    await gateway.assignmentsRemove('demo', { kind: 'user-global', scopeId: null, harnessId: null }, { expectedVersion: 7, operationKey: 'op' })
    await gateway.resolve({ projectId: null, harnessId: null })
    await gateway.previewEffective({ projectId: null, harnessId: null }, [])
    await gateway.discoverNative({ harnessId: 'pi', runtimeVersion: '1', projectId: null })
    await gateway.invokeDescriptor({ projectId: null, harnessId: null }, 'demo')

    expect(sent.map(call => call.method)).toEqual([...SKILLS_WIRE_METHODS])
    // The closed set is the contract: no call left the family, and every family
    // member is reachable from the gateway.
    expect(sent.every(call => (SKILLS_WIRE_METHODS as readonly string[]).includes(call.method))).toBe(true)
  })

  it('never speaks the legacy assets.* vocabulary, including the unwired facet call', async () => {
    const { wire, sent } = spyWire(method => envelope(method))
    const gateway = createSkillsGateway(wire)
    await gateway.catalogue()
    await gateway.assignmentsList({ layer: { kind: 'project', scopeId: 'ordessa', harnessId: 'pi' } })
    await gateway.resolve({ projectId: 'ordessa', harnessId: 'pi' })
    expect(sent.map(call => call.method).filter(method => method.startsWith('assets.'))).toEqual([])
    // The defect this replaces: the legacy adapter called `assets.profileFacets`,
    // which no backend published, and rendered a profile surface from nothing.
    expect(sent.map(call => call.method)).not.toContain('assets.profileFacets')
    // Project identity travels as the authoritative Workspace id only.
    expect(sent[1].params).toEqual({ layer: { kind: 'project', scopeId: 'ordessa', harnessId: 'pi' } })
  })

  it('an empty wire answer is a refusal, not an empty list', async () => {
    const { wire } = spyWire(() => null)
    await expect(createSkillsGateway(wire).catalogue()).rejects.toThrow('empty wire response')
  })

  it('ships bytes as base64 and only ever reads back a bounded preview', async () => {
    const { wire, sent } = spyWire(method => method === 'skills.preview'
      ? { preview: { path: 'scripts/run.sh', text: null, script: true, truncated: false } }
      : {})
    const gateway = createSkillsGateway(wire)
    await gateway.importChunk('import_1', 0, new Uint8Array([0x61, 0x62, 0x63]), 'sha256:y')
    expect(sent[0].params.payload).toBe('YWJj')
    const preview = await gateway.preview('demo', 1, 'scripts/run.sh')
    // A script body never crosses the wire, so no view can render it.
    expect(preview).toEqual({ path: 'scripts/run.sh', text: null, script: true, truncated: false })
  })

  it('a missing invoke descriptor is browse-only, not an error and not a fake route', async () => {
    const { wire } = spyWire(() => ({}))
    expect(await createSkillsGateway(wire).invokeDescriptor({ projectId: null, harnessId: null }, 'demo')).toBeNull()
  })
})

describe('import digest declaration', () => {
  it('matches the platform hash for the vectors a drift check compares', () => {
    const encode = (text: string) => new TextEncoder().encode(text)
    expect(sha256Hex(encode(''))).toBe('sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
    expect(sha256Hex(encode('abc'))).toBe('sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad')
    // A 55-byte message ends exactly at the length field boundary; 64 needs a
    // whole extra block. Both are where an off-by-one padding shows up.
    expect(sha256Hex(encode('a'.repeat(55)))).toBe('sha256:' + platformDigest('a'.repeat(55)))
    expect(sha256Hex(encode('b'.repeat(64)))).toBe('sha256:' + platformDigest('b'.repeat(64)))
  })
})

function platformDigest(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

/** The envelope each published method answers with. */
function envelope(method: string): unknown {
  switch (method) {
    case 'skills.catalogue': case 'skills.list': return { skills: [] }
    case 'skills.get': return { skill: {} }
    case 'skills.revisions': return { revisions: [] }
    case 'skills.preview': return { preview: { path: 'SKILL.md', text: '', script: false, truncated: false } }
    case 'skills.diff': return { diff: { assetId: 'demo', fromRevision: 1, toRevision: 2, added: [], removed: [], changed: [], hunks: [] } }
    case 'skills.import.begin': return { import: { importId: 'import_1' } }
    case 'skills.import.chunk': case 'skills.import.cancel': return {}
    case 'skills.import.preview': return { preview: { name: 'demo', description: '', metadata: {}, files: [], scripts: [], treeDigest: 'sha256:x', warnings: [] } }
    case 'skills.import.commit': return { commit: { effect: 'stored', assetId: 'demo', revision: 2, treeDigest: 'sha256:x' } }
    case 'skills.sources': return { sources: [] }
    case 'skills.checkUpdate': return { source: { assetId: 'demo', kind: 'git', reference: 'x', lastChecked: null, candidateRevision: null, archived: false } }
    case 'skills.approveRevision': return { kind: 'applied', rows: [], assignmentRevision: 8, approvedRevision: 2 }
    case 'skills.assignments.list': return { assignments: { layer: { kind: 'user-global', scopeId: null, harnessId: null }, rows: [], assignmentRevision: 7 } }
    case 'skills.assignments.upsert': case 'skills.assignments.remove': return { write: { kind: 'applied', rows: [], assignmentRevision: 8 } }
    case 'skills.resolve': case 'skills.previewEffective': return { effective: { target: {}, assignmentRevision: 7, resolved: [], refusals: [] } }
    case 'skills.discoverNative': return { discovered: [] }
    case 'skills.invokeDescriptor': return { descriptor: { kind: 'invoke', revision: 1 } }
    default: return undefined
  }
}

/** The fake used by every other test must satisfy the same shape the real
 * gateway does: no method may be missing, so an unwired call can never be
 * mistaken for an empty answer. */
describe('fake gateway completeness', () => {
  it('implements every member of the family the views call', () => {
    const { gateway } = fakeSkillsGateway()
    expect(Object.keys(gateway).sort()).toEqual([
      'approveRevision', 'assignmentsList', 'assignmentsRemove', 'assignmentsUpsert', 'catalogue', 'checkUpdate',
      'diff', 'discoverNative', 'get', 'importBegin', 'importCancel', 'importChunk', 'importCommit',
      'importPreview', 'invokeDescriptor', 'list', 'preview', 'previewEffective', 'resolve', 'revisions', 'sources',
    ])
    expect(Object.values(gateway).every(value => typeof value === 'function')).toBe(true)
  })
})
