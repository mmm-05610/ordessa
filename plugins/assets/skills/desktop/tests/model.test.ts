import { describe, expect, it } from 'vitest'
import type { SkillsGateway } from '../../contracts/src/gateway'
import { createSkillsModel } from '../src/model'
import {
  AVAILABLE_PROJECT, MISSING_PROJECT, demoEffective, demoRecord, demoResolved, demoRow,
  fakeSkillsGateway, fakeWorkspaces,
} from './fakes'

const ONE_FILE = { path: 'SKILL.md', bytes: new TextEncoder().encode('---\nname: demo\ndescription: d\n---\nbody') }

/** Rows the global layer shows: one stored enable, resolved with the deciding
 * scope + revision. */
function gatewayWithRows(options = {}) {
  return fakeSkillsGateway({
    rows: [demoRow('demo')],
    effective: demoEffective([demoResolved('demo', {
      selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 1 },
    })]),
    ...options,
  })
}

describe('skills model: reads', () => {
  it('loads the library and keeps 本层设置 and 最终结果 as two separate fields', async () => {
    const { gateway } = gatewayWithRows({
      catalogue: [demoRecord(), demoRecord({ assetId: 'other', nativeName: 'other' })],
      effective: demoEffective([
        demoResolved('demo', { selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 1 } }),
        demoResolved('other', {
          selectedBy: { layer: 'none', scopeId: null, harnessId: null, revision: null },
          evidence: 'stored', proofs: ['content_digest'],
        }),
      ]),
    })
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    const snapshot = model.getSnapshot()
    const row = snapshot.global.rows.find(item => item.assetId === 'demo')
    expect(snapshot.library.items).toHaveLength(2)
    expect(row?.layerRow?.decision).toBe('enable')
    expect(row?.effective?.selectedBy).toEqual({ layer: 'user-global', scopeId: null, harnessId: null, revision: 1 })
    // A content row with no entry at this layer reads as 继承 (no row, no
    // draft), and its 最终结果 says "无人选择" — never a hidden disable.
    const inherited = snapshot.global.rows.find(item => item.assetId === 'other')
    expect(inherited?.layerRow).toBeNull()
    expect(inherited?.draft).toBeNull()
    expect(inherited?.effective?.selectedBy.layer).toBe('none')
    expect(inherited?.effective?.excludedBy).toBeNull()
  })

  it('a request failure reports the error and keeps both the last good rows and the draft', async () => {
    let fail = false
    const inner = gatewayWithRows()
    const failing: SkillsGateway = {
      ...inner.gateway,
      assignmentsList: async query => {
        if (fail) throw Error('NETWORK: connection reset')
        return inner.gateway.assignmentsList(query)
      },
    }
    const model = createSkillsModel(failing, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'disable')
    const before = model.getSnapshot().global.rows
    const draft = model.getSnapshot().global.draft
    fail = true
    await model.refresh()
    const snapshot = model.getSnapshot()
    expect(snapshot.global.state).toBe('error')
    expect(snapshot.global.error).toContain('NETWORK')
    // The counterexample G14 names: a failed request must not clear the draft.
    expect(snapshot.global.rows).toBe(before)
    expect(snapshot.global.draft).toBe(draft)
    expect(Object.keys(snapshot.global.draft)).toEqual(['demo'])
  })

  it('switching the Harness scope keeps this layer draft and leaves the other layer alone', async () => {
    const { gateway, calls } = gatewayWithRows()
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'disable')
    await model.setHarness('global', 'codex')
    expect(Object.keys(model.getSnapshot().global.draft)).toEqual(['demo'])
    expect(model.getSnapshot().project.draft).toEqual({})
    // The brand layer is asked for, and the resolve target says the same brand.
    const listed = calls.filter(call => call.method === 'assignmentsList')
    expect(listed.at(-1)?.params[0]).toEqual({ layer: { kind: 'user-global', scopeId: null, harnessId: 'codex' } })
    expect(calls.filter(call => call.method === 'resolve').at(-1)?.params[0]).toEqual({ projectId: null, harnessId: 'codex', profileId: null })
  })
})

describe('skills model: draft, CAS and the project gate', () => {
  it('enable pins the approved revision, disable pins none, inherit removes the row', async () => {
    const { gateway, calls } = gatewayWithRows()
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'enable')
    expect(model.getSnapshot().global.draft.demo?.draft).toEqual({
      assetId: 'demo', layer: { kind: 'user-global', scopeId: null, harnessId: null }, decision: 'enable', revision: 1,
    })
    model.edit('global', 'demo', 'disable')
    expect(model.getSnapshot().global.draft.demo?.draft.revision).toBeNull()
    await model.save('global')
    expect(calls.some(call => call.method === 'assignmentsUpsert'
      && (call.params[0] as { decision: string }).decision === 'disable')).toBe(true)
    model.edit('global', 'demo', 'inherit')
    await model.save('global')
    expect(calls.filter(call => call.method === 'assignmentsRemove')).toHaveLength(1)
  })

  it('a CAS conflict keeps every draft cell, surfaces the server revision and offers a re-read', async () => {
    const conflict = { kind: 'conflict', code: 'cas-conflict', message: '版本 7 已过期', serverRevision: 9 } as const
    const { gateway, calls } = gatewayWithRows({ write: conflict })
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'disable')
    await model.save('global')
    let state = model.getSnapshot().global
    expect(state.conflict).toEqual({ message: '版本 7 已过期', serverRevision: 9 })
    expect(state.draft.demo?.draft.decision).toBe('disable')
    expect(state.saving).toBe(false)
    // Nothing was written through the conflict, and no silent second attempt.
    expect(calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(1)
    const listsBefore = calls.filter(call => call.method === 'assignmentsList').length
    await model.reRead('global')
    state = model.getSnapshot().global
    expect(state.conflict).toBeNull()
    // The re-read refreshed the stored side; the user's edit is still there.
    expect(state.draft.demo?.draft.decision).toBe('disable')
    expect(calls.filter(call => call.method === 'assignmentsList')).toHaveLength(listsBefore + 1)
    expect(calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(1)
  })

  it('a failed save is not a lost draft either', async () => {
    const { gateway } = gatewayWithRows({ write: { kind: 'conflict', code: 'unauthorized', message: '无权写入', serverRevision: 7 } })
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'enable')
    await model.save('global')
    expect(model.getSnapshot().global.draft.demo?.draft.decision).toBe('enable')
    expect(model.getSnapshot().global.conflict?.message).toBe('无权写入')
  })

  it('retries of the same edit reuse one operation key, so a save cannot apply twice', async () => {
    let attempt = 0
    const { gateway, calls } = gatewayWithRows({
      write: () => {
        attempt += 1
        return attempt === 1
          ? { kind: 'conflict', code: 'cas-conflict', message: 'stale', serverRevision: 7 }
          : ({ kind: 'applied', rows: [demoRow('demo')], assignmentRevision: 8 } as const)
      },
    })
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'disable')
    const key = model.getSnapshot().global.draft.demo?.operationKey
    await model.save('global')
    model.edit('global', 'demo', 'disable')
    expect(model.getSnapshot().global.draft.demo?.operationKey).toBe(key)
    await model.save('global')
    const keys = calls.filter(call => call.method === 'assignmentsUpsert')
      .map(call => (call.params[1] as { operationKey: string }).operationKey)
    expect(keys).toEqual([key, key])
    expect(model.getSnapshot().global.draft).toEqual({})
  })

  it('a missing project stops editing without dropping anything, and no write is sent', async () => {
    let projects = [AVAILABLE_PROJECT]
    const { gateway, calls } = gatewayWithRows({ rows: [demoRow('demo', {
      layer: { kind: 'project', scopeId: 'ordessa', harnessId: null }, decision: 'disable', revision: null,
    })] })
    const port = fakeWorkspaces(() => Promise.resolve(projects)).port
    const model = createSkillsModel(gateway, port)
    await model.refresh()
    await model.setProject('ordessa')
    expect(model.getSnapshot().project.editable).toBe(true)
    model.edit('project', 'demo', 'enable')
    expect(Object.keys(model.getSnapshot().project.draft)).toEqual(['demo'])
    // The project goes away mid-edit.
    projects = [MISSING_PROJECT]
    await model.refresh()
    const state = model.getSnapshot().project
    expect(state.editable).toBe(false)
    expect(state.stopReason).toContain('项目已缺失')
    // 已存记录 stays visible while editing is refused.
    expect(state.storedRows.map(row => row.decision)).toEqual(['disable'])
    const writesBefore = calls.filter(call => call.method.startsWith('assignmentsUpsert')).length
    await model.save('project')
    expect(calls.filter(call => call.method.startsWith('assignmentsU')).length).toBe(writesBefore)
    expect(model.getSnapshot().project.draft.demo?.draft.decision).toBe('enable')
    // New edits are refused too, and the refusal is said rather than swallowed.
    model.edit('project', 'demo', 'disable')
    expect(model.getSnapshot().project.draft.demo?.draft.decision).toBe('enable')
  })

  it('an unconfirmed project state pauses editing, including when the Workspace call failed', async () => {
    const { gateway } = gatewayWithRows()
    const broken = fakeWorkspaces(Error('WORKSPACE_UNAVAILABLE'))
    const model = createSkillsModel(gateway, broken.port)
    await model.refresh()
    await model.setProject('ordessa')
    expect(model.getSnapshot().project.editable).toBe(false)
    expect(model.getSnapshot().project.stopReason).toContain('未确认')
    expect(model.getSnapshot().projects.error).toContain('WORKSPACE_UNAVAILABLE')
  })

  it('previewing the effective set uses the read-only resolver and writes nothing', async () => {
    const { gateway, calls } = gatewayWithRows({
      draftEffective: demoEffective([demoResolved('demo', {
        selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 2 },
        evidence: 'selected', proofs: ['assignment_decision'],
      })]),
    })
    const model = createSkillsModel(gateway, fakeWorkspaces([AVAILABLE_PROJECT]).port)
    await model.refresh()
    model.edit('global', 'demo', 'enable', 2)
    await model.previewDraft('global')
    expect(model.getSnapshot().global.preview?.resolved[0]?.revision).toBe(1)
    expect(calls.filter(call => call.method === 'previewEffective')).toHaveLength(1)
    expect(calls.filter(call => call.method.startsWith('assignments'))
      .every(call => call.method === 'assignmentsList')).toBe(true)
  })
})

/** Ports of the legacy desktop model cases (plugins/assets/desktop/tests/
 * assets.test.tsx @ 752f148b1b), assertions kept. */
describe('legacy ports: import honesty', () => {
  it('imports honestly: a commit is "stored", never "loaded"', async () => {
    const { gateway, calls } = fakeSkillsGateway()
    const model = createSkillsModel(gateway, fakeWorkspaces([]).port)
    await model.importPicked([ONE_FILE], 'desktop:test', { originScope: 'public', originOwner: null })
    expect(model.getSnapshot().importPhase.kind).toBe('prepared')
    await model.confirmImport()
    const phase = model.getSnapshot().importPhase
    expect(phase.kind).toBe('committed')
    expect(phase.kind === 'committed' && phase).toMatchObject({ assetId: 'demo', revision: 2 })
    for (const method of ['importBegin', 'importChunk', 'importPreview', 'importCommit']) {
      expect(calls.some(call => call.method === method), method).toBe(true)
    }
    // No surface of the model may word the commit as a load.
    expect(JSON.stringify(phase)).not.toContain('loaded')
  })

  it('a failed preview cancels the session and reports failure without touching the list', async () => {
    const failing: SkillsGateway = {
      ...fakeSkillsGateway().gateway,
      async importPreview() { throw Error('IMPORT_DIGEST_MISMATCH: chunk 0') },
    }
    const { calls } = fakeSkillsGateway()
    const tracking: SkillsGateway = {
      ...failing,
      async importCancel(importId) { calls.push({ method: 'importCancel', params: [importId] }); return failing.importCancel(importId) },
    }
    const model = createSkillsModel(tracking, fakeWorkspaces([]).port)
    await model.refresh()
    const before = model.getSnapshot().library.items
    await model.importPicked([ONE_FILE], 'desktop:test', { originScope: 'public', originOwner: null })
    expect(model.getSnapshot().importPhase.kind).toBe('failed')
    expect(calls.some(call => call.method === 'importCancel')).toBe(true)
    expect(model.getSnapshot().library.items).toBe(before)
  })

  it('an archived source keeps its records readable and the import surface honest', async () => {
    const { gateway } = fakeSkillsGateway({ catalogue: [demoRecord({ archived: true })] })
    const model = createSkillsModel(gateway, fakeWorkspaces([]).port)
    await model.refresh()
    expect(model.getSnapshot().library.items?.[0]?.archived).toBe(true)
    expect(model.getSnapshot().error).toBeNull()
  })
})
