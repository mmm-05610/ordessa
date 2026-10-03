/**
 * Render-model assertions: keyboard order, aria-shaped attributes, capability
 * truthfulness, service-absence wording, and the honest absence of the legacy
 * dispatch surface (`specs/011-q3-subagents/legacy-inventory-matrix.md` §1).
 *
 * Everything here is provable headlessly. Geometry (900×600, 200% zoom) and real
 * screen-reader output are NOT claimed — see the task report's untested list.
 */
import { describe, expect, it } from 'vitest'
import { initialState, reduce, type RowView, type SettingsState } from '../src/model'
import { buildSettingsView, collectFocusKeys, hasPositiveTabIndex, rowStatusBadge, SUPPORT_WORDING, factGlyph, factLabel } from '../src/view'
import type { ViewNode } from '../src/view'
import { detailOf, nativeOf, summaryOf, TARGET } from './fixtures'

function base(): SettingsState {
  return initialState({ target: TARGET, viewerPrincipal: 'principal-1', serviceAvailable: true })
}

function stateWith(overrides: Partial<SettingsState>): SettingsState {
  return { ...base(), ...overrides }
}

const ready = (rows: readonly ReturnType<typeof summaryOf>[]): SettingsState['list'] => ({
  status: 'ready', data: rows, failure: null, requestStamp: TARGET, absence: null,
})

function findNodes(root: ViewNode, predicate: (node: Extract<ViewNode, { kind: 'element' }>) => boolean): readonly Extract<ViewNode, { kind: 'element' }>[] {
  const out: Extract<ViewNode, { kind: 'element' }>[] = []
  const walk = (node: ViewNode): void => {
    if (node.kind === 'text') return
    if (predicate(node)) out.push(node)
    node.children.forEach(walk)
  }
  walk(root)
  return out
}

describe('keyboard focus order derived from the model', () => {
  const state = stateWith({
    list: ready([summaryOf()]),
    selection: 'def-1',
    detail: { status: 'ready', data: detailOf(), failure: null, requestStamp: TARGET, absence: null },
  })
  const view = buildSettingsView(state)

  it('no focusable node uses a positive tabIndex, so document order is the tab order', () => {
    expect(hasPositiveTabIndex(view.root)).toBe(false)
    expect(view.focusOrder.length).toBeGreaterThan(0)
    expect(view.focusOrder).toEqual(collectFocusKeys(view.root))
  })

  it('list → diff → back keeps the same focus order (返回焦点稳定)', () => {
    const before = buildSettingsView(state).focusOrder
    const opened = reduce(state, {
      type: 'dialog/open',
      dialog: { kind: 'revision-diff', definitionId: 'def-1', from: 1, to: 2, lines: [{ kind: 'added', text: 'x' }] },
    })
    const diffView = buildSettingsView(opened)
    // the diff view itself is keyboard reachable
    expect(diffView.focusOrder).toContain('dialog:back')
    expect(diffView.focusOrder).toContain('dialog:close')
    const closed = reduce(opened, { type: 'dialog/close' })
    expect(buildSettingsView(closed).focusOrder).toEqual(before)
  })

  it('row selection controls come before the detail controls, in row order', () => {
    const order = view.focusOrder
    const rowIndex = order.indexOf('row:def-1:select')
    const diffIndex = order.indexOf('detail:act-diff')
    expect(rowIndex).toBeGreaterThanOrEqual(0)
    expect(diffIndex).toBeGreaterThan(rowIndex)
  })

  it('a filter button is reachable and announces its pressed state', () => {
    const filters = findNodes(view.root, n => n.attrs['data-action'] === 'filter-origin')
    expect(filters).toHaveLength(5)
    expect(filters.filter(f => f.attrs['aria-pressed'] === true)).toHaveLength(1)
    expect(filters.every(f => f.attrs.tabIndex === 0)).toBe(true)
  })
})

describe('aria-shaped attributes on the render output', () => {
  it('rows are listbox options with aria-selected', () => {
    const view = buildSettingsView(stateWith({ list: ready([summaryOf(), summaryOf({ definitionId: 'def-2' })]), selection: 'def-2' }))
    const options = findNodes(view.root, n => n.attrs.role === 'option')
    expect(options).toHaveLength(2)
    expect(options.find(o => o.attrs['data-row-id'] === 'def-2')?.attrs['aria-selected']).toBe(true)
    expect(options.find(o => o.attrs['data-row-id'] === 'def-1')?.attrs['aria-selected']).toBe(false)
  })

  it('loading uses role=status + aria-busy, error uses role=alert with the code', () => {
    const loading = buildSettingsView(stateWith({ list: { status: 'loading', data: null, failure: null, requestStamp: TARGET, absence: null } }))
    expect(findNodes(loading.root, n => n.attrs['data-state'] === 'loading')[0]?.attrs).toMatchObject({ role: 'status', 'aria-busy': true })
    const errored = buildSettingsView(stateWith({
      list: { status: 'error', data: null, failure: { code: 'ADAPTER_MISSING', detail: '没有适配器' }, requestStamp: TARGET, absence: null },
    }))
    const alert = findNodes(errored.root, n => n.attrs['data-state'] === 'error')[0]
    expect(alert?.attrs.role).toBe('alert')
    expect(JSON.stringify(alert)).toContain('ADAPTER_MISSING')
  })

  it('an unobserved fact has no glyph while observed facts do', () => {
    expect(factGlyph('unknown')).toBe('?')
    const view = buildSettingsView(stateWith({ list: ready([summaryOf()]) }))
    const unknownNodes = findNodes(view.root, n => n.attrs['data-tone'] === 'unknown' && typeof n.attrs['data-fact'] === 'string')
    expect(unknownNodes.length).toBeGreaterThan(0)
    expect(unknownNodes.every(n => n.attrs['data-glyph'] === '')).toBe(true)
    expect(unknownNodes.every(n => !JSON.stringify(n.children).includes('✓') && !JSON.stringify(n.children).includes('✗'))).toBe(true)
  })
})

describe('capability truthfulness (FR07 / per-pin facts)', () => {
  it('unknown and no are different labels, different tones and different attrs', () => {
    expect(factLabel('loaded', 'unknown')).not.toBe(factLabel('loaded', false))
    expect(factLabel('loaded', 'unknown')).toContain('未验证')
    expect(factLabel('loaded', false)).toBe('未装载')
    expect(factLabel('loaded', true)).toBe('已装载')
  })

  it('extension-backed and unknown are distinct visible states', () => {
    expect(SUPPORT_WORDING['extension-backed']).not.toBe(SUPPORT_WORDING.unknown)
    const view = buildSettingsView(stateWith({ list: ready([summaryOf()]) }))
    const supports = findNodes(view.root, n => typeof n.attrs['data-support'] === 'string').map(n => n.attrs['data-support'])
    expect(new Set(supports)).toEqual(new Set(['native', 'extension-backed', 'unsupported']))
    expect(supports).not.toContain('unknown')
    // an absent fact set still renders as unknown rather than a false cross
    const bare = buildSettingsView(stateWith({
      list: ready([summaryOf({ capabilities: [{ harnessId: 'claude', support: 'unknown', facts: {} }] })]),
    }))
    const cell = findNodes(bare.root, n => n.attrs['data-support'] === 'unknown')
    expect(cell).toHaveLength(1)
    expect(JSON.stringify(cell[0])).toContain('未验证')
  })

  it('nothing merely stored ever reads as 已生效', () => {
    const view = buildSettingsView(stateWith({ list: ready([summaryOf()]) }))
    expect(view.strings.join('|')).not.toContain('已生效')
    // and the same holds for every archive/publish/restore wording the UI can produce
    for (const dialog of [
      { kind: 'archive' as const, definitionId: 'def-1', effectText: 'text', pinned: [] },
      { kind: 'publish-revision' as const, definitionId: 'def-1', nonMovementText: 'text', pinned: [] },
      { kind: 'restore' as const, definitionId: 'def-1' },
      { kind: 'clone' as const, definitionId: 'def-1', revision: 1 },
    ]) {
      const opened = reduce(stateWith({ list: ready([summaryOf()]) }), { type: 'dialog/open', dialog })
      expect(buildSettingsView(opened).strings.join('|'), JSON.stringify(dialog)).not.toContain('已生效')
    }
  })

  it('the stored-only badge names what is NOT yet true', () => {
    const badge = rowStatusBadge({
      id: 'def-1', kind: 'managed', origin: 'mine', displayName: 'x', slug: 'x', archived: false,
      latestRevision: 1, lastApprovedSource: null, readOnly: false, brands: [], native: null, disableLabel: null,
    } satisfies RowView)
    expect(badge.text).toContain('未应用')
    expect(badge.tone).toBe('stored-only')
    expect(badge.text).not.toContain('已生效')
  })

  it('a native-discovered row is labelled 非 Ordessa 管理 and never claims management', () => {
    const state = stateWith({
      originFilter: 'native-discovered',
      selection: 'native:project:project-reviewer',
      native: { status: 'ready', data: { state: 'observed', observations: [nativeOf()] }, failure: null, requestStamp: TARGET, absence: null },
    })
    const view = buildSettingsView(state)
    expect(view.strings.join('|')).toContain('非 Ordessa 管理')
    expect(findNodes(view.root, n => n.attrs['data-managed'] === 'false')).toHaveLength(1)
    expect(findNodes(view.root, n => n.attrs['data-disable'] === 'not-possible')).toHaveLength(1)
    expect(view.strings.join('|')).not.toContain('已禁用')
  })
})

describe('service absence (§C2) is explained, never a spinner or a failed card', () => {
  const absent: SettingsState = {
    ...base(),
    serviceAvailable: false,
    list: { status: 'absent', data: null, failure: null, requestStamp: null, absence: { reason: '未接线', missing: 'wire 方法', owner: 'C0 foundation' } },
    native: { status: 'absent', data: null, failure: null, requestStamp: null, absence: { reason: '未接线', missing: 'wire 方法', owner: 'C0 foundation' } },
    detail: { status: 'absent', data: null, failure: null, requestStamp: null, absence: { reason: '未接线', missing: 'wire 方法', owner: 'C0 foundation' } },
    effective: { status: 'absent', data: null, failure: null, requestStamp: null, absence: { reason: '未接线', missing: 'wire 方法', owner: 'C0 foundation' } },
    defaults: {
      'user-global': { status: 'absent', data: null, failure: null, requestStamp: null, absence: { reason: '未接线', missing: 'wire 方法', owner: 'C0 foundation' } },
      'project': { status: 'absent', data: null, failure: null, requestStamp: null, absence: { reason: '未接线', missing: 'wire 方法', owner: 'C0 foundation' } },
    },
  }

  it('each absent region names its reason, the missing item and its owner', () => {
    const view = buildSettingsView(absent)
    const regions = findNodes(view.root, n => n.attrs['data-state'] === 'absent')
    expect(regions.length).toBeGreaterThanOrEqual(5)
    expect(view.strings.join('|')).toContain('缺失项：wire 方法')
    expect(view.strings.join('|')).toContain('归属：C0 foundation')
  })

  it('no region is left spinning, and no "plugin failed" card wording appears', () => {
    const view = buildSettingsView(absent)
    expect(findNodes(view.root, n => n.attrs['aria-busy'] === true)).toHaveLength(0)
    const text = view.strings.join('|')
    expect(text).not.toMatch(/插件故障|plugin failed|加载失败，请联系/)
    expect(text).toContain('定义服务：未接线')
  })
})

describe('legacy dispatch surface stays out (legacy-inventory-matrix §1)', () => {
  it('none of the forbidden legacy symbols or labels appear in the rendered strings', () => {
    const state = stateWith({ list: ready([summaryOf()]), selection: 'def-1', detail: { status: 'ready', data: detailOf(), failure: null, requestStamp: TARGET, absence: null } })
    const text = buildSettingsView(state).strings.join('|')
    for (const forbidden of ['run_subagent', 'list_subagents', 'subagentGrants', 'grant_subagent', 'revoke_subagent', 'resolve_roster', 'DelegationService', 'inline_available', 'check_cycle', 'MAX_ROSTER_ENTRIES']) {
      expect(text, forbidden).not.toContain(forbidden)
    }
    expect(text).not.toMatch(/派工|授权边|roster/i)
  })

  it('the definition-library vocabulary is present instead', () => {
    const text = buildSettingsView(stateWith({ list: ready([summaryOf()]) })).strings.join('|')
    expect(text).toContain('子代理定义库')
    expect(text).toContain('assets.native-subagents')
  })
})
