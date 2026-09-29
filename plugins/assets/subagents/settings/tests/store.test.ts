/**
 * The store's async flows: request stamping with real promises, refusal before
 * any port call, and the service-absence path (§C2 — no spinner, no fake data).
 */
import { describe, expect, it } from 'vitest'
import { createSettingsStore } from '../src/store'
import { visibleRows } from '../src/model'
import { createFakePort, detailOf, OTHER_TARGET, summaryOf, TARGET } from './fixtures'

const tick = () => new Promise(resolve => { setTimeout(resolve, 0) })

/** Load the row set, select def-1 and load its detail — the state a user is in
 *  when they press 编辑. */
function openDefinition(store: ReturnType<typeof createSettingsStore>) {
  store.dispatch({ type: 'list/result', stamp: TARGET, result: { ok: true, stamp: TARGET, data: [detailOf()] } })
  store.dispatch({ type: 'detail/select', definitionId: 'def-1' })
  store.dispatch({ type: 'detail/result', definitionId: 'def-1', stamp: TARGET, result: { ok: true, stamp: TARGET, data: detailOf() } })
}

describe('service absence', () => {
  it('reload() with no port yields explained absent slices, never a loading state', () => {
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    store.reload()
    const state = store.getState()
    expect(state.serviceAvailable).toBe(false)
    for (const slice of [state.list, state.native, state.detail, state.effective, state.defaults['user-global'], state.defaults['project']]) {
      expect(slice.status).toBe('absent')
      expect(slice.absence?.owner).toContain('C0')
    }
    expect(state.list.status).not.toBe('loading')
    expect(visibleRows(state)).toEqual([])
  })

  it('an absent port refuses every action without touching the port list', () => {
    const store = createSettingsStore({ port: null, target: TARGET, viewerPrincipal: 'principal-1' })
    store.reload()
    store.activate('inspect-native', {})
    store.activate('resolve-preview', {})
    store.activate('select-row', { 'data-row-id': 'def-1' })
    store.activate('import-preview', {})
    store.activate('retry', {})
    expect(store.getState().list.status).toBe('absent')
    expect(store.getState().stats.droppedResults).toBe(0)
  })
})

describe('request stamping with real promises', () => {
  it('a response that arrives after a target switch is dropped, not applied', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    store.activate('reload', {})
    await tick()
    // nothing has resolved yet: the row set is still empty and loading
    expect(store.getState().list.status).toBe('loading')

    store.dispatch({ type: 'target/switch', target: OTHER_TARGET })
    port.listD.resolve({ ok: true, stamp: TARGET, data: [detailOf()] })
    await tick()

    const state = store.getState()
    expect(state.stats.droppedResults).toBe(1)
    expect(state.list.status).toBe('idle')
    expect(visibleRows(state).map(r => r.id)).not.toContain('def-1')
  })

  it('a matching response lands exactly once and keeps its request stamp', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    store.activate('reload', {})
    await tick()
    port.listD.resolve({ ok: true, stamp: TARGET, data: [summaryOf()] })
    port.nativeD.resolve({ ok: true, stamp: TARGET, data: { state: 'observed', observations: [] } })
    port.assignmentsD.resolve({ ok: true, stamp: TARGET, data: [] })
    await port.settleAll(TARGET)
    await tick()

    const state = store.getState()
    expect(state.list.status).toBe('ready')
    expect(state.list.requestStamp).toEqual(TARGET)
    expect(visibleRows(state).map(r => r.id)).toEqual(['def-1'])
    expect(state.stats.droppedResults).toBe(0)
  })

  it('the port is called with the stamp the reducer will check', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    store.activate('inspect-native', {})
    await tick()
    expect(port.calls.map(c => c.method)).toContain('inspectNative')
    expect(port.calls.every(c => c.stamp.serverId === TARGET.serverId)).toBe(true)
  })
})

describe('mutations: refusal happens before the port is called', () => {
  it('a save with no unsaved changes never reaches the port', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    openDefinition(store)
    store.activate('draft-open', {})
    store.activate('confirm-publish', {})
    await tick()
    expect(port.calls.some(c => c.method === 'saveRevision')).toBe(false)
    expect(store.getState().stats.refusedMutations).toBe(1)
    expect(store.getState().notices.some(n => n.level === 'refusal')).toBe(true)
    // the untouched draft survives
    expect(store.getState().draft).not.toBeNull()
  })

  it('an approved save publishes a revision and keeps the draft content marked saved', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    openDefinition(store)
    store.activate('draft-open', {})
    store.activate('draft-edit', { 'data-field': 'roleBody', 'data-value': '新的角色正文' })
    store.activate('confirm-publish', {})
    await tick()
    expect(port.calls.map(c => c.method)).toContain('saveRevision')
    port.mutationD.resolve({ ok: true, stamp: TARGET, data: detailOf({ latestRevision: 3, rowVersion: 9 }) })
    await tick()

    const state = store.getState()
    expect(state.draft?.dirty).toBe(false)
    expect(state.draft?.savedMarker).toBe('rev:3')
    expect(state.list.data?.[0]?.latestRevision).toBe(3)
    // and the wording never claims the definition is now in effect
    expect(state.notices.some(n => n.text.includes('存内容不等于启用'))).toBe(true)
  })

  it('a ceiling refusal keeps the draft and reports the code', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    openDefinition(store)
    store.activate('draft-open', {})
    store.activate('draft-edit', { 'data-field': 'roleBody', 'data-value': '要求 Bash 与 bypassPermissions' })
    store.activate('confirm-publish', {})
    await tick()
    port.mutationD.resolve({ ok: false, stamp: TARGET, error: { code: 'PERMISSION_EXCEEDS_CEILING', detail: '上限未授予' } })
    await tick()
    const state = store.getState()
    expect(state.draft?.roleBody).toBe('要求 Bash 与 bypassPermissions')
    expect(state.notices.find(n => n.code === 'PERMISSION_EXCEEDS_CEILING')?.text).toContain('已拒绝')
    // the stored revision is untouched: a refusal never rewrote the row
    expect(state.detail.data?.latestRevision).toBe(2)
    expect(state.detail.data?.rowVersion).toBe(3)
  })

  it('a native disable without established suppressibility is refused with the §C5 code', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    store.dispatch({
      type: 'native/result', stamp: TARGET,
      result: { ok: true, stamp: TARGET, data: { state: 'observed', observations: [{ nativeName: 'legacy', scope: 'project', sourceCategory: 'native-file' }] } },
    })
    store.dispatch({ type: 'detail/select', definitionId: 'native:project:legacy' })
    store.activate('native-disable', {})
    await tick()
    expect(port.calls.some(c => c.method === 'approveAssignmentUpdate')).toBe(false)
    const notice = store.getState().notices.find(n => n.level === 'refusal')
    expect(notice?.text).toContain('NATIVE_DISCOVERY_UNCONTROLLED')
    expect(notice?.text).not.toMatch(/已禁用|已屏蔽|已关闭/)
  })

  it('an import approval without a selected file never reaches the port', async () => {
    const port = createFakePort()
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    store.activate('import-source', { 'data-value': 'git:rev-1' })
    store.activate('import-preview', {})
    await tick()
    port.previewD.resolve({ ok: true, stamp: TARGET, data: { previewId: 'p', sourceName: 's', sourceRef: 'r', sourceDigest: 'd', files: [], diagnostics: [], futurePermissions: [] } })
    await tick()
    store.activate('import-approve', {})
    await tick()
    expect(port.calls.some(c => c.method === 'approveImport')).toBe(false)
    expect(store.getState().stats.refusedMutations).toBe(1)
  })

  it('an unhandled port rejection becomes OPERATION_UNKNOWN, not a silent success', async () => {
    const port = createFakePort()
    port.listDefinitions = () => Promise.reject(new Error('boom'))
    const store = createSettingsStore({ port, target: TARGET, viewerPrincipal: 'principal-1' })
    store.activate('reload', {})
    await tick()
    await tick()
    const state = store.getState()
    expect(state.list.status).toBe('error')
    expect(state.list.failure?.code).toBe('OPERATION_UNKNOWN')
    // and the error never claims a read succeeded
    expect(state.list.data).toBeNull()
  })
})
