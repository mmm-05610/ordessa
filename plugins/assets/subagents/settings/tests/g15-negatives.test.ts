/**
 * G15 negative column, verbatim from `docs/design/native-subagents/verification.md`:
 * 错误清草稿 / 另服务晚响应覆盖 / 权限项视觉假绿.
 * Each `it` below fails if its guard is removed.
 */
import { describe, expect, it } from 'vitest'
import { initialState, reduce, saveRevisionIntent, startDraft, visibleRows, type SettingsState } from '../src/model'
import { detailOf, failedResult, okList, OTHER_TARGET, TARGET } from './fixtures'
import { declarationNode } from '../src/view'

const baseState = (): SettingsState => initialState({ target: TARGET, viewerPrincipal: 'principal-1', serviceAvailable: true })

function draftState(): SettingsState {
  const started = reduce(baseState(), { type: 'detail/select', definitionId: 'def-1' })
  const withDetail = reduce(started, { type: 'detail/result', definitionId: 'def-1', stamp: TARGET, result: { ok: true, stamp: TARGET, data: detailOf() } })
  const drafted = reduce(withDetail, { type: 'draft/start', definitionId: 'def-1' })
  return reduce(drafted, { type: 'draft/edit', field: 'roleBody', value: '未保存的正文' })
}

describe('G15 negative: 另一服务晚响应覆盖 (§C2 per-target stamping)', () => {
  const base = reduce(baseState(), { type: 'list/result', stamp: TARGET, result: okList(TARGET, []) })

  it('a response for a foreign server/project/profile/session target is dropped', () => {
    const switched = reduce(base, { type: 'target/switch', target: OTHER_TARGET })
    expect(switched.target.serverId).toBe('srv-b')

    // The OLD target's list response arrives after the switch.
    const staleRows = [detailOf({ definitionId: 'def-stale', displayName: '另一服务的行' })]
    const after = reduce(switched, { type: 'list/result', stamp: TARGET, result: okList(TARGET, staleRows) })

    // dropped means *unchanged*: the new target's own (still unloaded) slice stays as it is
    expect(after.list.data).toBeNull()
    expect(after.list.status).toBe('idle')
    expect(after.stats.droppedResults).toBe(1)
    expect(visibleRows(after).map(r => r.id)).not.toContain('def-stale')
  })

  it('drops on each stamp field independently, not just serverId', () => {
    const variants = [
      { ...TARGET, projectId: 'other-proj' },
      { ...TARGET, profileId: 'other-prof' },
      { ...TARGET, sessionId: 'other-sess' },
      { ...TARGET, revision: TARGET.revision + 1 },
      { ...TARGET, providerGeneration: 'gen-stale' },
    ]
    for (const stamp of variants) {
      const switched = reduce(base, { type: 'target/switch', target: { ...TARGET, revision: 99 } })
      const after = reduce(switched, { type: 'list/result', stamp, result: okList(stamp, [detailOf()]) })
      expect(after.stats.droppedResults, JSON.stringify(stamp)).toBe(1)
      expect(after.list.data, JSON.stringify(stamp)).toBeNull()
    }
  })

  it('a matching stamp does land (the guard is not a blanket refuse)', () => {
    const other = initialState({ target: OTHER_TARGET, viewerPrincipal: 'principal-1', serviceAvailable: true })
    const after = reduce(other, { type: 'list/result', stamp: OTHER_TARGET, result: okList(OTHER_TARGET, [detailOf()]) })
    expect(after.list.status).toBe('ready')
    expect(after.list.data?.map(r => r.definitionId)).toEqual(['def-1'])
    expect(after.stats.droppedResults).toBe(0)
  })

  it('a detail response for a row the user already left never lands', () => {
    const selected = reduce(base, { type: 'detail/select', definitionId: 'def-1' })
    const requested = reduce(selected, { type: 'detail/request', definitionId: 'def-1' })
    const movedOn = reduce(requested, { type: 'detail/select', definitionId: 'def-2' })
    const late = reduce(movedOn, { type: 'detail/result', definitionId: 'def-1', stamp: TARGET, result: { ok: true, stamp: TARGET, data: detailOf() } })
    expect(late.detail.status).toBe('idle')
    expect(late.detail.data).toBeNull()
  })

  it('a late mutation result for an untracked operation key cannot re-apply', () => {
    const withRow = reduce(base, { type: 'list/result', stamp: TARGET, result: okList(TARGET, [detailOf()]) })
    const after = reduce(withRow, {
      type: 'mutation/result', operationKey: 'never-asked', kind: 'archive', stamp: TARGET,
      result: { ok: true, stamp: TARGET, data: detailOf({ archived: true }) },
    })
    expect(after.list.data?.[0]?.archived).toBe(false)
    expect(after.notices).toHaveLength(0)
  })

  it('an assignments result from another target cannot overwrite the defaults pane', () => {
    const loaded = reduce(base, { type: 'assignments/result', layer: 'user-global', stamp: TARGET, result: { ok: true, stamp: TARGET, data: [] } })
    const switched = reduce(loaded, { type: 'target/switch', target: OTHER_TARGET })
    const after = reduce(switched, {
      type: 'assignments/result', layer: 'user-global', stamp: TARGET,
      result: { ok: true, stamp: TARGET, data: [{ serverScope: 's', principal: 'p', scopeKind: 'user-global-generic', scopeId: null, harnessId: 'any', definitionId: 'from-old-target', decision: 'enable', revision: 1, rowVersion: 0 }] },
    })
    expect(after.defaults['user-global'].data ?? []).toEqual([])
    expect(after.stats.droppedResults).toBe(1)
  })
})

describe('G15 negative: 错误清草稿', () => {
  const withDraft = draftState()

  it('a list read failure keeps the unsaved draft byte-identical', () => {
    const after = reduce(withDraft, { type: 'list/result', stamp: TARGET, result: failedResult(TARGET, 'DEFINITION_INVALID', '读取失败') })
    expect(after.list.status).toBe('error')
    expect(after.draft).toEqual(withDraft.draft)
    expect(after.draft?.roleBody).toBe('未保存的正文')
    expect(after.draft?.dirty).toBe(true)
  })

  it('a CAS (REVISION_STALE) save failure keeps the draft AND the saved content', () => {
    const pending = reduce(withDraft, {
      type: 'mutation/request', refusal: null,
      intent: { operationKey: 'save:op-1', kind: 'save-revision', stamp: TARGET, definitionId: 'def-1', assignment: null },
    })
    const after = reduce(pending, {
      type: 'mutation/result', operationKey: 'save:op-1', kind: 'save-revision', stamp: TARGET,
      result: { ok: false, stamp: TARGET, error: { code: 'REVISION_STALE', detail: 'rowVersion 落后' } },
    })
    expect(after.draft?.roleBody).toBe('未保存的正文')
    expect(after.draft?.dirty).toBe(true)
    // the last successfully stored revision is untouched in the loaded detail
    expect(after.detail.data?.latestRevision).toBe(2)
    expect(after.notices.filter(n => n.level === 'refusal' && n.code === 'REVISION_STALE')).toHaveLength(1)
    expect(after.notices.find(n => n.code === 'REVISION_STALE')?.text).toContain('草稿')
  })

  it('abandoning a dialog does not clear the draft', () => {
    const opened = reduce(withDraft, { type: 'dialog/open', dialog: { kind: 'archive', definitionId: 'def-1', effectText: 'x', pinned: [] } })
    const closed = reduce(opened, { type: 'dialog/close' })
    expect(closed.dialog.kind).toBe('none')
    expect(closed.draft?.roleBody).toBe('未保存的正文')
  })

  it('switching target preserves the draft but refuses to apply it', () => {
    const switched = reduce(withDraft, { type: 'target/switch', target: OTHER_TARGET })
    expect(switched.draft?.roleBody).toBe('未保存的正文')
    expect(switched.draft?.draftTarget).toEqual(TARGET)
    const intent = saveRevisionIntent(
      switched.draft!,
      { definitionId: 'def-1', displayName: 'a', slug: 'b', description: 'c', roleBody: '未保存的正文', expectedRowVersion: 3 },
      OTHER_TARGET, 'n1',
    )
    expect(intent.refusal).toContain('另一个目标')
  })

  it('only the explicit discard clears a draft', () => {
    expect(reduce(withDraft, { type: 'draft/discard' }).draft).toBeNull()
    expect(reduce(withDraft, { type: 'filter/origin', filter: 'mine' }).draft).not.toBeNull()
  })

  it('an explicitly saved revision survives abandoning the page draft', () => {
    const pending = reduce(withDraft, {
      type: 'mutation/request', refusal: null,
      intent: { operationKey: 'save:op-2', kind: 'save-revision', stamp: TARGET, definitionId: 'def-1', assignment: null },
    })
    const saved = reduce(pending, {
      type: 'mutation/result', operationKey: 'save:op-2', kind: 'save-revision', stamp: TARGET,
      result: { ok: true, stamp: TARGET, data: detailOf({ latestRevision: 3, rowVersion: 9 }) },
    })
    expect(saved.draft?.dirty).toBe(false)
    expect(saved.draft?.savedMarker).toBe('rev:3')
    expect(saved.list.data?.[0]?.latestRevision).toBe(3)
    const abandoned = reduce(saved, { type: 'draft/discard' })
    expect(abandoned.list.data?.[0]?.latestRevision).toBe(3)
    expect(abandoned.list.data?.[0]?.rowVersion).toBe(9)
  })

  it('the draft seeded from the stored revision matches the store, not a guess', () => {
    expect(withDraft.draft).toEqual({
      ...startDraft(detailOf(), TARGET),
      roleBody: '未保存的正文',
      dirty: true,
    })
  })
})

describe('G15 negative: 权限项视觉假绿', () => {
  it('an over-ceiling item is refused-styled with its reason and never reads as granted', () => {
    const node = declarationNode({
      kind: 'permission-mode', name: 'bypassPermissions', granted: false,
      refusal: { code: 'PERMISSION_EXCEEDS_CEILING', detail: '审批姿势放宽的字段一律拒绝', source: 'capability-matrix.md' },
    }, 'perm')
    if (node.kind !== 'element') throw new Error('expected an element')
    expect(node.attrs['data-tone']).toBe('refused')
    const json = JSON.stringify(node)
    expect(json).toContain('不可应用')
    expect(json).toContain('PERMISSION_EXCEEDS_CEILING')
    expect(json).not.toContain('已生效')
    expect(json).not.toContain('"data-tone":"yes"')
  })

  it('an unverified grant renders as unverified — neither a check nor a cross', () => {
    const node = declarationNode({ kind: 'tool', name: 'Bash', granted: 'unknown' }, 'perm')
    if (node.kind !== 'element') throw new Error('expected an element')
    expect(node.attrs['data-granted']).toBe('unknown')
    expect(node.attrs['data-tone']).toBe('unknown')
    const json = JSON.stringify(node)
    expect(json).not.toContain('✓')
    expect(json).not.toContain('✗')
    expect(json).toContain('实际授权未验证')
  })

  it('requested is always shown separately from granted', () => {
    const json = JSON.stringify(declarationNode({ kind: 'tool', name: 'Read', granted: true }, 'perm'))
    expect(json).toContain('请求能力')
    expect(json).toContain('"data-requested":"true"')
    expect(json).toContain('已授权')
  })
})
