// @vitest-environment jsdom
/**
 * G15 — the Profile-editor Skill section.
 * Positive: 三态 + 最终结果 (deciding scope + fixed revision), 启用时指定已批准
 * 版本 with diff-before-switch, Profile 专用就地导入, 双源说明.
 * Counter-examples (verification.md G15): 选择即修改内容实体 / 取消删除已导入
 * 资产 / 旧贡献残留 UI — plus the G06/G09 unavailable-layer edge, CAS-keeps-
 * draft, keyboard/focus, and archived read-only.
 */
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProfileSkillsModel } from '../src/profileModel'
import { createProfileSkillsModel } from '../src/profileModel'
import { ProfileSkillSection } from '../src/profileSection'
import type { ProfileHost } from '../../contracts/src/profile'
import {
  fakeProfileHost, fakeProfileSkillsGateway, profileLibraryRow, profileRelation, profileRevisionOption,
} from './profile-fakes'
import { demoEffective, demoResolved } from './fakes'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface Rendered { container: HTMLElement; unmount(): Promise<void> }
let mounted: Rendered[] = []

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
  const group = container.querySelector(`[data-testid="profile-setting-${assetId}"] [role="group"]`) as HTMLElement
  expect(group, `profile-setting-${assetId} group`).toBeTruthy()
  return [...group.querySelectorAll<HTMLButtonElement>('button')]
}

const pressedChoice = (container: HTMLElement, assetId = 'demo') =>
  rowButtons(container, assetId).filter(button => button.getAttribute('aria-pressed') === 'true').map(button => button.textContent)

function settledModel(
  gatewayOptions = {}, hostOptions = {},
): { model: ProfileSkillsModel; calls: { method: string; params: unknown[] }[]; hostCalls: { method: string; params: unknown[] }[]; host: ProfileHost } {
  const built = fakeProfileSkillsGateway(gatewayOptions)
  const hostFake = fakeProfileHost(hostOptions)
  return {
    model: createProfileSkillsModel(built.gateway, hostFake.host),
    calls: built.calls, hostCalls: hostFake.calls, host: hostFake.host,
  }
}

async function settled(gatewayOptions = {}, hostOptions = {}): Promise<ReturnType<typeof settledModel>> {
  const context = settledModel(gatewayOptions, hostOptions)
  await context.model.refresh()
  return context
}

describe('G15 正例：三态、最终结果、双源说明', () => {
  it('every row shows the Profile-layer choice AND the final result with deciding scope + fixed revision', async () => {
    stubViewport(1280)
    const context = await settled(
      {
        effective: demoEffective([demoResolved('demo', {
          revision: 2,
          selectedBy: { layer: 'profile', scopeId: 'p1', harnessId: 'pi', revision: 2 },
          excludedBy: null, evidence: 'selected', proofs: ['assignment_decision'],
        })]),
      },
      { relations: [profileRelation('demo', { decision: 'enable', revision: 2 })] },
    )
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    expect(pressedChoice(container)).toEqual(['启用'])
    expect(text(container, 'profile-choice-demo')).toContain('本层：启用')
    expect(text(container, 'profile-pinned-demo')).toContain('固定版 r2')
    const result = text(container, 'profile-effective-demo')
    expect(result).toContain('在有效集合')
    expect(result).toContain('Profile p1 / pi · r2')
    expect(text(container, 'profile-effect-note-demo')).toBe('已选择，尚未投放')
    // The two-source panel is part of the section, not a tooltip.
    expect(text(container, 'profile-two-source-note')).toContain('“本层设置”读取 Profile 自己的草稿/已存条目')
    expect(text(container, 'profile-two-source-note')).toContain('“最终结果”读取 skills.resolve 的有效集合')
  })

  it('inherited content and profile-private content are told apart, with honest origin badges', async () => {
    stubViewport(1280)
    const context = await settled(
      {
        effective: demoEffective([
          demoResolved('demo', { originScope: 'public' }),
          demoResolved('own', { nativeName: 'own', originScope: 'profile' }),
        ]),
      },
      { relations: [profileRelation('own', { decision: 'enable', revision: 1, importedForProfile: true })] },
    )
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    expect(text(container, 'profile-origin-demo')).toContain('公共库')
    expect(text(container, 'profile-origin-own')).toContain('Profile 专用')
    expect(text(container, 'profile-two-source-note')).toContain('Profile 专用 1 项')
    expect(text(container, 'profile-two-source-note')).toContain('继承内容 1 项')
  })
})

describe('G15 反例 (verification.md)', () => {
  it('选择即修改内容实体 — editing a choice sends nothing to the content layer', async () => {
    stubViewport(1280)
    const context = await settled()
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    const buttons = rowButtons(container)
    await act(async () => { buttons[1].focus(); buttons[1].click() })
    // 禁用 was chosen: no content-family call ever appears (only the refresh
    // reads), no host write until an explicit save.
    expect(pressedChoice(container)).toEqual(['禁用'])
    expect(text(container, 'profile-draft-demo')).toContain('未保存')
    expect(context.calls.filter(call => ['approveRevision', 'importCommit', 'importBegin', 'importChunk', 'importPreview', 'diff'].includes(call.method))).toHaveLength(0)
    expect(context.hostCalls.filter(call => call.method === 'saveRelations')).toHaveLength(0)
    await clickByTestId(container, 'profile-save')
    await flush()
    expect(context.hostCalls.filter(call => call.method === 'saveRelations')).toHaveLength(1)
  })

  it('取消删除已导入资产 — cancelling the Profile keeps imported content and deletes nothing', async () => {
    stubViewport(1280)
    const context = await settled()
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    // Import in place through the bounded transfer.
    await act(async () => {
      await context.model.importPicked([{ path: 'SKILL.md', bytes: new TextEncoder().encode('x') }])
    })
    expect(text(container, 'profile-import-preview')).toContain('【脚本——安装与预览均不执行】')
    await clickByTestId(container, 'profile-import-confirm')
    await flush()
    expect(text(container, 'profile-import-result')).toContain('已保存（stored）')
    expect(text(container, 'profile-origin-demo')).toContain('Profile 专用')
    // Now cancel the whole Profile edit.
    const gatewayCallsBeforeCancel = context.calls.length
    await clickByTestId(container, 'profile-cancel-editing')
    await flush()
    expect(context.hostCalls.some(call => call.method === 'cancelEditing')).toBe(true)
    // The content is STILL there: the library re-read lists it…
    expect(context.model.getSnapshot().library.map(row => row.assetId)).toContain('demo')
    // …and the "deletes nothing" half is asserted over the CLOSED gateway
    // call set, not a name regex that cannot match (the interface has no
    // delete/remove/uninstall method, so the old filter was vacuous).
    // (1) Every call ever made is one of the ten declared methods — no
    //     undeclared door exists on this surface.
    const DECLARED_GATEWAY_METHODS: readonly string[] = [
      'listSkills', 'revisions', 'diff', 'approveRevision', 'resolveProfile',
      'importBegin', 'importChunk', 'importPreview', 'importCommit', 'importCancel',
    ]
    expect(context.calls.map(call => call.method).filter(m => !DECLARED_GATEWAY_METHODS.includes(m))).toEqual([])
    // (2) The cancel act itself adds only pure re-read traffic (library list
    //     + effective resolve): no publish (importCommit), no write, no
    //     transfer teardown beyond what the import already did — cancelling
    //     the relationship can never reach content at all.
    const methodsAfterCancel = context.calls.slice(gatewayCallsBeforeCancel).map(call => call.method)
    expect(methodsAfterCancel).toEqual(['listSkills', 'resolveProfile'])
    // What DID travel before the cancel: the bounded transfer, commit as the
    // only publish point.
    expect(context.calls.slice(0, gatewayCallsBeforeCancel).map(call => call.method).filter(m => m.startsWith('import'))).toEqual(
      ['importBegin', 'importChunk', 'importPreview', 'importCommit'],
    )
  })

  it('旧贡献卸载只摘 UI — unmounting writes nothing; stored relations survive and read back', async () => {
    stubViewport(1280)
    const built = fakeProfileSkillsGateway()
    const hostFake = fakeProfileHost({ relations: [profileRelation('demo', { decision: 'enable', revision: 1 })] })
    const first = createProfileSkillsModel(built.gateway, hostFake.host)
    await first.refresh()
    const mounted1 = await render(<ProfileSkillSection model={first} />)
    expect(pressedChoice(mounted1.container)).toEqual(['启用'])
    await mounted1.unmount()
    // Removal is UI-only: the host was never asked to change anything, and its
    // stored state still has the enable row.
    expect(hostFake.calls.filter(call => call.method === 'saveRelations')).toHaveLength(0)
    expect(hostFake.state.relations).toEqual([profileRelation('demo', { decision: 'enable', revision: 1 })])
    expect(document.querySelector('[data-testid="profile-skill-section"]')).toBeNull()
    // A fresh mount of the contribution reads the stored assignment back.
    const second = createProfileSkillsModel(built.gateway, hostFake.host)
    await second.refresh()
    const mounted2 = await render(<ProfileSkillSection model={second} />)
    expect(pressedChoice(mounted2.container)).toEqual(['启用'])
  })

  it('移除覆写 says out loud that it is neither an uninstall nor a global disable', async () => {
    stubViewport(1280)
    const context = await settled({}, { relations: [profileRelation('demo')] })
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    const remove = find(container, 'profile-remove-override-demo') as HTMLButtonElement
    expect(remove.textContent).toContain('恢复继承')
    expect(remove.textContent).toContain('不卸载内容')
    expect(remove.textContent).toContain('非全局禁用')
    await act(async () => { remove.focus(); remove.click() })
    expect(pressedChoice(container)).toEqual(['继承'])
    await clickByTestId(container, 'profile-save')
    await flush()
    // The save dropped the relation row — and touched no content: the library
    // still lists the asset.
    const saved = context.hostCalls.find(call => call.method === 'saveRelations')!.params[0] as { assetId: string }[]
    expect(saved.some(row => row.assetId === 'demo')).toBe(false)
    expect(context.model.getSnapshot().library.map(row => row.assetId)).toContain('demo')
  })
})

describe('启用时指定已批准版本 (FR07 profile side)', () => {
  it('the picker shows approval facts from skills.revisions; the binding moves only on explicit 重指', async () => {
    stubViewport(1280)
    const context = await settled(
      { revisions: [profileRevisionOption(1, true), profileRevisionOption(2, true), profileRevisionOption(3, false)] },
      { relations: [profileRelation('demo', { decision: 'enable', revision: 1 })] },
    )
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    await clickByTestId(container, 'profile-switch-demo')
    await flush()
    expect(text(container, 'profile-revision-demo-1')).toContain('已批准')
    expect(text(container, 'profile-revision-demo-3')).toContain('未批准')
    // Diff BEFORE any switch: choosing a revision previews, it does not repoint.
    await clickByTestId(container, 'profile-preview-demo-2')
    const diffClicks = context.calls.filter(call => call.method === 'diff')
    expect(diffClicks).toHaveLength(1)
    expect(diffClicks[0].params[0]).toEqual({ assetId: 'demo', fromRevision: 1, toRevision: 2 })
    const diff = text(container, 'profile-diff-demo')
    expect(diff).toContain('新增 notes.md')
    expect(diff).toContain('变更 SKILL.md')
    expect(context.hostCalls.filter(call => call.method === 'saveRelations')).toHaveLength(0)
    // No approval call either: r2 is already approved, and approval alone
    // would move no binding anyway (FR07).
    expect(context.calls.filter(call => call.method === 'approveRevision')).toHaveLength(0)
    // The explicit approve-and-repoint act.
    await clickByTestId(container, 'profile-confirm-repoint-demo-2')
    expect(text(container, 'profile-pinned-demo')).toContain('固定版 r2')
    expect(context.calls.filter(call => call.method === 'approveRevision')).toHaveLength(0)
    await clickByTestId(container, 'profile-save')
    await flush()
    const saved = context.hostCalls.find(call => call.method === 'saveRelations')!.params[0] as { revision: number | null }[]
    expect(saved.find(row => row.revision === 2)).toBeDefined()
  })

  it('an unapproved revision only moves the binding after approve + explicit confirm, in that order', async () => {
    stubViewport(1280)
    const context = await settled(
      { revisions: [profileRevisionOption(1, true), profileRevisionOption(3, false)] },
      { relations: [profileRelation('demo', { decision: 'enable', revision: 1 })] },
    )
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    await clickByTestId(container, 'profile-switch-demo')
    await flush()
    await clickByTestId(container, 'profile-approve-repoint-demo-3')
    // Diff preview came first; nothing approved, nothing repointed yet.
    expect(context.calls.filter(call => call.method === 'approveRevision')).toHaveLength(0)
    expect(context.calls.filter(call => call.method === 'diff')).toHaveLength(1)
    await clickByTestId(container, 'profile-confirm-repoint-demo-3')
    await flush()
    const approveCalls = context.calls.filter(call => call.method === 'approveRevision')
    expect(approveCalls).toHaveLength(1)
    // …and the approval went out AFTER the diff was shown, never before it.
    expect(context.calls.indexOf(approveCalls[0])).toBeGreaterThan(context.calls.findIndex(call => call.method === 'diff'))
    expect(text(container, 'profile-pinned-demo')).toContain('固定版 r3')
    // A failed approval must leave the binding exactly where it was.
    const failing = await settled(
      { revisions: [profileRevisionOption(1, true), profileRevisionOption(3, false)], approveFails: true },
      { relations: [profileRelation('demo', { decision: 'enable', revision: 1 })] },
    )
    const failingView = await render(<ProfileSkillSection model={failing.model} />)
    await clickByTestId(failingView.container, 'profile-switch-demo')
    await flush()
    await clickByTestId(failingView.container, 'profile-approve-repoint-demo-3')
    await clickByTestId(failingView.container, 'profile-confirm-repoint-demo-3')
    await flush()
    expect(text(failingView.container, 'profile-pinned-demo')).toContain('固定版 r1')
    expect(text(failingView.container, 'profile-error')).toContain('批准失败')
  })

  it('启用 without any approvable revision opens the picker instead of pinning a guess', async () => {
    stubViewport(1280)
    const context = await settled({ revisions: [profileRevisionOption(2, false)] })
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    const buttons = rowButtons(container)
    await act(async () => { buttons[0].focus(); buttons[0].click() })
    await flush()
    expect(find(container, 'profile-draft-demo')).toBeNull()
    expect(text(container, 'profile-error')).toContain('启用需要指定已批准版本')
    expect(find(container, 'profile-switcher-demo')).not.toBeNull()
  })
})

describe('G06/G09 边缘：Profile 层不可读', () => {
  it('host layer unavailable → 继承 shows as 未确定, never as disabled; edits refused', async () => {
    stubViewport(1280)
    const context = await settled({}, { unavailable: true })
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    await flush()
    expect(text(container, 'profile-layer-unavailable')).toContain('不代表已禁用')
    expect(text(container, 'profile-choice-demo')).toContain('继承（未确定）')
    expect(text(container, 'profile-effective-demo')).toContain('最终结果待解析')
    expect(rowButtons(container).every(button => button.disabled)).toBe(true)
    // The content library still reads honestly — §G3 blocks the layer, not the
    // content facts.
    expect(context.model.getSnapshot().library.map(row => row.assetId)).toContain('demo')
    // Refused edits change nothing.
    await act(async () => { context.model.edit('demo', 'disable') })
    expect(text(container, 'profile-error')).toContain('Profile 层暂不可读')
    expect(pressedChoice(container)).toEqual([])
  })

  it('backend resolve refuses with PROFILE_LAYER_UNAVAILABLE while the host reads fine', async () => {
    stubViewport(1280)
    const context = await settled(
      { resolveUnavailable: true },
      { relations: [profileRelation('demo', { decision: 'enable', revision: 1 })] },
    )
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    expect(text(container, 'profile-effective-unavailable')).toContain('最终结果待解析')
    expect(text(container, 'profile-choice-demo')).toContain('本层：启用')
    expect(text(container, 'profile-effective-demo')).toContain('最终结果待解析')
    // The section never upgrades the unproven state into a load/enable claim.
    expect(container.textContent).not.toContain('已装载')
    expect(container.textContent).not.toContain('已启用')
  })
})

describe('G15 保存语义与状态', () => {
  it('a CAS conflict keeps every draft cell and offers 重新读取', async () => {
    stubViewport(1280)
    const context = settledModel({}, { saveResult: { kind: 'conflict', message: 'Profile 配置已被别处改动', serverConfigRevision: 9 } })
    await context.model.refresh()
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    const buttons = rowButtons(container)
    await act(async () => { buttons[1].focus(); buttons[1].click() })
    await clickByTestId(container, 'profile-save')
    expect(text(container, 'profile-save-conflict')).toContain('Profile 配置已被别处改动')
    expect(text(container, 'profile-save-conflict')).toContain('Profile 配置版本 9')
    expect(pressedChoice(container)).toEqual(['禁用'])
    expect(text(container, 'profile-draft-demo')).toContain('未保存')
    await clickByTestId(container, 'profile-conflict-reread')
    await flush()
    // The re-read wrote nothing extra and the draft still stands.
    expect(pressedChoice(container)).toEqual(['禁用'])
    expect(context.hostCalls.filter(call => call.method === 'saveRelations')).toHaveLength(1)
  })

  it('an archived Profile is read-only here, and nothing is deleted by archiving', async () => {
    stubViewport(1280)
    const context = await settled({}, {
      archived: true, relations: [profileRelation('demo', { decision: 'enable', revision: 1 })],
    })
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    expect(text(container, 'profile-archived')).toContain('只读')
    expect(rowButtons(container).every(button => button.disabled)).toBe(true)
    expect((find(container, 'profile-save') as HTMLButtonElement).disabled).toBe(true)
    // The stored enable row is still displayed — archived ≠ erased.
    expect(pressedChoice(container)).toEqual(['启用'])
    await act(async () => { await context.model.save() })
    expect(context.hostCalls.filter(call => call.method === 'saveRelations')).toHaveLength(0)
  })

  it('keyboard: arrows move the row cursor, and closing the picker restores trigger focus', async () => {
    stubViewport(1280)
    const context = await settled(
      { library: [profileLibraryRow(), profileLibraryRow({ assetId: 'other', nativeName: 'other' })] },
      {
        relations: [
          profileRelation('demo', { decision: 'enable', revision: 1 }),
          profileRelation('other', { decision: 'enable', revision: 1 }),
        ],
      },
    )
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    const first = rowButtons(container, 'demo')[0]
    await act(async () => { first.focus() })
    await act(async () => { first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
    expect(document.activeElement).toBe(rowButtons(container, 'other')[0])
    await act(async () => { rowButtons(container, 'other')[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowUp', bubbles: true })) })
    expect(document.activeElement).toBe(rowButtons(container, 'demo')[0])
    // Picker focus ownership: closing returns the cursor to its trigger.
    await clickByTestId(container, 'profile-switch-demo')
    await flush()
    const trigger = find(container, 'profile-switch-demo') as HTMLElement
    await clickByTestId(container, 'profile-switcher-close-demo')
    await flush()
    expect(document.activeElement).toBe(trigger)
  })

  it('the section renders no absolute host path and no secret anywhere', async () => {
    stubViewport(1280)
    const context = await settled()
    const { container } = await render(<ProfileSkillSection model={context.model} />)
    expect(context.calls.some(call => JSON.stringify(call.params).includes('/home/'))).toBe(false)
    expect(container.textContent).not.toContain('/home/')
    const attributes = [...container.querySelectorAll('*')]
      .map(node => `${node.getAttribute('aria-label') ?? ''}${node.getAttribute('title') ?? ''}${node.getAttribute('data-testid') ?? ''}`)
      .join('|')
    expect(attributes).not.toContain('/home/')
  })
})

/** The evidence-honesty gate on this surface: nothing here may upgrade a
 * projection into a load or an enable (G15 + G16 wording rules). */
describe('装载声明防伪造', () => {
  const cases: { name: string; overrides: Parameters<typeof demoResolved>[1]; want: string }[] = [
    { name: 'projected only', overrides: { evidence: 'projected', proofs: ['projection_digest'] }, want: '已投放，未确认装载' },
    { name: 'claimed loaded without observation', overrides: { evidence: 'loaded', proofs: ['projection_digest'] }, want: '装载状态未知' },
    { name: 'claimed used without event', overrides: { evidence: 'used', proofs: ['load_observation'] }, want: '装载状态未知' },
  ]
  for (const testCase of cases) {
    it(`renders "${testCase.name}" exactly as far as its own proofs go`, async () => {
      stubViewport(1280)
      const context = await settled({
        effective: demoEffective([demoResolved('demo', testCase.overrides)]),
      })
      const { container } = await render(<ProfileSkillSection model={context.model} />)
      expect(text(container, 'profile-effect-note-demo')).toBe(testCase.want)
      expect(container.textContent).not.toContain('已启用')
    })
  }
})
