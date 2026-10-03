// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SkillsGateway } from '../../contracts/src/gateway'
import type { NativeDiscoveryItem, ResolvedSkill } from '../../contracts/src/skills'
import { createSkillsModel, type SkillsModel } from '../src/model'
import type { OverlayOpener } from '../src/view'
import { SKILLS_DETAIL_OVERLAY_ID, SkillsSection } from '../src/view'
import {
  AVAILABLE_PROJECT, MISSING_PROJECT, demoEffective, demoRecord, demoResolved, demoRow,
  fakeSkillsGateway, fakeWorkspaces,
} from './fakes'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface Rendered { container: HTMLElement; unmount(): Promise<void> }
let mounted: Rendered[] = []

/** jsdom has no layout engine: the viewport width is what the responsive hook
 * is allowed to see, and the geometry itself is checked in the Electron smoke. */
function stubViewport(width: number) {
  const original = window.matchMedia
  restores.push(() => { window.matchMedia = original })
  window.matchMedia = ((query: string) => ({
    matches: width <= 720, media: query, onchange: null,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true,
  }) as unknown) as typeof window.matchMedia
}
const restores: (() => void)[] = []

async function render(element: ReactNode): Promise<Rendered> {
  const container = document.createElement('div')
  document.body.append(container)
  let root!: Root
  await act(async () => { root = createRoot(container); root.render(element) })
  const rendered: Rendered = {
    container,
    async unmount() { await act(async () => root.unmount()); container.remove() },
  }
  mounted.push(rendered)
  return rendered
}

afterEach(async () => {
  for (const entry of mounted.splice(0).reverse()) await entry.unmount()
  for (const restore of restores.splice(0).reverse()) restore()
  vi.restoreAllMocks()
})

const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }

function text(container: HTMLElement, testId: string): string {
  const node = container.querySelector(`[data-testid="${testId}"]`)
  expect(node, testId).toBeTruthy()
  return node!.textContent ?? ''
}

const find = (container: HTMLElement, testId: string) => container.querySelector(`[data-testid="${testId}"]`)

async function clickByTestId(container: HTMLElement, testId: string) {
  const node = find(container, testId)
  expect(node, testId).toBeTruthy()
  await act(async () => { (node as HTMLElement).focus?.(); (node as HTMLElement).click?.() })
}

function rowButtons(container: HTMLElement, assetId = 'demo'): HTMLButtonElement[] {
  const row = container.querySelector(`[data-testid="assignment-row-${assetId}"]`) as HTMLElement
  expect(row, `assignment-row-${assetId}`).toBeTruthy()
  return [...row.querySelectorAll<HTMLButtonElement>('button')]
}

/** One assignment area's own DOM: both areas render the same asset ids, so an
 * unscoped query could pass on the wrong layer's answer. */
function area(container: HTMLElement, key: 'global' | 'project'): HTMLElement {
  const node = container.querySelector(
    key === 'global' ? '[data-testid="default-assignments"]' : '[data-testid="project-assignments"]',
  ) as HTMLElement
  expect(node, key).toBeTruthy()
  return node
}

/** The decision the row actually reads as set — the pressed button, not the
 * three labels that are always on screen. */
const pressedDecision = (container: HTMLElement, assetId = 'demo') =>
  rowButtons(container, assetId).filter(button => button.getAttribute('aria-pressed') === 'true').map(button => button.textContent)

/** A settled gateway plus its call log; the fake is complete by type, so an
 * unwired method is a compile error rather than an empty answer. */
function gateway(options: Parameters<typeof fakeSkillsGateway>[0] = {}) {
  return fakeSkillsGateway(options)
}

async function settled(skills: SkillsGateway, projects = [AVAILABLE_PROJECT]): Promise<SkillsModel> {
  const model = createSkillsModel(skills, fakeWorkspaces(projects).port)
  await model.refresh()
  return model
}

describe('内容库 view', () => {
  it('renders names, revisions, sources and ownership; no load claim anywhere (legacy case kept)', async () => {
    stubViewport(1280)
    const { gateway: wire } = gateway()
    const { container } = await render(<SkillsSection model={await settled(wire)} />)
    expect(text(container, 'skills-list')).toContain('demo · r2 · local:import · 公共库')
    expect(container.textContent).not.toContain('已装载')
    expect(container.textContent).not.toContain('已启用')
  })

  it('shows empty, loading and error states without losing the last good list', async () => {
    stubViewport(1280)
    const empty = gateway({ catalogue: [] })
    const emptyView = await render(<SkillsSection model={await settled(empty.gateway)} />)
    expect(find(emptyView.container, 'skills-empty')).not.toBeNull()
    expect(find(emptyView.container, 'skills-list')).toBeNull()

    let fail = false
    const base = gateway()
    const flaky: SkillsGateway = {
      ...base.gateway,
      catalogue: async () => { if (fail) throw Error('CATALOGUE_UNAVAILABLE'); return base.gateway.catalogue() },
    }
    const model = await settled(flaky)
    const { container } = await render(<SkillsSection model={model} />)
    fail = true
    await act(async () => { await model.refresh() })
    expect(text(container, 'library-error')).toContain('CATALOGUE_UNAVAILABLE')
    // The list from the last good read is still on screen while the error shows.
    expect(find(container, 'skills-list')).not.toBeNull()
    fail = false
    await clickByTestId(container, 'library-error')
    await flush()
    expect(text(container, 'skills-list')).toContain('demo')
  })

  it('shows the loading state before the first answer arrives', async () => {
    stubViewport(1280)
    const base = gateway()
    let release: () => void = () => {}
    const gate = new Promise<void>(resolve => { release = resolve })
    const slow: SkillsGateway = { ...base.gateway, catalogue: async () => { await gate; return base.gateway.catalogue() } }
    const model = createSkillsModel(slow, fakeWorkspaces([]).port)
    const { container } = await render(<SkillsSection model={model} />)
    expect(find(container, 'library-loading')).not.toBeNull()
    expect(find(container, 'skills-list')).toBeNull()
    release()
    await flush()
    expect(find(container, 'skills-list')).not.toBeNull()
  })

  it('shows the fixed source reference and lets an update check be asked for', async () => {
    stubViewport(1280)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    await act(async () => { model.selectAsset('demo') })
    await flush()
    expect(text(container, 'source-line')).toContain('Git 固定引用 deadbeef')
    expect(text(container, 'source-line')).toContain('候选 r2')
    expect(text(container, 'source-line')).toContain('来源在册')
    expect(text(container, 'source-line')).toContain('尚未检查')
    await clickByTestId(container, 'check-update')
    await flush()
    expect(built.calls.filter(call => call.method === 'checkUpdate')).toHaveLength(1)
    // The refreshed row is re-rendered from the answer, not left as the old text.
    expect(text(container, 'source-line')).toContain('最近检查 2026-09-02')
  })

  it('marks an archived source and keeps its rows readable', async () => {
    stubViewport(1280)
    const { gateway: wire } = gateway({ catalogue: [demoRecord({ archived: true })] })
    const model = await settled(wire)
    const { container } = await render(<SkillsSection model={model} />)
    expect(text(container, 'skill-row-demo')).toContain('已归档')
    await act(async () => { model.selectAsset('demo') })
    await flush()
    expect(text(container, 'skill-approved')).toContain('来源已归档')
  })

  it('marks scripts in the manifest and promises neither execution nor loading (legacy case kept)', async () => {
    stubViewport(1280)
    const { gateway: wire } = gateway()
    const model = await settled(wire)
    const { container } = await render(<SkillsSection model={model} />)
    await act(async () => { model.selectAsset('demo') })
    await flush()
    const manifest = text(container, 'file-manifest')
    expect(manifest).toContain('scripts/run.sh')
    expect(manifest).toContain('【脚本——安装与预览均不执行，内容不展示】')
    expect(manifest).not.toContain('运行')
    expect(manifest).not.toContain('已装载')
    // Only the non-script file gets a preview affordance.
    const previewButtons = [...container.querySelectorAll('[data-testid="file-manifest"] button')].map(b => b.textContent)
    expect(previewButtons).toEqual(['预览'])
  })

  it('renders a lying script body as a refusal, never as content', async () => {
    stubViewport(1280)
    const { gateway: wire } = gateway({
      preview: { path: 'scripts/run.sh', text: 'TOKEN=super-secret-value', script: true, truncated: false },
    })
    const model = await settled(wire)
    const { container } = await render(<SkillsSection model={model} />)
    await act(async () => { model.selectAsset('demo') })
    await act(async () => { await model.loadPreview('demo', 1, 'scripts/run.sh') })
    expect(text(container, 'preview-text')).toBe('脚本内容不展示')
    expect(container.textContent).not.toContain('super-secret-value')
  })

  it('shows the update candidate diff and says approval does not move bindings', async () => {
    stubViewport(1280)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    await act(async () => { model.selectAsset('demo') })
    await flush()
    expect(text(container, 'update-diff')).toContain('r1 → r2')
    expect(text(container, 'update-diff')).toContain('新增 notes.md')
    expect(text(container, 'update-diff')).toContain('批准不会移动已有绑定')
    await clickByTestId(container, 'approve-revision')
    await flush()
    expect(built.calls.some(call => call.method === 'approveRevision')).toBe(true)
    expect(built.calls.some(call => call.method === 'assignmentsUpsert')).toBe(false)
  })

  it('moves selection and focus with the keyboard, and closes the overlay on leave (G14 focus)', async () => {
    stubViewport(1280)
    const built = gateway({ catalogue: [demoRecord(), demoRecord({ assetId: 'other', nativeName: 'other' })] })
    const model = await settled(built.gateway)
    const opened: { id: string; anchor?: HTMLElement; disposed: boolean }[] = []
    const overlays: OverlayOpener = {
      open(id, options) {
        const record = { id, anchor: options?.anchor, disposed: false }
        opened.push(record)
        return { dispose() { record.disposed = true } }
      },
    }
    const { container, unmount } = await render(<SkillsSection model={model} overlays={overlays} />)
    const list = container.querySelector('[data-testid="skills-list"]') as HTMLElement
    const press = async (key: string) => {
      await act(async () => { list.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })) })
    }
    await press('ArrowDown')
    expect(model.getSnapshot().selectedAssetId).toBe('other')
    expect(document.activeElement).toBe(container.querySelector('#skill-option-other'))
    await press('ArrowUp')
    expect(model.getSnapshot().selectedAssetId).toBe('demo')
    expect(document.activeElement).toBe(container.querySelector('#skill-option-demo'))
    await press('End')
    expect(model.getSnapshot().selectedAssetId).toBe('other')
    await press('Home')
    expect(model.getSnapshot().selectedAssetId).toBe('demo')
    // The detail surface is a platform overlay; leaving the page closes it.
    await clickByTestId(container, 'open-detail-overlay')
    expect(opened).toHaveLength(1)
    expect(opened[0].id).toBe(SKILLS_DETAIL_OVERLAY_ID)
    expect(opened[0].anchor?.isConnected).toBe(true)
    await unmount()
    expect(opened[0].disposed).toBe(true)
  })
})

describe('默认启用 / 项目启用 view', () => {
  it('every row shows 本层设置 and 最终结果 with the deciding scope and revision', async () => {
    stubViewport(1280)
    const built = gateway({
      rows: [demoRow('demo', { layer: { kind: 'project', scopeId: 'ordessa', harnessId: null }, revision: 2 })],
      effective: demoEffective([demoResolved('demo', {
        revision: 2,
        selectedBy: { layer: 'project', scopeId: 'ordessa', harnessId: null, revision: 2 },
        excludedBy: null, evidence: 'projected', proofs: ['projection_digest'],
      })]),
    })
    const model = await settled(built.gateway)
    await model.setProject('ordessa')
    const { container } = await render(<SkillsSection model={model} />)
    const result = text(area(container, 'project'), 'effective-demo')
    expect(pressedDecision(area(container, 'project'))).toEqual(['启用'])
    expect(text(area(container, 'project'), 'layer-setting-demo')).toContain('固定版 r2')
    expect(result).toContain('在有效集合')
    expect(result).toContain('项目 ordessa / 所有 Harness · r2')
    expect(result).toContain('已投放，未确认装载')
    expect(result).not.toContain('已装载')
  })

  it('shows the inherited global result and this layer exception separately', async () => {
    stubViewport(1280)
    const built = gateway({
      rows: [],
      effective: demoEffective([demoResolved('demo', {
        selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 1 },
        excludedBy: null,
      })]),
    })
    const model = await settled(built.gateway)
    await model.setProject('ordessa')
    const { container } = await render(<SkillsSection model={model} />)
    // 本层: nothing chosen here. 最终结果: it is in the set because the global
    // layer said so — the page has to show both, not a merged "on" switch.
    expect(pressedDecision(area(container, 'project'))).toEqual(['继承'])
    expect(text(area(container, 'project'), 'inherited-demo')).toContain('继承自全局')
    expect(text(area(container, 'project'), 'effective-demo')).toContain('全局默认 / 所有 Harness · r1')
    // The global area keeps its own answer plus the scope note the page owes.
    expect(text(container, 'default-assignments')).toContain('全局默认仅影响当前用户在本 Server 中的新提交')
  })

  it('a project disable names the excluding scope', async () => {
    stubViewport(1280)
    const built = gateway({
      rows: [demoRow('demo', { layer: { kind: 'project', scopeId: 'ordessa', harnessId: 'codex' }, decision: 'disable', revision: null })],
      effective: demoEffective([demoResolved('demo', {
        selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 1 },
        excludedBy: { layer: 'project', scopeId: 'ordessa', harnessId: 'codex', revision: null },
        evidence: 'unknown', proofs: [],
      })]),
    })
    const model = await settled(built.gateway)
    await model.setProject('ordessa')
    await model.setHarness('project', 'codex')
    const { container } = await render(<SkillsSection model={model} />)
    expect(pressedDecision(area(container, 'project'))).toEqual(['禁用'])
    expect(text(area(container, 'project'), 'effective-demo')).toContain('不在有效集合')
    expect(text(area(container, 'project'), 'effective-demo')).toContain('由 项目 ordessa / codex 排除')
    expect(text(area(container, 'project'), 'effect-note')).toBe('装载状态未知')
  })

  it('the tri-state writes no request until save, then exactly one per edited row', async () => {
    stubViewport(1280)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    const buttons = rowButtons(container)
    expect(buttons.map(button => button.textContent)).toEqual(['启用', '禁用', '继承'])
    await act(async () => { buttons[1].focus(); buttons[1].click() })
    expect(text(container, 'draft-flag-demo')).toContain('未保存')
    expect(built.calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(0)
    await clickByTestId(container, 'save-global')
    await flush()
    expect(built.calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(1)
    expect(find(container, 'draft-flag-demo')).toBeNull()
    expect(pressedDecision(container)).toEqual(['禁用'])
  })

  it('a CAS conflict keeps the draft on screen and offers 重新读取 (G14 counterexample)', async () => {
    stubViewport(1280)
    const built = gateway({
      write: { kind: 'conflict', code: 'cas-conflict', message: '服务端已变更', serverRevision: 9 },
    })
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    const buttons = rowButtons(container)
    await act(async () => { buttons[1].focus(); buttons[1].click() })
    await clickByTestId(container, 'save-global')
    expect(text(container, 'save-conflict-global')).toContain('服务端已变更')
    expect(text(container, 'save-conflict-global')).toContain('服务端版本 9')
    expect(pressedDecision(container)).toEqual(['禁用'])
    await clickByTestId(container, 'conflict-reread-global')
    expect(find(container, 'save-conflict-global')).toBeNull()
    // The user's choice is still the displayed 本层设置 after the re-read, and
    // the re-read itself wrote nothing.
    expect(pressedDecision(container)).toEqual(['禁用'])
    expect(built.calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(1)
  })

  it('stops editing when the project is missing, keeping stored records', async () => {
    stubViewport(1280)
    const built = gateway({
      rows: [demoRow('demo', { layer: { kind: 'project', scopeId: 'ordessa', harnessId: null }, decision: 'disable', revision: null })],
    })
    const model = await settled(built.gateway, [MISSING_PROJECT])
    await model.setProject('ordessa')
    const { container } = await render(<SkillsSection model={model} />)
    expect(text(area(container, 'project'), 'editing-stopped')).toContain('项目已缺失')
    expect(rowButtons(area(container, 'project')).every(button => button.disabled)).toBe(true)
    // The stored record is still shown — 禁用 is what the layer has on file.
    expect(pressedDecision(area(container, 'project'))).toEqual(['禁用'])
    expect(text(container, 'project-picker')).toContain('已缺失')
    expect(built.calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(0)
  })

  it('stays operable on a narrow viewport: rows stack and both columns remain reachable', async () => {
    stubViewport(360)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    expect(find(container, 'skills-settings')?.getAttribute('data-narrow')).toBe('true')
    const row = container.querySelector('[data-testid="assignment-row-demo"]') as HTMLElement
    expect(row.getAttribute('data-narrow')).toBe('stack')
    const setting = row.querySelector('[data-testid^="layer-setting-"]') as HTMLElement
    const result = row.querySelector('[data-testid^="effective-"]') as HTMLElement
    expect(pressedDecision(container)).toEqual(['继承'])
    expect(result.textContent).toContain('在有效集合')
    const buttons = [...setting.querySelectorAll<HTMLButtonElement>('button')]
    await act(async () => { buttons[0].focus(); buttons[0].click() })
    expect(find(container, 'draft-flag-demo')).not.toBeNull()
    // The save control takes focus and acts with no pointer or hover needed.
    const save = container.querySelector('[data-testid="save-global"]') as HTMLButtonElement
    expect(save.disabled).toBe(false)
    await act(async () => { save.focus(); save.click() })
    expect(document.activeElement).toBe(save)
    expect(built.calls.filter(call => call.method === 'assignmentsUpsert')).toHaveLength(1)
  })
})

describe('原生发现 view', () => {
  it('lists native findings read-only with location and the honest masking answer (US5/G11)', async () => {
    stubViewport(1280)
    const items: NativeDiscoveryItem[] = [
      { harnessId: 'pi', runtimeVersion: '0.9', nativeName: 'project-own', locationCategory: 'project', sourceEvidence: 'harness-discovery', canBeMasked: false, conflictsWith: null },
      { harnessId: 'codex', runtimeVersion: '1.2', nativeName: 'user-own', locationCategory: 'user-global', sourceEvidence: 'harness-discovery', canBeMasked: null, conflictsWith: 'demo' },
    ]
    const built = gateway({ native: items })
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    // Before the observation there is no claim in either direction.
    expect(find(container, 'native-empty')).not.toBeNull()
    await act(async () => { await model.loadNative('pi', '0.9', null) })
    expect(text(container, 'native-pi-project-own')).toContain('项目目录')
    expect(text(container, 'native-mask-project-own')).toBe('无法由 Ordessa 关闭')
    expect(text(container, 'native-mask-user-own')).toContain('无法由 Ordessa 关闭（该 Harness 未声明可屏蔽能力）')
    expect(text(container, 'native-codex-user-own')).toContain('与受管项 demo 重名')
    // Read-only by construction: no switch at all, and no fake "已禁用".
    expect(container.querySelectorAll('[data-testid="native-discovery"] button').length).toBe(0)
    expect(text(container, 'native-discovery')).not.toContain('已禁用')
    expect(text(container, 'native-discovery')).not.toContain('启用')
    expect(built.calls.filter(call => call.method === 'discoverNative')).toHaveLength(1)
  })

  it('previews a text body but echoes no path, in content or in attributes', async () => {
    stubViewport(1280)
    const built = gateway({
      catalogue: [demoRecord({ source: 'git:example/repo@deadbeef' })],
      native: [{
        harnessId: 'pi', runtimeVersion: '0.9', nativeName: 'private-finder',
        locationCategory: 'unknown', sourceEvidence: 'observed in this session only', canBeMasked: null, conflictsWith: null,
      }],
      preview: { path: 'SKILL.md', text: '正文示例', script: false, truncated: true },
    })
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    await act(async () => { model.selectAsset('demo') })
    await act(async () => { await model.loadPreview('demo', 1, '/home/user/.pi/skills/private/SKILL.md') })
    await act(async () => { await model.loadNative('pi', '0.9', null) })
    // Positive control: the body of a non-script file really is on screen.
    const body = text(container, 'preview-text')
    expect(body).toContain('正文示例')
    expect(body).toContain('（已按上限截断）')
    // ...and no absolute path reaches the DOM or any attribute of it.
    expect(container.textContent).not.toContain('/home/')
    const attributes = [...container.querySelectorAll('*')]
      .map(node => `${node.getAttribute('aria-label') ?? ''}${node.getAttribute('title') ?? ''}`)
      .join('|')
    expect(attributes).not.toContain('/home/')
    expect(text(container, 'native-discovery')).not.toContain('已禁用')
  })
})

describe('import wizard view', () => {
  it('shows the prepared preview with the script badge and the honest result sentence (legacy case kept)', async () => {
    stubViewport(1280)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    expect(find(container, 'import-preview')).toBeNull()
    expect(text(container, 'import-wizard')).toContain('不执行')
    await act(async () => {
      await model.importPicked([{ path: 'SKILL.md', bytes: new TextEncoder().encode('x') }], 'desktop:test',
        { originScope: 'public', originOwner: null })
    })
    expect(text(container, 'import-preview')).toContain('【脚本——安装与预览均不执行】')
    await clickByTestId(container, 'import-confirm')
    await flush()
    // The commit sentence says "stored" and names its own limit out loud.
    const result = text(container, 'import-result')
    expect(result).toContain('已保存（stored）')
    expect(result).toContain('不代表已装载到任何会话')
    expect(text(container, 'effect-note')).not.toContain('已装载')
    expect(built.calls.some(call => call.method === 'importCommit')).toBe(true)
  })

  it('feeds picked files through the transfer without ever sending a path', async () => {
    stubViewport(1280)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    const input = container.querySelector('[data-testid="import-pick"] input') as HTMLInputElement
    const bytes = new TextEncoder().encode('---\nname: demo\ndescription: d\n---\nbody')
    const file = { name: 'SKILL.md', arrayBuffer: async () => bytes.buffer as ArrayBuffer } as unknown as File
    Object.defineProperty(input, 'files', { configurable: true, value: [file] })
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })) })
    await flush()
    expect(text(container, 'import-preview')).toContain('demo')
    const declared = built.calls.find(call => call.method === 'importBegin')?.params[0] as { path: string }[]
    expect(declared.map(entry => entry.path)).toEqual(['SKILL.md'])
    // Only the file name travels; no desktop path exists anywhere in the calls.
    expect(JSON.stringify(built.calls)).not.toContain('/home/')
  })

  it('cancelling a prepared import cancels the transfer', async () => {
    stubViewport(1280)
    const built = gateway()
    const model = await settled(built.gateway)
    const { container } = await render(<SkillsSection model={model} />)
    await act(async () => {
      await model.importPicked([{ path: 'SKILL.md', bytes: new TextEncoder().encode('x') }], 'desktop:test',
        { originScope: 'project', originOwner: 'ordessa' })
    })
    expect(text(container, 'import-preview')).toContain('项目专用')
    await clickByTestId(container, 'import-cancel')
    expect(built.calls.some(call => call.method === 'importCancel')).toBe(true)
    expect(find(container, 'import-preview')).toBeNull()
  })
})

/** The evidence-honesty gate at the surface: a projection alone never reads as
 * an enable or a load (requirement 3). */
describe('evidence wording in the row', () => {
  const cases: { name: string; resolved: ResolvedSkill; want: string; forbid: string[] }[] = [
    {
      name: 'projected',
      resolved: demoResolved('demo', { evidence: 'projected', proofs: ['projection_digest'] }),
      want: '已投放，未确认装载',
      // The projection field is the only evidence here, so neither of the
      // stronger claims may appear for it.
      forbid: ['已装载', '已启用', '已调用'],
    },
    {
      name: 'loaded with its own observation',
      resolved: demoResolved('demo', { evidence: 'loaded', proofs: ['projection_digest', 'load_observation'] }),
      want: '已装载（Harness 有装载观察证据）',
      forbid: ['已启用', '已调用'],
    },
    {
      name: 'loaded without its own observation',
      resolved: demoResolved('demo', { evidence: 'loaded', proofs: ['projection_digest'] }),
      want: '装载状态未知',
      forbid: ['已装载'],
    },
    {
      name: 'used without an invocation event',
      resolved: demoResolved('demo', { evidence: 'used', proofs: ['load_observation'] }),
      want: '装载状态未知',
      forbid: ['已调用'],
    },
    {
      name: 'used with its own event',
      resolved: demoResolved('demo', { evidence: 'used', proofs: ['invocation_event'] }),
      want: '已调用（有独立调用事件证据）',
      forbid: ['已启用'],
    },
  ]

  for (const testCase of cases) {
    it(`renders ${testCase.name} exactly as far as its own proofs go`, async () => {
      stubViewport(1280)
      const built = gateway({
        rows: [demoRow('demo')],
        effective: demoEffective([{ ...testCase.resolved, selectedBy: { ...testCase.resolved.selectedBy } }]),
      })
      const { container } = await render(<SkillsSection model={await settled(built.gateway)} />)
      const note = text(container, 'effect-note')
      expect(note).toBe(testCase.want)
      for (const forbidden of testCase.forbid) expect(note).not.toContain(forbidden)
      // 本层设置 may honestly say 启用 (a stored decision); the effect sentence
      // never does, so a projection can never masquerade as a decision.
      if (testCase.forbid.includes('已启用')) expect(text(container, 'effective-demo')).not.toContain('已启用')
    })
  }
})

it('keeps an unsaved draft across a settings-page leave', async () => {
  stubViewport(1280)
  const built = gateway()
  const model = await settled(built.gateway)
  const first = await render(<SkillsSection model={model} />)
  const buttons = rowButtons(first.container)
  await act(async () => { buttons[1].focus(); buttons[1].click() })
  await first.unmount()
  expect(model.getSnapshot().global.draft.demo?.draft.decision).toBe('disable')
  const again = await render(<SkillsSection model={model} />)
  expect(pressedDecision(again.container)).toEqual(['禁用'])
  expect(text(again.container, 'draft-flag-demo')).toContain('未保存')
})
