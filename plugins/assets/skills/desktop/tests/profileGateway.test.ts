// @vitest-environment jsdom
/**
 * Profile-side gateway contract tests.
 *
 * The wire-name lists in this file are HAND-MAINTAINED literals, not read
 * from `src/ordessa_skills/wire.py`. What they pin is exactly: (1) the
 * gateway's own closed set `PROFILE_WIRE_METHODS` must equal the frozen
 * local list (the equality check below — any rename/added door in the
 * desktop adapter is a red here), and (2) that frozen list must remain a
 * SUBSET of a locally copied snapshot of the published `skills.*` family
 * (wire.py's `SKILLS_METHOD_IDS` as of the copy date). A backend-side
 * rename in wire.py does NOT automatically go red in this file — keeping
 * the snapshot honest is a review-time duty. The dotted legacy spellings
 * (`skills.import.begin`, …) and the never-published `assets.profileFacets`
 * are refused here by name, which is the defect G15 must not repeat.
 */
import { describe, expect, it } from 'vitest'
import { PROFILE_WIRE_METHODS, createProfileSkillsGateway, type ProfileWireMethod } from '../src/profileGateway'
import type { WireCaller } from '../src/gateway'

/** Records every wire call and answers with the backend's own view shape
 * (`service.py` / `resolver.py` outputs), envelope-free. */
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

describe('profile skills gateway speaks the published wire family', () => {
  it('calls exactly the skills.* names wire.py publishes, with its flat params', async () => {
    const { wire, sent } = spyWire(method => envelope(method))
    const gateway = createProfileSkillsGateway(wire)
    await gateway.listSkills()
    await gateway.revisions('demo')
    await gateway.diff({ assetId: 'demo', fromRevision: 1, toRevision: 2 })
    await gateway.approveRevision({ assetId: 'demo', revision: 2, expectedDigest: 'sha256:' + 'a'.repeat(64) })
    await gateway.resolveProfile({ profileId: 'p1', harnessId: 'pi' })
    const opened = await gateway.importBegin([{ path: 'SKILL.md', bytes: 2, sha256: 'sha256:x' }], 2)
    await gateway.importChunk(opened.importId, 0, new Uint8Array([1, 2]), 'sha256:x')
    await gateway.importPreview(opened.importId)
    await gateway.importCommit(opened.importId, 'demo', 2)
    await gateway.importCancel(opened.importId)

    expect(sent.map(call => call.method)).toEqual([...PROFILE_WIRE_METHODS])
    // wire.py param vocabulary: flat ids, `chunkIndex`/`payloadBase64`,
    // `fromRevision`/`toRevision`, `profileId`/`harnessId` — no nested
    // `target`, no dotted `import.*`, no `sourcePath` anywhere.
    const chunkCall = sent.find(call => call.method === 'skills.importChunk')!
    expect(Object.keys(chunkCall.params).sort()).toEqual(['chunkIndex', 'importId', 'payloadBase64', 'sha256'])
    const resolveCall = sent.find(call => call.method === 'skills.resolve')!
    expect(resolveCall.params).toEqual({ profileId: 'p1', harnessId: 'pi' })
    const diffCall = sent.find(call => call.method === 'skills.diff')!
    expect(diffCall.params).toEqual({ assetId: 'demo', fromRevision: 1, toRevision: 2 })
    const commitCall = sent.find(call => call.method === 'skills.importCommit')!
    expect(commitCall.params).toEqual({ importId: opened.importId, assetId: 'demo', revision: 2 })
    const previewCall = sent.find(call => call.method === 'skills.importPreview')!
    expect(previewCall.params.source).toEqual({ kind: 'local' })
    expect(JSON.stringify(sent)).not.toContain('sourcePath')
  })

  it('never speaks the legacy assets.* vocabulary, including the unwired facet call', async () => {
    const { wire, sent } = spyWire(method => envelope(method))
    const gateway = createProfileSkillsGateway(wire)
    await gateway.listSkills()
    await gateway.resolveProfile({ profileId: 'p1', harnessId: 'pi', projectId: 'ordessa' })
    expect(sent.map(call => call.method).filter(method => method.startsWith('assets.'))).toEqual([])
    expect(sent.map(call => call.method)).not.toContain('assets.profileFacets')
    // The dotted legacy spellings do not exist in wire.py's table; nothing
    // this gateway emits may use them either.
    expect(sent.every(call => !call.method.includes('import.'))).toBe(true)
    expect(sent[1].params).toEqual({ profileId: 'p1', harnessId: 'pi', projectId: 'ordessa' })
  })

  it('an empty wire answer is a refusal, not an empty list', async () => {
    const { wire } = spyWire(() => null)
    await expect(createProfileSkillsGateway(wire).listSkills()).rejects.toThrow('empty wire response')
  })

  it('normalises the backend view dicts onto the shared contract DTOs', async () => {
    const { wire } = spyWire(method => envelope(method))
    const gateway = createProfileSkillsGateway(wire)
    const [row] = await gateway.listSkills()
    // records.py asset_view `name`/`latestRevision`/`digest` → the model names.
    expect(row).toEqual({
      assetId: 'demo', nativeName: 'demo', description: 'A demo.', source: 'local:import',
      latestInstalledRevision: 2, treeDigest: 'sha256:' + 'a'.repeat(64),
    })
    const options = await gateway.revisions('demo')
    // Approval is the backend's fact (approvalRecord present), never inferred.
    expect(options).toEqual([
      { revision: 1, treeDigest: 'sha256:' + 'a'.repeat(64), approved: true, approvedAt: '2026-09-01T00:00:00Z' },
      { revision: 2, treeDigest: 'sha256:' + 'b'.repeat(64), approved: false, approvedAt: null },
    ])
    const effective = await gateway.resolveProfile({ profileId: 'p1', harnessId: 'pi' })
    const decided = effective.resolved.find(item => item.assetId === 'demo')!
    // resolver layers land on the shared LayerKind vocabulary; the profile
    // layer names itself with the profile id and the pinned revision.
    expect(decided.selectedBy).toEqual({ layer: 'profile', scopeId: 'p1', harnessId: 'pi', revision: 2 })
    expect(decided.evidence).toBe('selected')
    expect(decided.proofs).toEqual(['assignment_decision'])
    // The not_enabled absence maps to the DTO's `none` layer — disable and
    // never-enabled stay distinct (G06).
    const absent = effective.resolved.find(item => item.assetId === 'never')!
    expect(absent.selectedBy.layer).toBe('none')
    expect(absent.excludedBy).toBeNull()
    const forced = effective.resolved.find(item => item.assetId === 'forced')!
    expect(forced.selectedBy.layer).toBe('mandatory')
  })

  it('the typed §G3 refusal propagates with its code intact', async () => {
    const { wire } = spyWire(method => {
      if (method === 'skills.resolve') {
        throw Error('WireError UNAVAILABLE internalCode=PROFILE_LAYER_UNAVAILABLE')
      }
      return envelope(method)
    })
    const gateway = createProfileSkillsGateway(wire)
    await expect(gateway.resolveProfile({ profileId: 'p1', harnessId: 'pi' }))
      .rejects.toThrow(/PROFILE_LAYER_UNAVAILABLE/)
  })

  it('the closed method set equals the frozen local list, a subset of the copied wire.py snapshot', () => {
    // What this actually checks: `wirePublished` is a hand-copied frozen
    // snapshot of wire.py's SKILLS_METHOD_IDS (the tuple at wire.py lines
    // 392-400 as copied here); the loop proves this gateway's closed set
    // stays a SUBSET of that snapshot, and the equality below proves the
    // snapshot equals the gateway's own frozen literal list. Neither check
    // reads wire.py at runtime — backend drift alone would NOT redden
    // this test; it is the drift signal for the DESKTOP side's names only.
    const wirePublished = [
      'skills.list', 'skills.get', 'skills.revisions', 'skills.preview', 'skills.diff',
      'skills.importBegin', 'skills.importChunk', 'skills.importPreview', 'skills.importCommit', 'skills.importCancel',
      'skills.sourcesCheckUpdate', 'skills.approveRevision', 'skills.assignmentsList', 'skills.assignmentsUpsert',
      'skills.assignmentsRemove', 'skills.resolve', 'skills.previewEffective', 'skills.discoverNative', 'skills.invokeDescriptor',
    ]
    for (const method of PROFILE_WIRE_METHODS) expect(wirePublished).toContain(method)
    // And the gateway interface has no other door: the type closes the set.
    const all: readonly ProfileWireMethod[] = ['skills.list', 'skills.revisions', 'skills.diff',
      'skills.approveRevision', 'skills.resolve', 'skills.importBegin', 'skills.importChunk',
      'skills.importPreview', 'skills.importCommit', 'skills.importCancel']
    expect(PROFILE_WIRE_METHODS).toEqual(all)
  })
})

function envelope(method: string): unknown {
  switch (method) {
    case 'skills.list': return {
      items: [{
        assetId: 'demo', kind: 'skill', name: 'demo', description: 'A demo.',
        latestRevision: 2, digest: 'sha256:' + 'a'.repeat(64), source: 'local:import',
      }], nextCursor: null,
    }
    case 'skills.revisions': return {
      assetId: 'demo',
      items: [
        { revision: 1, treeDigest: 'sha256:' + 'a'.repeat(64), approvalRecord: { approvedAt: '2026-09-01T00:00:00Z', approvedBy: 'user' } },
        { revision: 2, treeDigest: 'sha256:' + 'b'.repeat(64), approvalRecord: null },
      ],
    }
    case 'skills.diff': return {
      assetId: 'demo', fromRevision: 1, toRevision: 2,
      added: ['notes.md'], removed: [], changed: ['SKILL.md'],
    }
    case 'skills.approveRevision': return { approval: { revision: 2 }, effect: 'stored' }
    case 'skills.resolve': return {
      target: { projectId: null, harnessId: 'pi', profileId: 'p1', sessionRef: '', runtimeGeneration: 0 },
      serverScope: 'server:demo',
      resolvedSkills: [
        {
          assetId: 'demo', nativeName: 'demo', revision: 2, treeDigest: 'sha256:' + 'a'.repeat(64),
          originScope: 'public', originOwner: null,
          selectedBy: { layer: 'profile', scopeKind: null, scopeId: 'p1', harnessId: 'pi', rowVersion: 4 },
          excludedBy: null, layerDecisions: [],
          capabilityEvidence: { effect: 'selected', discovery: 'unknown', isolation: 'unknown' },
        },
        {
          assetId: 'forced', nativeName: 'forced', revision: 1, treeDigest: 'sha256:' + 'c'.repeat(64),
          originScope: 'public', originOwner: null,
          selectedBy: { layer: 'mandatory_policy', scopeKind: null, scopeId: null, harnessId: null, rowVersion: null },
          excludedBy: null, layerDecisions: [],
          capabilityEvidence: { effect: 'selected', discovery: 'unknown', isolation: 'unknown' },
        },
      ],
      excludedSkills: [
        { assetId: 'never', excludedBy: null, absentReason: 'not_enabled', layerDecisions: [] },
      ],
      diagnostics: [], assignmentRevisions: { user_global_any: 3 }, profileRevision: null,
    }
    case 'skills.importBegin': return { importId: 'import_1', effect: 'stored' }
    case 'skills.importChunk': return { importId: 'import_1', receivedBytes: 2 }
    case 'skills.importPreview': return {
      name: 'demo', description: 'A demo.', metadata: {}, files: [{ path: 'SKILL.md', bytes: 2 }],
      scripts: [], treeDigest: 'sha256:' + 'b'.repeat(64), totalBytes: 2, source: { kind: 'local' },
    }
    case 'skills.importCommit': return {
      asset: { assetId: 'demo', kind: 'skill', name: 'demo', description: 'A demo.', latestRevision: 2, digest: 'sha256:' + 'b'.repeat(64), source: 'transfer:import_1' },
      effect: 'stored',
    }
    case 'skills.importCancel': return { cancelled: true, importId: 'import_1' }
    default: return undefined
  }
}
