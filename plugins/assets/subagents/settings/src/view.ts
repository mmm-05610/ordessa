/**
 * Pure render model for the Settings definition library.
 *
 * This module turns `model.ts` state into a tree of plain data nodes carrying
 * `aria`-shaped attributes and an unambiguous focus order. It is DOM-free and
 * React-free on purpose: the accessibility/keyboard claims in
 * `docs/design/native-subagents/ux.md` §"交互验收" can only be *asserted* where
 * they are provable headlessly, and this file is where they are provable:
 *
 *  - focus order is derived by document-order traversal, and every focusable
 *    node uses `tabIndex: 0` (no positive index anywhere), so
 *    `collectFocusKeys()` **is** the sequential keyboard order;
 *  - `unknown` / `extension-backed` / refused items get distinct `data-*`
 *    states and distinct text, which the tests read directly;
 *  - no node ever carries raw HTML.
 *
 * What is NOT provable here (900×600 geometry, 200% zoom, real screen-reader
 * output, focus-ring visibility) is recorded as untested in the task report.
 */
import type {
  AssignmentView, BrandCapability, CapabilityDeclaration, DefinitionDetail, EffectiveSet, FactValue,
  OriginFilter, ResourceRef, TargetStamp,
} from './contract'
import { CAPABILITY_FACTS } from './contract'
import type { DiffLine, Draft, ImportFlow, Notice, RowView, SettingsState, Slice } from './model'
import { importApprovalPaths, nativeUnknownReason, revisionDiff, selectedRow, visibleRows } from './model'
import type { SafeBlock, SafeInline } from './sanitize'
import { safePreview } from './sanitize'

// ---------------------------------------------------------------------------
// Node shapes
// ---------------------------------------------------------------------------

export type ViewAttrs = Record<string, string | number | boolean | undefined>

export interface ViewElement {
  readonly kind: 'element'
  readonly tag: string
  readonly key: string
  readonly attrs: ViewAttrs
  readonly children: readonly ViewNode[]
}

export type ViewNode =
  | { readonly kind: 'text'; readonly text: string }
  | ViewElement

export function txt(text: string): ViewNode {
  return { kind: 'text', text }
}

export function el(tag: string, key: string, attrs: ViewAttrs, children: readonly ViewNode[]): ViewNode {
  return { kind: 'element', tag, key, attrs, children }
}

const FOCUSABLE_TAGS = new Set(['button', 'a', 'input', 'select', 'textarea'])

export function isFocusable(node: ViewNode): boolean {
  if (node.kind !== 'element') return false
  if (node.attrs.tabIndex === -1) return false
  if (node.attrs.hidden === true) return false
  return FOCUSABLE_TAGS.has(node.tag) || node.attrs.tabIndex === 0
}

function asNodeList(root: ViewNode | readonly ViewNode[]): readonly ViewNode[] {
  return typeof (root as ViewNode).kind === 'string' ? [root as ViewNode] : root as readonly ViewNode[]
}

/** Document-order traversal == sequential focus order (all indexes are 0). */
export function collectFocusKeys(root: ViewNode | readonly ViewNode[]): readonly string[] {
  const out: string[] = []
  const walk = (node: ViewNode): void => {
    if (node.kind === 'text') return
    if (isFocusable(node)) out.push(node.key)
    node.children.forEach(walk)
  }
  asNodeList(root).forEach(walk)
  return out
}

/** Guard: a positive tabIndex would make the derived order a lie. */
export function hasPositiveTabIndex(root: ViewNode | readonly ViewNode[]): boolean {
  let found = false
  const walk = (node: ViewNode): void => {
    if (node.kind === 'text') return
    if (typeof node.attrs.tabIndex === 'number' && node.attrs.tabIndex > 0) found = true
    node.children.forEach(walk)
  }
  asNodeList(root).forEach(walk)
  return found
}

export function collectStrings(nodes: readonly ViewNode[]): readonly string[] {
  const out: string[] = []
  const walk = (node: ViewNode): void => {
    if (node.kind === 'text') out.push(node.text)
    else {
      for (const [k, v] of Object.entries(node.attrs)) if (typeof v === 'string') out.push(`${k}=${v}`)
      node.children.forEach(walk)
    }
  }
  nodes.forEach(walk)
  return out
}

// ---------------------------------------------------------------------------
// Truthful labels (FR07, data-model §状态和迁移)
// ---------------------------------------------------------------------------

interface FactWording {
  readonly yes: string
  readonly no: string
  readonly unknown: string
}

export const FACT_WORDING: Record<(typeof CAPABILITY_FACTS)[number], FactWording> = {
  stored: { yes: '已保存', no: '未保存', unknown: '保存状态未验证' },
  selected: { yes: '已解析选中', no: '未选中', unknown: '选中状态未验证' },
  projected: { yes: '已投射到目标', no: '未投射', unknown: '投射状态未验证' },
  loaded: { yes: '已装载', no: '未装载', unknown: '装载未验证（无观测机制）' },
  invokable: { yes: '已确认可调用', no: '不可调用', unknown: '可调用性未验证' },
  used: { yes: '已发生调用', no: '未观察到调用', unknown: '调用未验证' },
}

export const SUPPORT_WORDING: Record<BrandCapability['support'], string> = {
  native: '原生',
  'extension-backed': 'extension-backed（依赖扩展）',
  unsupported: '不支持',
  unknown: '未验证',
}

/** Tone is a *rendering* decision, never a truth claim. */
export type FactTone = 'yes' | 'no' | 'unknown'

export function factTone(value: FactValue | undefined): FactTone {
  if (value === true) return 'yes'
  if (value === false) return 'no'
  return 'unknown'
}

export function factLabel(fact: (typeof CAPABILITY_FACTS)[number], value: FactValue | undefined): string {
  return FACT_WORDING[fact][factTone(value)]
}

/** Glyphs exist only for observed yes/no; `unknown` never gets a check or a cross. */
export function factGlyph(tone: FactTone): string {
  return tone === 'yes' ? '✓' : tone === 'no' ? '✗' : '?'
}

// ---------------------------------------------------------------------------
// Safe rendering of the markdown data tree
// ---------------------------------------------------------------------------

export function renderInline(inline: readonly SafeInline[], keyPrefix: string, index: number): ViewNode {
  const node = inline[index]
  if (!node) return txt('')
  const key = `${keyPrefix}:${index}`
  switch (node.kind) {
    case 'text': return txt(node.text)
    case 'code': return el('code', key, {}, [txt(node.text)])
    case 'strong': return el('strong', key, {}, renderChildren(node.children, key))
    case 'em': return el('em', key, {}, renderChildren(node.children, key))
    case 'link': return el('a', `${key}:a`, { href: node.href, rel: 'noopener noreferrer', tabIndex: 0 }, renderChildren(node.children, `${key}:c`))
  }
}

function renderChildren(children: readonly SafeInline[], keyPrefix: string): readonly ViewNode[] {
  return children.map((_, i) => renderInline(children, keyPrefix, i))
}

export function renderSafeBlocks(blocks: readonly SafeBlock[], keyPrefix: string): readonly ViewNode[] {
  return blocks.map((block, i) => {
    const key = `${keyPrefix}:b${i}`
    switch (block.kind) {
      case 'heading': return el(`h${block.level + 2}`, key, { 'data-safe-markdown': 'heading' }, [renderInline(block.children, key, 0)])
      case 'paragraph': return el('p', key, {}, block.children.map((_, j) => renderInline(block.children, key, j)))
      case 'list': return el('ul', key, {}, block.items.map((item, j) => el('li', `${key}:li${j}`, {}, item.map((_, k) => renderInline(item, `${key}:li${j}`, k)))))
      case 'code-block': return el('pre', key, { 'data-safe-markdown': 'code-block' }, [txt(block.text)])
    }
  })
}

// ---------------------------------------------------------------------------
// Section-level pieces
// ---------------------------------------------------------------------------

const FILTERS: readonly { readonly value: OriginFilter; readonly label: string }[] = [
  { value: 'all', label: '全部' },
  { value: 'mine', label: '我的' },
  { value: 'project', label: '项目' },
  { value: 'profile-only', label: 'Profile 专用' },
  { value: 'native-discovered', label: '仅原生发现' },
]

export function targetIdentityNode(target: TargetStamp, key = 'target'): ViewNode {
  const cells: readonly string[] = [
    `Server=${target.serverId}`,
    `项目=${target.projectId ?? '（无）'}`,
    `Profile=${target.profileId ?? '（无）'}`,
    `会话=${target.sessionId ?? '（无）'}`,
    `目标修订=${target.revision}`,
    `providerGeneration=${target.providerGeneration}`,
  ]
  return el('div', key, { role: 'group', 'aria-label': '当前目标', 'data-target-revision': String(target.revision) },
    cells.map((c, i) => el('span', `${key}:c${i}`, { 'data-target-cell': c.split('=')[0] ?? '' }, [txt(c)])))
}

function sliceStateNode<T>(slice: Slice<T>, key: string, subject: string): ViewNode | null {
  switch (slice.status) {
    case 'idle':
      return null
    case 'loading':
      // A loading state always names its subject and is announced politely.
      return el('p', `${key}:loading`, { role: 'status', 'aria-live': 'polite', 'aria-busy': true, 'data-state': 'loading' }, [txt(`${subject}加载中…`)])
    case 'error':
      return el('div', `${key}:error`, { role: 'alert', 'data-state': 'error', 'data-error-code': slice.failure?.code ?? 'OPERATION_UNKNOWN' }, [
        txt(`${subject}读取失败`),
        el('span', `${key}:error:code`, { 'data-error-code': slice.failure?.code ?? 'OPERATION_UNKNOWN' }, [txt(slice.failure?.code ?? 'OPERATION_UNKNOWN')]),
        el('span', `${key}:error:detail`, {}, [txt(slice.failure?.detail ?? '服务未给出原因')]),
        el('button', `${key}:error:retry`, { type: 'button', tabIndex: 0, 'data-action': 'retry', 'aria-label': `重试加载${subject}` }, [txt('重试')]),
      ])
    case 'absent':
      // §C2: an explained absence — never a spinner, never a "plugin failed" card.
      return el('section', `${key}:absent`, { role: 'region', 'aria-label': `${subject}不可用说明`, 'data-state': 'absent' }, [
        el('h4', `${key}:absent:title`, {}, [txt(`${subject}暂不可用`)]),
        el('p', `${key}:absent:reason`, {}, [txt(slice.absence?.reason ?? '未提供原因')]),
        el('p', `${key}:absent:missing`, { 'data-gap': 'true' }, [txt(`缺失项：${slice.absence?.missing ?? '未说明'}`)]),
        el('p', `${key}:absent:owner`, { 'data-gap': 'true' }, [txt(`归属：${slice.absence?.owner ?? '未说明'}`)]),
      ])
    case 'ready':
      return null
  }
}

function capabilityCellNode(brand: BrandCapability, rowId: string): ViewNode {
  const key = `cap:${rowId}:${brand.harnessId}`
  const children: ViewNode[] = [
    el('span', `${key}:brand`, { 'data-brand': brand.harnessId }, [txt(brand.harnessId)]),
    el('span', `${key}:support`, {
      'data-support': brand.support,
      'aria-label': `目标适用性：${SUPPORT_WORDING[brand.support]}`,
    }, [txt(SUPPORT_WORDING[brand.support])]),
  ]
  if (brand.targetVersion) children.push(el('span', `${key}:version`, { 'data-target-version': brand.targetVersion }, [txt(`v${brand.targetVersion}`)]))
  for (const fact of CAPABILITY_FACTS) {
    const value = brand.facts[fact]
    const tone = factTone(value)
    const label = factLabel(fact, value)
    children.push(el('span', `${key}:fact:${fact}`, {
      'data-fact': fact,
      'data-tone': tone,
      'data-truth': value === true ? 'observed-yes' : value === false ? 'observed-no' : 'unobserved',
      'aria-label': `${fact}：${label}`,
      // An unobserved fact gets no glyph at all: a check or a cross would both
      // be a truth claim the pin has no evidence for.
      'data-glyph': tone === 'unknown' ? '' : factGlyph(tone),
    }, [txt(tone === 'unknown' ? `${fact}：${label}` : `${factGlyph(tone)} ${fact}：${label}`)]))
  }
  return el('div', key, { role: 'group', 'aria-label': `能力事实 ${brand.harnessId}` }, children)
}

/**
 * Row badge. `stored` alone must never read as an applied/effective state, so
 * the badge says what is true and what is not yet true.
 */
export function rowStatusBadge(row: RowView): { readonly text: string; readonly tone: 'stored-only' | 'archived' | 'read-only' | 'effective-unknown' } {
  if (row.kind === 'native') return { text: '非 Ordessa 管理（只读）', tone: 'read-only' }
  if (row.archived) return { text: '已归档（不删除已固定引用）', tone: 'archived' }
  return { text: '已保存（未应用；生效需分配与提交闸门）', tone: 'stored-only' }
}

function rowNode(row: RowView, state: SettingsState, index: number): ViewNode {
  const badge = rowStatusBadge(row)
  const selected = state.selection === row.id
  const key = `row:${row.id}`
  const cells: ViewNode[] = [
    el('span', `${key}:name`, { 'data-row-field': 'displayName' }, [txt(row.displayName)]),
    el('span', `${key}:origin`, { 'data-origin': row.origin }, [txt(originText(row))]),
    el('span', `${key}:badge`, { 'data-badge': badge.tone, 'aria-label': badge.text }, [txt(badge.text)]),
    el('span', `${key}:revision`, { 'data-row-field': 'revision' }, [txt(row.kind === 'native' ? '非受管修订' : `v${row.latestRevision}`)]),
    el('span', `${key}:source`, { 'data-row-field': 'lastApprovedSource' }, [txt(row.lastApprovedSource ?? '无批准来源记录')]),
  ]
  if (row.kind === 'native') {
    cells.push(el('span', `${key}:suppress`, { 'data-suppress': row.native?.suppressible === true ? 'yes' : row.native?.suppressible === false ? 'no' : 'unknown' }, [txt(row.disableLabel ?? '可屏蔽性未验证')]))
  } else {
    for (const brand of row.brands) cells.push(capabilityCellNode(brand, row.id))
  }
  return el('li', key, { role: 'option', 'aria-selected': selected, 'data-row-kind': row.kind, 'data-row-id': row.id }, [
    el('button', `${key}:select`, { type: 'button', tabIndex: 0, 'data-action': 'select-row', 'aria-label': `查看 ${row.displayName}` }, cells),
    el('span', `${key}:order`, { 'data-order': String(index), hidden: true }, [txt('')]),
  ])
}

function originText(row: RowView): string {
  switch (row.origin) {
    case 'mine': return '我的'
    case 'project': return '项目'
    case 'profile-only': return 'Profile 专用'
    case 'native-discovered': return '仅原生发现'
    case 'shared': return '公共（他人来源）'
  }
}

// ---------------------------------------------------------------------------
// Permission / capability declaration table: requested ≠ granted
// ---------------------------------------------------------------------------

export function declarationNode(decl: CapabilityDeclaration, key: string): ViewNode {
  const tone = factTone(decl.granted)
  const over = decl.refusal !== undefined && decl.refusal !== null
  const attrs: ViewAttrs = {
    'data-decl-kind': decl.kind,
    'data-decl-name': decl.name,
    'data-requested': 'true',
    'data-granted': tone,
    'data-tone': over ? 'refused' : tone,
  }
  const children: ViewNode[] = [
    el('span', `${key}:name`, {}, [txt(decl.name)]),
    el('span', `${key}:requested`, { 'data-field': 'requested' }, [txt('请求能力')]),
    el('span', `${key}:granted`, { 'data-field': 'granted', 'aria-label': `实际授权：${tone === 'unknown' ? '未验证' : tone === 'yes' ? '已授权' : '未授权'}` },
      [txt(tone === 'unknown' ? '实际授权未验证' : tone === 'yes' ? '已授权' : '未授权')]),
  ]
  if (over && decl.refusal) {
    children.push(el('span', `${key}:refusal`, { role: 'alert', 'data-refusal-code': decl.refusal.code, 'data-tone': 'refused' }, [
      txt(`不可应用：${decl.refusal.detail}（来源：${decl.refusal.source}）`),
    ]))
  }
  return el('li', key, attrs, children)
}

/**
 * A declaration that asks for more than the ceiling is rendered as a refusal
 * with its reason, never as an approved/green item (G15 "权限项视觉假绿").
 */
export function permissionListNode(declarations: readonly CapabilityDeclaration[] | undefined, keyPrefix: string): ViewNode {
  const items = (declarations ?? []).map((d, i) => declarationNode(d, `${keyPrefix}:item:${i}`))
  return el('div', `${keyPrefix}`, { role: 'group', 'aria-label': '工具/权限声明：请求能力，不是已授权能力', 'data-notice': 'requested-not-granted' }, [
    el('h4', `${keyPrefix}:title`, {}, [txt('工具/权限（显示"请求能力"，非"已授权能力"）')]),
    items.length === 0
      ? el('p', `${keyPrefix}:empty`, { 'data-state': 'empty' }, [txt('该修订未声明工具/权限。')])
      : el('ul', `${keyPrefix}:list`, {}, items),
    el('p', `${keyPrefix}:hint`, { 'data-state': 'declaration-only' }, [txt('声明不会提升强制权限；超出上限的项在装载/运行前被拒绝，不静默收窄。')]),
  ])
}

// ---------------------------------------------------------------------------
// Defaults (user-global + per-project)
// ---------------------------------------------------------------------------

function defaultsPaneNode(state: SettingsState, key: string): ViewNode {
  const layer = (label: string, slice: Slice<readonly AssignmentView[]>, sliceKey: string) => {
    const stateNode = sliceStateNode(slice, `${sliceKey}`, `${label}默认`)
    const rows = (slice.data ?? []).map((a, i) => el('li', `${sliceKey}:row:${i}`, { 'data-assignment': `${a.scopeKind}/${a.definitionId}` }, [
      txt(`${a.scopeKind}${a.scopeId ? `=${a.scopeId}` : ''} · harness=${a.harnessId} · ${a.definitionId}${a.revision === null || a.revision === undefined ? '' : `@v${a.revision}`} → ${decisionText(a.decision)}`),
    ]))
    return el('section', `${sliceKey}`, { role: 'region', 'aria-label': `${label}默认分配` }, [
      el('h4', `${sliceKey}:title`, {}, [txt(`${label}默认`)]),
      ...(stateNode ? [stateNode] : []),
      slice.status === 'ready'
        ? rows.length === 0
          ? el('p', `${sliceKey}:empty`, { 'data-state': 'empty' }, [txt('该层没有显式决定，即继承下一层。')])
          : el('ul', `${sliceKey}:list`, {}, rows)
        : txt(''),
    ])
  }
  return el('section', key, { role: 'region', 'aria-label': '默认分配' }, [
    layer('用户全局', state.defaults['user-global'], `${key}:user-global`),
    layer('当前项目', state.defaults['project'], `${key}:project`),
    el('p', `${key}:note`, { 'data-state': 'separated' }, [txt('存内容、用户全局默认、项目默认、Profile 选择是四件分开的事。')]),
  ])
}

function decisionText(decision: AssignmentView['decision']): string {
  return decision === 'enable' ? '启用（固定修订）' : decision === 'disable' ? '排除（仅受管项）' : '继承'
}

// ---------------------------------------------------------------------------
// Import flow
// ---------------------------------------------------------------------------

function importPaneNode(flow: ImportFlow, state: SettingsState, key: string): ViewNode {
  const children: ViewNode[] = [el('h4', `${key}:title`, {}, [txt('导入（先预览，再显式批准）')])]
  children.push(el('input', `${key}:source`, { type: 'text', tabIndex: 0, 'aria-label': '导入来源（本地文件或固定 Git revision）', value: flow.sourceRef, 'data-field': 'sourceRef' }, []))
  children.push(el('button', `${key}:preview`, { type: 'button', tabIndex: 0, 'data-action': 'import-preview', disabled: flow.sourceRef === '' || !state.serviceAvailable, 'aria-label': '生成导入预览' }, [txt('预览')]))
  if (flow.step === 'previewing') children.push(el('p', `${key}:loading`, { role: 'status', 'aria-busy': true, 'data-state': 'loading' }, [txt('预览加载中…')]))
  if (flow.step === 'error' && flow.failure) {
    children.push(el('div', `${key}:error`, { role: 'alert', 'data-state': 'error', 'data-error-code': flow.failure.code }, [txt(`预览失败：${flow.failure.code} — ${flow.failure.detail}（草稿与已存内容未受影响）`)]))
  }
  if (flow.preview) {
    const p = flow.preview
    children.push(el('dl', `${key}:summary`, { 'aria-label': '来源与文件摘要' }, [
      el('dt', `${key}:src-name`, {}, [txt('来源')]), el('dd', `${key}:src-name:v`, {}, [txt(`${p.sourceName} @ ${p.sourceRef}`)]),
      el('dt', `${key}:src-digest`, {}, [txt('摘要')]), el('dd', `${key}:src-digest:v`, {}, [txt(p.sourceDigest)]),
      ...p.files.flatMap((f, i) => [
        el('dt', `${key}:file:${i}:path`, {}, [txt(f.relativePath)]),
        el('dd', `${key}:file:${i}:meta`, { 'data-selectable': String(f.selectable), 'data-digest': f.contentDigest }, [txt(`${f.sizeBytes}B；诊断：${f.diagnostics.join('；') || '无'}`)]),
      ]),
    ]))
    if (p.diagnostics.length > 0) children.push(el('ul', `${key}:diagnostics`, { 'aria-label': '格式/引用诊断' }, p.diagnostics.map((d, i) => el('li', `${key}:diag:${i}`, {}, [txt(d)]))))
    if (p.futurePermissions.length > 0) {
      children.push(el('div', `${key}:future`, { 'aria-label': '将来权限影响' }, [
        el('h5', `${key}:future:title`, {}, [txt('导入后将请求的能力（不是已授权）')]),
        el('ul', `${key}:future:list`, {}, p.futurePermissions.map((d, i) => declarationNode(d, `${key}:future:item:${i}`))),
      ]))
    }
    children.push(el('fieldset', `${key}:select`, {}, [
      el('legend', `${key}:select:legend`, {}, [txt('选择要导入的文件（只有被显式选中的内容会被复制）')]),
      ...p.files.filter(f => f.selectable).map((f, i) => el('label', `${key}:check:${i}`, {}, [
        el('input', `${key}:check:${i}:input`, { type: 'checkbox', tabIndex: 0, 'data-path': f.relativePath, checked: flow.selectedPaths.includes(f.relativePath) }, []),
        txt(f.relativePath),
      ])),
    ]))
    const approved = importApprovalPaths(flow).length > 0
    children.push(el('button', `${key}:approve`, {
      type: 'button', tabIndex: 0, 'data-action': 'import-approve', disabled: !approved,
      'aria-label': approved ? '批准导入所选文件' : '批准导入（需先选择文件）',
    }, [txt('批准导入')]))
  }
  if (flow.step === 'approved') {
    children.push(el('p', `${key}:done`, { role: 'status', 'data-state': 'approved' }, [txt(`已批准导入 ${flow.result?.length ?? 0} 个定义；存内容不等于启用。`)]))
  }
  return el('section', key, { role: 'region', 'aria-label': '导入' }, children)
}

// ---------------------------------------------------------------------------
// Dialogs
// ---------------------------------------------------------------------------

function dialogNode(state: SettingsState, key: string): ViewNode | null {
  const d = state.dialog
  switch (d.kind) {
    case 'none':
      return null
    case 'archive':
      return el('div', key, { role: 'group', 'aria-label': '归档影响范围', 'data-dialog': 'archive' }, [
        el('p', `${key}:effect`, { 'data-effect-scope': 'true' }, [txt(d.effectText)]),
        el('ul', `${key}:pinned`, {}, d.pinned.map((a, i) => el('li', `${key}:pinned:${i}`, { 'data-pin-kept': 'true' }, [txt(assignmentPinText(a))]))),
        el('button', `${key}:confirm`, { type: 'button', tabIndex: 0, 'data-action': 'confirm-archive', 'aria-label': '确认归档' }, [txt('确认归档')]),
        el('button', `${key}:cancel`, { type: 'button', tabIndex: 0, 'data-action': 'close-dialog', 'aria-label': '取消并返回' }, [txt('取消')]),
      ])
    case 'publish-revision':
      return el('div', key, { role: 'group', 'aria-label': '发布新修订的影响范围', 'data-dialog': 'publish-revision' }, [
        el('p', `${key}:non-movement`, { 'data-non-movement': 'true' }, [txt(d.nonMovementText)]),
        el('ul', `${key}:pinned`, {}, d.pinned.map((a, i) => el('li', `${key}:pinned:${i}`, { 'data-pin-kept': 'true' }, [txt(assignmentPinText(a))]))),
        el('button', `${key}:confirm`, { type: 'button', tabIndex: 0, 'data-action': 'confirm-publish', 'aria-label': '确认发布新修订' }, [txt('发布新修订')]),
        el('button', `${key}:cancel`, { type: 'button', tabIndex: 0, 'data-action': 'close-dialog', 'aria-label': '取消并返回' }, [txt('取消')]),
      ])
    case 'revision-diff':
      return el('div', key, { role: 'group', 'aria-label': `修订差异 v${d.from} → v${d.to}`, 'data-dialog': 'revision-diff' }, [
        el('button', `${key}:back`, { type: 'button', tabIndex: 0, 'data-action': 'close-dialog', 'aria-label': '返回定义列表' }, [txt('返回列表')]),
        el('ul', `${key}:lines`, {}, d.lines.map((line, i) => el('li', `${key}:line:${i}`, { 'data-diff': line.kind }, [txt(diffPrefix(line))]))),
        el('button', `${key}:close`, { type: 'button', tabIndex: 0, 'data-action': 'close-dialog', 'aria-label': '关闭差异视图' }, [txt('关闭差异')]),
      ])
    case 'clone':
      return el('div', key, { role: 'group', 'aria-label': '复制定义', 'data-dialog': 'clone' }, [
        el('p', `${key}:note`, {}, [txt('复制会生成新的 definitionId，原定义与其固定分配不变。')]),
        el('button', `${key}:confirm`, { type: 'button', tabIndex: 0, 'data-action': 'confirm-clone', 'aria-label': '确认复制' }, [txt('确认复制')]),
        el('button', `${key}:cancel`, { type: 'button', tabIndex: 0, 'data-action': 'close-dialog', 'aria-label': '取消并返回' }, [txt('取消')]),
      ])
    case 'restore':
      return el('div', key, { role: 'group', 'aria-label': '恢复定义', 'data-dialog': 'restore' }, [
        el('p', `${key}:note`, {}, [txt('恢复使该定义重新可被选择；不会自动写入任何分配。')]),
        el('button', `${key}:confirm`, { type: 'button', tabIndex: 0, 'data-action': 'confirm-restore', 'aria-label': '确认恢复' }, [txt('确认恢复')]),
        el('button', `${key}:cancel`, { type: 'button', tabIndex: 0, 'data-action': 'close-dialog', 'aria-label': '取消并返回' }, [txt('取消')]),
      ])
  }
}

function assignmentPinText(a: AssignmentView): string {
  return `${a.scopeKind}${a.scopeId ? `=${a.scopeId}` : ''} / harness=${a.harnessId} → ${a.definitionId}${a.revision === null || a.revision === undefined ? '' : `@v${a.revision}`}`
}

function diffPrefix(line: DiffLine): string {
  return line.kind === 'added' ? `+ ${line.text}` : line.kind === 'removed' ? `- ${line.text}` : `  ${line.text}`
}

// ---------------------------------------------------------------------------
// Detail pane
// ---------------------------------------------------------------------------

function detailPaneNode(state: SettingsState, key: string): ViewNode {
  const row = selectedRow(state)
  const slice = state.detail
  const stateNode = sliceStateNode(slice, `${key}:slice`, '定义详情')
  if (!row) {
    return el('section', key, { role: 'region', 'aria-label': '定义详情' }, [
      ...(stateNode ? [stateNode] : [el('p', `${key}:empty`, { 'data-state': 'empty' }, [txt('未选择定义。用上方列表的条目进入详情、预览与差异。')])]),
    ])
  }
  const detail: DefinitionDetail | null = slice.status === 'ready' ? slice.data : null
  const children: ViewNode[] = [
    el('h3', `${key}:title`, {}, [txt(row.displayName)]),
    el('p', `${key}:purpose`, {}, [txt(detail?.description ?? '用途描述待加载')]),
    el('p', `${key}:revision`, { 'data-latest-revision': String(row.latestRevision) }, [txt(`最新修订 v${row.latestRevision}`)]),
    el('p', `${key}:source`, {}, [txt(`最后批准来源：${row.lastApprovedSource ?? '无记录'}`)]),
    el('p', `${key}:archived`, { 'data-archived': String(row.archived) }, [txt(row.archived ? '已归档' : '未归档')]),
  ]

  if (row.kind === 'native') {
    children.push(el('p', `${key}:native-notice`, { role: 'status', 'data-managed': 'false', 'aria-label': '非 Ordessa 管理' }, [txt('非 Ordessa 管理（原生发现项，只读查看）')]))
    children.push(el('div', `${key}:native-disable`, { 'data-disable': row.native?.suppressible === true ? 'possible' : 'not-possible' }, [
      txt(row.disableLabel ?? '可屏蔽性未验证'),
    ]))
    children.push(el('p', `${key}:native-evidence`, {}, [txt(`来源：${row.native?.sourceCategory ?? '未知'} / ${row.native?.scope ?? '未知'}；证据：${row.native?.evidence ?? '无'}`)]))
    return el('section', key, { role: 'region', 'aria-label': '定义详情' }, children)
  }

  // per-brand facts (already in the row) restated for the detail pane
  children.push(el('div', `${key}:brands`, { role: 'group', 'aria-label': '目标版本支持事实' }, row.brands.length === 0
    ? [el('p', `${key}:brands:empty`, { 'data-state': 'unknown-only' }, [txt('无目标能力事实：全部按未验证显示。')])]
    : row.brands.map(b => capabilityCellNode(b, row.id))))

  // references (declarations, never credentials)
  const content = detail?.latestContent ?? null
  const refLine = (label: string, refs: readonly ResourceRef[] | undefined) =>
    el('p', `${key}:ref:${label}`, { 'data-reference-kind': label }, [txt(`${label}：${(refs ?? []).map(r => `${r.ownerId}${r.revision ? `@${r.revision}` : ''}`).join('、') || '未声明'}`)])
  const modelLine = (label: string, ref: ResourceRef | null | undefined) =>
    el('p', `${key}:ref:${label}`, { 'data-reference-kind': label }, [txt(`${label}：${ref ? `${ref.ownerId}${ref.revision ? `@${ref.revision}` : ''}` : '未声明'}`)])
  children.push(el('div', `${key}:refs`, { role: 'group', 'aria-label': '引用的模型/工具/MCP/Skill/运行限制' }, [
    modelLine('模型', content?.declaredModelRef),
    refLine('工具', content?.toolRefs),
    refLine('MCP', content?.mcpRefs),
    refLine('Skill', content?.skillRefs),
    el('p', `${key}:limits`, { 'data-reference-kind': 'limits' }, [txt(`运行限制：${content?.limits ? JSON.stringify(content.limits) : '未声明'}`)]),
    el('p', `${key}:isolation`, { 'data-reference-kind': 'isolation' }, [txt(`隔离：${content?.isolation ? JSON.stringify(content.isolation) : '未声明'}`)]),
    el('p', `${key}:refs-note`, { 'data-state': 'declaration-only' }, [txt('引用只是声明，由各属主授权解析；此处不显示任何秘密。')]),
  ]))

  if (content) children.push(permissionListNode(content.capabilityDeclarations, `${key}:perms`))

  // safe source preview
  const preview = safePreview(content?.roleBody ?? '')
  children.push(el('section', `${key}:preview`, { role: 'region', 'aria-label': '角色正文安全预览', 'data-preview': 'safe-markdown' }, [
    el('h4', `${key}:preview:title`, {}, [txt('角色正文（纯文本/安全 Markdown，不执行语法、不加载远程图片、不显示 secret）')]),
    ...(preview.notices.length === 0 ? [] : [el('ul', `${key}:preview:notices`, { 'aria-label': '预览已做的安全处理' }, preview.notices.map((n, i) => el('li', `${key}:preview:notice:${i}`, { 'data-preview-notice': n.kind }, [txt(n.detail)])))]),
    ...renderSafeBlocks(preview.blocks, `${key}:preview:block`),
  ]))

  // actions
  const pinned = detail?.pinnedAssignments ?? []
  children.push(el('div', `${key}:actions`, { role: 'group', 'aria-label': '定义操作' }, [
    el('button', `${key}:act-new`, { type: 'button', tabIndex: 0, 'data-action': 'draft-new', 'aria-label': '新建定义' }, [txt('创建')]),
    el('button', `${key}:act-edit`, { type: 'button', tabIndex: 0, 'data-action': 'draft-open', 'aria-label': '编辑此定义（打开草稿）' }, [txt('编辑')]),
    el('button', `${key}:act-clone`, { type: 'button', tabIndex: 0, 'data-action': 'open-clone', 'aria-label': '复制此定义' }, [txt('复制')]),
    el('button', `${key}:act-diff`, { type: 'button', tabIndex: 0, 'data-action': 'open-diff', 'aria-label': '预览修订差异', disabled: (detail?.revisions.length ?? 0) < 2 }, [txt('预览差异')]),
    el('button', `${key}:act-publish`, { type: 'button', tabIndex: 0, 'data-action': 'open-publish', 'aria-label': '发布新修订' }, [txt('发布新修订')]),
    el('button', `${key}:act-archive`, { type: 'button', tabIndex: 0, 'data-action': 'open-archive', 'aria-label': '归档此定义' }, [txt('归档')]),
    el('span', `${key}:act-pin-count`, { 'data-pinned-count': String(pinned.length) }, [txt(`${pinned.length} 个固定分配不受影响`)]),
  ]))

  // draft editor
  const draft: Draft | null = state.draft
  children.push(el('div', `${key}:draft`, { role: 'group', 'aria-label': '编辑草稿', 'data-draft-dirty': String(draft?.dirty ?? false) }, [
    el('h4', `${key}:draft:title`, {}, [txt('编辑草稿（存内容不自动启用）')]),
    el('input', `${key}:draft:displayName`, { type: 'text', tabIndex: 0, 'aria-label': '名称', value: draft?.displayName ?? '', 'data-field': 'displayName' }, []),
    el('input', `${key}:draft:slug`, { type: 'text', tabIndex: 0, 'aria-label': 'slug', value: draft?.slug ?? '', 'data-field': 'slug' }, []),
    el('textarea', `${key}:draft:description`, { tabIndex: 0, 'aria-label': '用途描述', 'data-field': 'description' }, [txt(draft?.description ?? '')]),
    el('textarea', `${key}:draft:roleBody`, { tabIndex: 0, 'aria-label': '角色正文', 'data-field': 'roleBody' }, [txt(draft?.roleBody ?? '')]),
    el('button', `${key}:draft:save`, { type: 'button', tabIndex: 0, 'data-action': 'save-draft', 'aria-label': '保存为新修订' }, [txt('保存为新修订')]),
    el('button', `${key}:draft:discard`, { type: 'button', tabIndex: 0, 'data-action': 'discard-draft', 'aria-label': '放弃草稿（唯一会清空草稿的动作）' }, [txt('放弃草稿')]),
    el('p', `${key}:draft:note`, { 'data-state': 'draft-preserved' }, [txt('错误、关闭对话框或切换目标都不会清空本草稿；只有"放弃草稿"会。')]),
  ]))

  // defaults on this definition
  const definition = detail ?? null
  children.push(el('div', `${key}:assign`, { role: 'group', 'aria-label': '默认分配' }, definition === null
    ? [el('p', `${key}:assign:empty`, { 'data-state': 'loading' }, [txt('分配选项待详情加载。')])]
    : [
      el('p', `${key}:assign:note`, {}, [txt('用户全局默认与项目默认在本区独立管理，不塞进 Profile。')]),
      el('button', `${key}:assign:global-enable`, { type: 'button', tabIndex: 0, 'data-action': 'assign', 'data-layer': 'user-global', 'data-decision': 'enable', 'aria-label': '在用户全局默认启用（固定当前修订）', disabled: definition.archived }, [txt(`全局启用 v${definition.latestRevision}`)]),
      el('button', `${key}:assign:global-disable`, { type: 'button', tabIndex: 0, 'data-action': 'assign', 'data-layer': 'user-global', 'data-decision': 'disable', 'aria-label': '在用户全局默认排除' }, [txt('全局排除')]),
      el('button', `${key}:assign:global-inherit`, { type: 'button', tabIndex: 0, 'data-action': 'assign', 'data-layer': 'user-global', 'data-decision': 'inherit', 'aria-label': '在用户全局默认恢复继承' }, [txt('全局继承')]),
      el('button', `${key}:assign:project-enable`, { type: 'button', tabIndex: 0, 'data-action': 'assign', 'data-layer': 'project', 'data-decision': 'enable', 'aria-label': '在当前项目默认启用（固定当前修订）', disabled: definition.archived || state.target.projectId === null }, [txt(`项目启用 v${definition.latestRevision}`)]),
      el('button', `${key}:assign:project-disable`, { type: 'button', tabIndex: 0, 'data-action': 'assign', 'data-layer': 'project', 'data-decision': 'disable', 'aria-label': '在当前项目默认排除' }, [txt('项目排除')]),
      el('button', `${key}:assign:project-inherit`, { type: 'button', tabIndex: 0, 'data-action': 'assign', 'data-layer': 'project', 'data-decision': 'inherit', 'aria-label': '在当前项目默认恢复继承' }, [txt('项目继承')]),
    ]))

  return el('section', key, { role: 'region', 'aria-label': '定义详情' }, children)
}


// ---------------------------------------------------------------------------
// Notices / effective set
// ---------------------------------------------------------------------------

export function noticeNode(notice: Notice, key: string): ViewNode {
  return el('li', key, {
    'data-notice-level': notice.level,
    'data-notice-code': notice.code ?? '',
    'data-tone': notice.level === 'refusal' ? 'refused' : notice.level === 'warning' ? 'warn' : 'info',
  }, [
    el('span', `${key}:text`, {}, [txt(notice.text)]),
    el('button', `${key}:dismiss`, { type: 'button', tabIndex: 0, 'data-action': 'dismiss-notice', 'data-notice-key': notice.id, 'aria-label': '关闭该提示' }, [txt('关闭')]),
  ])
}

function effectiveNode(set: EffectiveSet | null, key: string): ViewNode {
  if (set === null) return el('p', `${key}:empty`, { 'data-state': 'empty' }, [txt('有效集未加载；不显示推测结果。')])
  return el('section', key, { role: 'region', 'aria-label': '解析有效集预览' }, [
    el('h4', `${key}:title`, {}, [txt('解析有效集预览（只读，来自服务）')]),
    el('ul', `${key}:resolved`, {}, set.resolved.map((r, i) => el('li', `${key}:r:${i}`, { 'data-effective': r.definitionId }, [txt(`${r.definitionId}@v${r.revision} 由 ${r.selectedBy} 选中 → ${r.nativeName}`)]))),
    el('ul', `${key}:excluded`, {}, set.excluded.map((e, i) => el('li', `${key}:e:${i}`, { 'data-excluded': e.reasonCode, 'data-tone': 'refused' }, [txt(`${e.definitionId}：${e.reasonCode} — ${e.detail}`)]))),
  ])
}

/** The effective-set region shows a state node first, then the set itself. */
function effectiveStateNode(state: SettingsState): ViewNode {
  const stateNode = sliceStateNode(state.effective, 'effective', '有效集')
  if (stateNode) return stateNode
  if (state.effective.status === 'ready') return effectiveNode(state.effective.data, 'effective')
  return el('p', 'effective:idle', { 'data-state': 'empty' }, [txt('有效集未请求；不显示推测结果。')])
}

// ---------------------------------------------------------------------------
// Root
// ---------------------------------------------------------------------------

export interface SettingsView {
  readonly root: ViewNode
  /** Derived sequential keyboard order; document order because no index is positive. */
  readonly focusOrder: readonly string[]
  /** Every string the renderer can produce, for the false-green guards. */
  readonly strings: readonly string[]
}

export function buildSettingsView(state: SettingsState): SettingsView {
  const rows = visibleRows(state)
  const listState = sliceStateNode(state.list, 'list', '定义库')
  const unknownReason = nativeUnknownReason(state)
  const listChildren: ViewNode[] = [
    el('h3', 'list:title', {}, [txt('子代理定义库')]),
    el('div', 'list:filters', { role: 'group', 'aria-label': '按来源过滤' }, FILTERS.map(f => el('button', `list:filter:${f.value}`, {
      type: 'button', tabIndex: 0, 'data-action': 'filter-origin', 'data-origin-filter': f.value,
      'aria-pressed': state.originFilter === f.value, 'aria-label': `过滤：${f.label}`,
    }, [txt(f.label)]))
      .concat(el('button', 'list:filter:archived', {
        type: 'button', tabIndex: 0, 'data-action': 'toggle-archived', 'aria-pressed': state.showArchived, 'aria-label': '显示归档项',
      }, [txt('显示归档')]))),
    ...(listState ? [listState] : []),
    ...(unknownReason ? [el('p', 'list:native-unknown', { role: 'status', 'data-state': 'unknown', 'aria-label': `原生发现：未验证 — ${unknownReason}` }, [txt(`原生发现状态未验证：${unknownReason}（无观测机制，不等于不存在）`)])] : []),
    ...(rows.length > 0
      ? [el('ul', 'list:rows', { role: 'listbox', 'aria-label': '定义列表', 'aria-multiselectable': false }, rows.map((r, i) => rowNode(r, state, i)))]
      : listState
        ? []
        : [el('p', 'list:empty', { 'data-state': 'empty', role: 'status' }, [txt('该过滤条件下没有条目。')])]),
  ]

  const nativeActions = el('div', 'native:actions', { role: 'group', 'aria-label': '原生发现项操作' }, [
    el('button', 'native:inspect', { type: 'button', tabIndex: 0, 'data-action': 'inspect-native', 'aria-label': '重新观察原生发现项' }, [txt('观察原生发现')]),
    el('button', 'effective:inspect', { type: 'button', tabIndex: 0, 'data-action': 'resolve-preview', 'aria-label': '预览解析有效集' }, [txt('预览有效集')]),
  ])

  const dlg = dialogNode(state, 'dialog')
  const children: ViewNode[] = [
    targetIdentityNode(state.target, 'target'),
    el('div', 'service', { 'data-service': state.serviceAvailable ? 'present' : 'absent' }, [
      txt(state.serviceAvailable ? '定义服务：已接线' : '定义服务：未接线（以下内容为按端口契约渲染的解释态，不含伪造数据）'),
    ]),
    el('ul', 'notices', { role: 'status', 'aria-live': 'polite', 'aria-label': '操作反馈' }, state.notices.map((n, i) => noticeNode(n, `notice:${i}:${n.id}`))),
    el('section', 'list', { role: 'region', 'aria-label': '定义列表' }, listChildren),
    ...[nativeActions],
    detailPaneNode(state, 'detail'),
    defaultsPaneNode(state, 'defaults'),
    ...[effectiveStateNode(state)],
    importPaneNode(state.importFlow, state, 'import'),
    ...(dlg === null ? [] : [dlg]),
  ]

  const root = el('div', 'root', { 'data-settings-section': 'subagent-library', 'data-facet': 'assets.native-subagents' }, children)
  return { root, focusOrder: collectFocusKeys(root), strings: collectStrings([root]) }
}

/** Diff rows for the dialog, computed from two revisions (pure). */
export function diffLinesFor(detail: DefinitionDetail, from: number, to: number): readonly DiffLine[] {
  const a = detail.revisions.find(r => r.revision === from)
  const b = detail.revisions.find(r => r.revision === to)
  if (!a || !b) return []
  return revisionDiff(a, b)
}
