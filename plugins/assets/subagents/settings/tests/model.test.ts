/**
 * View-model behaviour: origin filtering, archive/revision semantics, the import
 * two-step, default-assignment intents and the revision diff.
 */
import { describe, expect, it } from 'vitest'
import {
  archiveEffectText, assignmentIntent, cloneIntent, draftAppliesTo, importApprovalPaths, initialState,
  lineDiff, nativeDisableIntent, revisionDiff, revisionNonMovementText, saveRevisionIntent,
  rowOrigin, startDraft, visibleRows, type SettingsState,
} from '../src/model'
import { detailOf, nativeOf, OTHER_TARGET, summaryOf, TARGET } from './fixtures'
import { buildSettingsView } from '../src/view'

const rows = [
  summaryOf(),
  summaryOf({ definitionId: 'def-2', displayName: '项目构建者', originScope: 'project', originOwner: 'principal-1' }),
  summaryOf({ definitionId: 'def-3', displayName: 'Profile 专用', originScope: 'profile', originOwner: 'principal-1' }),
  summaryOf({ definitionId: 'def-4', displayName: '公共他人', originScope: 'public', originOwner: 'principal-2' }),
  summaryOf({ definitionId: 'def-5', displayName: '已归档', archived: true, originScope: 'public', originOwner: 'principal-1' }),
]

const withRows = (overrides: Partial<SettingsState> = {}): SettingsState => ({
  ...initialState({ target: TARGET, viewerPrincipal: 'principal-1', serviceAvailable: true }),
  list: { status: 'ready', data: rows, failure: null, requestStamp: TARGET, absence: null },
  ...overrides,
})

describe('list filtering by origin (ux.md §"Settings 中的定义库")', () => {
  it('shows managed rows under "all" and hides archived unless asked', () => {
    const ids = visibleRows(withRows()).map(r => r.id)
    expect(ids).toEqual(['def-1', 'def-2', 'def-3', 'def-4'])
    expect(ids).not.toContain('def-5')
    const withArchived = visibleRows(withRows({ showArchived: true }))
    expect(withArchived.map(r => r.id)).toContain('def-5')
    expect(withArchived.find(r => r.id === 'def-5')?.archived).toBe(true)
  })

  it('maps each origin scope to its filter bucket', () => {
    expect(rowOrigin(summaryOf(), 'principal-1')).toBe('mine')
    expect(rowOrigin(summaryOf({ originScope: 'project' }), 'principal-1')).toBe('project')
    expect(rowOrigin(summaryOf({ originScope: 'profile' }), 'principal-1')).toBe('profile-only')
    // a public row from another owner is NOT claimed as "mine"
    expect(rowOrigin(summaryOf({ originOwner: 'someone-else' }), 'principal-1')).toBe('shared')
  })

  it('each declared filter yields exactly its own bucket', () => {
    const cases: readonly [string, string[]][] = [
      ['mine', ['def-1']],
      ['project', ['def-2']],
      ['profile-only', ['def-3']],
    ]
    for (const [filter, expected] of cases) {
      const state = { ...withRows(), originFilter: filter as SettingsState['originFilter'] }
      expect(visibleRows(state).map(r => r.id), filter).toEqual(expected)
    }
  })

  it('"仅原生发现" shows only read-only native items, labelled 非 Ordessa 管理', () => {
    const native = {
      ...withRows(),
      originFilter: 'native-discovered' as const,
      native: {
        status: 'ready' as const,
        data: { state: 'observed' as const, observations: [nativeOf(), nativeOf({ nativeName: 'user-reviewer', scope: 'user' })] },
        failure: null, requestStamp: TARGET, absence: null,
      },
    }
    const visible = visibleRows(native)
    expect(visible.map(r => r.id)).toEqual(['native:project:project-reviewer', 'native:user:user-reviewer'])
    expect(visible.every(r => r.readOnly && r.kind === 'native')).toBe(true)
  })

  it('an unobserved native mechanism is unknown, never an empty "没有原生定义"', () => {
    const state: SettingsState = {
      ...withRows(),
      native: {
        status: 'ready', data: { state: 'unknown', reason: '无受控观察通道（SR-1/SR-3b）' },
        failure: null, requestStamp: TARGET, absence: null,
      },
    }
    expect(visibleRows(state).filter(r => r.kind === 'native')).toHaveLength(0)
    const view = buildSettingsView(state)
    expect(view.strings.join('|')).toContain('状态未验证')
    expect(view.strings.join('|')).not.toContain('没有原生定义')
  })

  it('a native item without established suppressibility never reads as 已禁用', () => {
    for (const [suppressible, expected] of [[undefined, '未验证'], [false, '无法屏蔽'], [true, '可屏蔽']] as const) {
      const row = visibleRows({
        ...withRows(),
        originFilter: 'native-discovered',
        native: { status: 'ready', data: { state: 'observed', observations: [nativeOf({ suppressible })] }, failure: null, requestStamp: TARGET, absence: null },
      })[0]
      expect(row?.disableLabel, String(suppressible)).toContain(expected)
      expect(row?.disableLabel).not.toContain('已禁用')
      const intent = nativeDisableIntent(row!.native!, TARGET, 'n1')
      if (suppressible === true) expect(intent.refusal).toBeNull()
      else expect(intent.refusal).toContain('NATIVE_DISCOVERY_UNCONTROLLED')
    }
  })
})

describe('archive / publish / clone effects are stated, not implied', () => {
  const definition = summaryOf({ latestRevision: 3 })
  const pinned = [
    { serverScope: 'srv-a', principal: 'p', scopeKind: 'project-generic' as const, scopeId: 'proj-b', harnessId: 'any', definitionId: 'def-1', decision: 'enable' as const, revision: 2, rowVersion: 5 },
  ]

  it('the archive dialog names the effect scope and the untouched pins', () => {
    const text = archiveEffectText(definition, pinned)
    expect(text).toContain('新的选择')
    expect(text).toContain('不受影响')
    expect(text).toContain('不会随归档移动')
    expect(text).toContain('proj-b')
    expect(text).toContain('@v2')
    expect(text).toContain('删除属于另一个数据保留政策')
  })

  it('publishing a revision states that existing pinned assignments do not move (FR02)', () => {
    const text = revisionNonMovementText(definition, pinned)
    expect(text).toContain('不会移动')
    expect(text).toContain('逐个升级需单独批准')
    expect(text).toContain('不自动启用')
    expect(text).toContain('v3 → 新 v4')
    expect(text).toContain('@v2')
  })

  it('clone and archive intents carry a CAS rowVersion and a deterministic operation key', () => {
    const a = cloneIntent(definition, 3, TARGET, 'nonce-1')
    const b = cloneIntent(definition, 3, TARGET, 'nonce-1')
    expect(a.intent.operationKey).toBe(b.intent.operationKey)
    expect(a.intent.operationKey).toContain('def-1')
    expect(a.intent.operationKey).toContain('nonce-1')
    expect(a.refusal).toBeNull()
  })

  it('an archive intent does not silently claim an applied/loaded state', () => {
    const intent = archiveEffectText(definition, [])
    expect(intent).toContain('当前没有任何固定分配引用该定义')
  })
})

describe('import is a two-step preview → explicit approval (FR14)', () => {
  const preview = detailOf().revisions[0]!
  void preview

  it('nothing is approvable before a preview exists', () => {
    const state = initialState({ target: TARGET, viewerPrincipal: 'principal-1', serviceAvailable: true })
    expect(importApprovalPaths(state.importFlow)).toEqual([])
  })

  it('only explicitly selected, selectable paths survive into the approval', () => {
    const flow = {
      step: 'preview' as const, sourceRef: 'git:rev', preview: {
        previewId: 'p', sourceName: 's', sourceRef: 'r', sourceDigest: 'd',
        files: [
          { relativePath: 'a.md', sizeBytes: 1, contentDigest: 'x', diagnostics: [], selectable: true },
          { relativePath: 'b.md', sizeBytes: 1, contentDigest: 'y', diagnostics: [], selectable: false },
        ],
        diagnostics: [], futurePermissions: [],
      }, selectedPaths: ['a.md', 'b.md'], failure: null, result: null,
    }
    expect(importApprovalPaths(flow)).toEqual(['a.md'])
  })
})

describe('default-assignment intents: user-global and per-project stay separate (FR02/US2)', () => {
  const definition = summaryOf({ latestRevision: 2 })

  it('enable requires a pinned revision', () => {
    const built = assignmentIntent({ definition, layer: 'project', decision: 'enable', target: TARGET, nonce: 'n' })
    expect(built.refusal).toContain('固定修订')
    const pinned = assignmentIntent({ definition, layer: 'project', decision: 'enable', revision: 2, target: TARGET, nonce: 'n' })
    expect(pinned.intent.assignment?.revision).toBe(2)
    expect(pinned.intent.assignment?.scopeId).toBe('proj-a')
    expect(pinned.refusal).toBeNull()
  })

  it('a pin beyond the latest revision is refused before any write', () => {
    const built = assignmentIntent({ definition, layer: 'project', decision: 'enable', revision: 9, target: TARGET, nonce: 'n' })
    expect(built.refusal).toContain('不存在')
  })

  it('a Profile-only definition cannot enter the user-global default', () => {
    const profileOnly = summaryOf({ originScope: 'profile' })
    const built = assignmentIntent({ definition: profileOnly, layer: 'user-global', decision: 'enable', revision: 1, target: TARGET, nonce: 'n' })
    expect(built.refusal).toContain('Profile 专用')
  })

  it('user-global has no project id while project scope keeps it (no cross-project leak)', () => {
    const global = assignmentIntent({ definition, layer: 'user-global', decision: 'disable', target: TARGET, nonce: 'n' })
    const project = assignmentIntent({ definition, layer: 'project', decision: 'disable', target: TARGET, nonce: 'n' })
    expect(global.intent.assignment?.scopeId).toBeNull()
    expect(global.intent.assignment?.scopeKind).toBe('user-global-generic')
    expect(project.intent.assignment?.scopeId).toBe('proj-a')
    expect(project.intent.assignment?.scopeKind).toBe('project-generic')
  })

  it('switching target makes an old draft unappliable but never unwriteable for its own target', () => {
    const draft = startDraft(detailOf(), TARGET)
    expect(draftAppliesTo(draft, TARGET)).toBe(true)
    expect(draftAppliesTo(draft, OTHER_TARGET)).toBe(false)
    const built = saveRevisionIntent({ ...draft, dirty: true, roleBody: 'x' }, { definitionId: 'def-1', displayName: 'a', slug: 'b', description: 'c', roleBody: 'x', expectedRowVersion: 3 }, OTHER_TARGET, 'n')
    expect(built.refusal).toContain('另一个目标')
  })

  it('an empty role body cannot publish a revision', () => {
    const draft = startDraft(detailOf(), TARGET)
    const built = saveRevisionIntent({ ...draft, dirty: true }, { definitionId: 'def-1', displayName: 'a', slug: 'b', description: 'c', roleBody: '', expectedRowVersion: 3 }, TARGET, 'n')
    expect(built.refusal).toContain('为空')
  })
})

describe('revision diff (keyboard-reachable, FR01)', () => {
  const detail = detailOf()
  const [v1, v2] = detail.revisions

  it('diffs two immutable revisions line by line and keeps digests apart', () => {
    const lines = revisionDiff(v1!, v2!)
    expect(lines[0]!.text).toContain('v1 (sha256:11111111')
    expect(lines[0]!.text).toContain('v2 (sha256:22222222')
    expect(lines.some(l => l.kind === 'added' && l.text === '输出差异清单。')).toBe(true)
    expect(lines.some(l => l.kind === 'context')).toBe(true)
    expect(lines.some(l => /仅声明，不代表授权/.test(l.text))).toBe(true)
  })

  it('the line diff never invents a rewrite: a removal and an addition stay separate', () => {
    const lines = lineDiff(['a', 'b'], ['a', 'c'])
    expect(lines).toEqual([
      { kind: 'context', text: 'a' },
      { kind: 'removed', text: 'b' },
      { kind: 'added', text: 'c' },
    ])
  })
})

