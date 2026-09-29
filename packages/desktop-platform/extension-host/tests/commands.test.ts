import { describe, expect, it } from 'vitest'
import {
  boundChords,
  createCommandSource,
  dispatchKey,
  EMPTY_SEQUENCE,
  evaluateWhen,
  listPalette,
} from '../src/services/commands'
import type { CommandContext, KeyEventLike, KeySequenceState } from '../src/services/commands'
import { createKeybindingService, isKeyChordError } from '../src/services/keybindings'
import type { DisposableLike, ResourceScopeLike } from '../src/services/keybindings'

/** 最小可用的资源作用域，模拟 `@ordessa/extension-api` 的 `OwnedResources`。 */
function scope(): ResourceScopeLike & { disposeAll(): void } {
  const items: DisposableLike[] = []
  return {
    isDisposed: false,
    add(item) { items.push(item); return item },
    disposeAll() { for (const item of items.splice(0).reverse()) item.dispose() },
  }
}

function key(event: Partial<KeyEventLike> & { key: string }): KeyEventLike {
  return { ctrlKey: false, shiftKey: false, altKey: false, metaKey: false, ...event }
}

describe('when 表达式求值', () => {
  const context: CommandContext = { editor: true, dialog: false, selection: 'line' }

  it('treats an absent or blank expression as always available', () => {
    expect(evaluateWhen(undefined, context)).toBe(true)
    expect(evaluateWhen('   ', context)).toBe(true)
  })

  it('reads bare identifiers and negates them', () => {
    expect(evaluateWhen('editor', context)).toBe(true)
    expect(evaluateWhen('dialog', context)).toBe(false)
    expect(evaluateWhen('!dialog', context)).toBe(true)
    expect(evaluateWhen('!editor', context)).toBe(false)
  })

  it('evaluates && and || with the usual precedence', () => {
    expect(evaluateWhen('editor && !dialog', context)).toBe(true)
    expect(evaluateWhen('dialog && editor', context)).toBe(false)
    expect(evaluateWhen('dialog || editor', context)).toBe(true)
    expect(evaluateWhen('dialog || missing', context)).toBe(false)
  })

  it('honours parentheses over precedence', () => {
    expect(evaluateWhen('(dialog || editor) && selection', context)).toBe(true)
    expect(evaluateWhen('dialog || (editor && selection)', context)).toBe(true)
    expect(evaluateWhen('(dialog || missing) && editor', context)).toBe(false)
  })

  it('throws a typed error for malformed expressions instead of guessing', () => {
    for (const bad of ['editor &&', '(editor', 'editor)', '&& editor', '!', '@bad']) {
      let thrown: unknown
      try { evaluateWhen(bad, context) } catch (error) { thrown = error }
      expect(thrown, bad).toMatchObject({ code: 'invalid-when-expression', expression: bad })
    }
  })
})

describe('注册期校验', () => {
  it('rejects a command with an unparseable when clause and registers nothing', () => {
    const source = createCommandSource({})
    const owner = scope()
    expect(() => source.forScope(owner).add({ id: 'bad', title: 'Bad', when: 'a &&', run: () => {} })).toThrow()
    expect(source.getSnapshot()).toHaveLength(0)
  })

  it('rejects a command whose defaultKeybinding is malformed', () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings })
    const owner = scope()
    let thrown: unknown
    try {
      source.forScope(owner).add({ id: 'bad.key', title: 'Bad', defaultKeybinding: 'Hyper+X', run: () => {} })
    } catch (error) { thrown = error }
    expect(isKeyChordError(thrown)).toBe(true)
    expect(keybindings.getSnapshot()).toHaveLength(0)
    expect(source.getSnapshot()).toHaveLength(0)
  })

  it('registers defaultKeybinding through the keybinding service', () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings })
    source.forScope(scope()).add({
      id: 'ordessa.demo.send', title: 'Send', defaultKeybinding: 'Mod+Enter', run: () => {},
    })
    expect(keybindings.getSnapshot()).toEqual([{ commandId: 'ordessa.demo.send', key: 'Mod+Enter' }])
    expect(keybindings.isBound('ordessa.demo.send')).toBe(true)
  })
})

describe('C-07 §4 三态与失败', () => {
  it('returns Refused command-absent for an unknown command', async () => {
    const source = createCommandSource({})
    await expect(source.execute('nope.missing')).resolves.toEqual({
      kind: 'Refused', commandId: 'nope.missing', reason: 'command-absent', retryable: false,
    })
  })

  it('returns Refused command-unavailable when when evaluates false', async () => {
    const source = createCommandSource({ context: () => ({ dialog: false }) })
    source.forScope(scope()).add({ id: 'a', title: 'A', when: 'dialog', run: () => {} })
    await expect(source.execute('a')).resolves.toEqual({
      kind: 'Refused', commandId: 'a', reason: 'command-unavailable', retryable: false,
    })
  })

  it('returns Unknown host-not-ready before the host reports readiness', async () => {
    const source = createCommandSource({ context: () => ({ hostReady: false }) })
    source.forScope(scope()).add({ id: 'a', title: 'A', run: () => {} })
    await expect(source.execute('a')).resolves.toEqual({
      kind: 'Unknown', commandId: 'a', reason: 'host-not-ready',
    })
  })

  it('accepts a command and passes its arguments through', async () => {
    const seen: unknown[] = []
    const source = createCommandSource({})
    source.forScope(scope()).add({ id: 'a', title: 'A', run: (args) => { seen.push(args) } })
    const outcome = await source.execute('a', { text: 'hi' })
    expect(outcome).toMatchObject({ kind: 'Accepted', commandId: 'a' })
    expect(seen).toEqual([{ text: 'hi' }])
  })

  it('never throws out of execute, even when run rejects', async () => {
    const failures: { id: string; error: unknown }[] = []
    const source = createCommandSource({ onError: (id, error) => { failures.push({ id, error }) } })
    source.forScope(scope()).add({ id: 'boom', title: 'Boom', run: () => { throw new Error('kaboom') } })

    const outcome = await source.execute('boom')

    expect(outcome).toMatchObject({ kind: 'Refused', commandId: 'boom', retryable: false })
    expect(failures).toHaveLength(1)
    expect(failures[0]?.id).toBe('boom')
    expect(String(failures[0]?.error)).toContain('kaboom')
  })
})

describe('C-07 §7.3 抛异常的命令：上报后应用继续可用', () => {
  it('surfaces the failure and keeps the source usable', async () => {
    const reported: string[] = []
    let healthyRuns = 0
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({
      keybindings,
      onError: (id) => { reported.push(id) },
    })
    const owner = scope()
    source.forScope(owner).add({ id: 'broken', title: 'Broken', defaultKeybinding: 'Mod+B', run: () => { throw new Error('nope') } })
    source.forScope(owner).add({ id: 'healthy', title: 'Healthy', defaultKeybinding: 'Mod+H', run: () => { healthyRuns += 1 } })

    // 抛异常的键位仍然登记在快捷键表里（配置保留）。
    expect(keybindings.isBound('broken')).toBe(true)

    const failure = await source.execute('broken')
    expect(failure).toMatchObject({ kind: 'Refused', reason: 'command-failed', retryable: false })
    expect(reported).toEqual(['broken'])

    // 服务没有崩：另一条命令照常执行，错误面可以再上报。
    await expect(source.execute('healthy')).resolves.toMatchObject({ kind: 'Accepted' })
    expect(healthyRuns).toBe(1)

    await expect(source.execute('broken')).resolves.toMatchObject({ kind: 'Refused' })
    expect(reported).toEqual(['broken', 'broken'])

    expect(listPalette(source, keybindings, { hostReady: true })).toHaveLength(2)
  })
})

describe('C-07 §7.4 提供者卸载与重装', () => {
  it('removes the command from the palette, marks bindings unbound, and restores them', () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings })
    const provider = scope()
    const registration = source.forScope(provider).add({
      id: 'ordessa.demo.gone', title: 'Gone', defaultKeybinding: 'Mod+G', run: () => {},
    })

    expect(listPalette(source, keybindings, {}).map(item => item.id)).toEqual(['ordessa.demo.gone'])
    expect(keybindings.isBound('ordessa.demo.gone')).toBe(true)

    registration.dispose()

    // 命令从面板消失；绑定配置保留但标记 unbound，resolve 不再映射它。
    expect(source.getSnapshot()).toHaveLength(0)
    expect(listPalette(source, keybindings, {})).toHaveLength(0)
    expect(keybindings.getSnapshot().map(item => item.commandId)).toEqual(['ordessa.demo.gone'])
    expect(keybindings.getUnbound().map(item => item.commandId)).toEqual(['ordessa.demo.gone'])
    expect(keybindings.isBound('ordessa.demo.gone')).toBe(false)
    expect(keybindings.resolve().size).toBe(0)

    // 重装：原绑定恢复，命令回到面板。
    source.forScope(provider).add({
      id: 'ordessa.demo.gone', title: 'Gone', defaultKeybinding: 'Mod+G', run: () => {},
    })

    expect(keybindings.isBound('ordessa.demo.gone')).toBe(true)
    expect(keybindings.getUnbound()).toHaveLength(0)
    expect([...keybindings.resolve().values()]).toEqual(['ordessa.demo.gone'])
    expect(listPalette(source, keybindings, {}).map(item => item.id)).toEqual(['ordessa.demo.gone'])
  })

  it('keeps a rebound chord from being hijacked while the owner is absent, then restores the owner', () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings })
    const owner = scope()
    const registration = source.forScope(owner).add({
      id: 'absent', title: 'Absent', defaultKeybinding: 'Mod+Enter', run: () => {},
    })
    registration.dispose()

    // 缺席期间别人可以临时接管这条键位。
    keybindings.bind({ commandId: 'successor', key: 'Mod+Enter' })
    expect([...keybindings.resolve().values()]).toEqual(['successor'])

    // 原命令重装 → 优先权回到它，顶替者被挤出。
    source.forScope(owner).add({ id: 'absent', title: 'Absent', defaultKeybinding: 'Mod+Enter', run: () => {} })
    expect(keybindings.resolve().get(keybindings.getSnapshot()[0]!.key === 'Mod+Enter'
      ? [...keybindings.resolve().keys()][0]!
      : '')).toBeDefined()
    expect([...keybindings.resolve().values()]).toEqual(['absent'])
  })
})

describe('C-07 §7.5 when 为假即隐藏', () => {
  it('hides an unavailable command from the palette and refuses to run it', async () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    let context: CommandContext = { dialog: false }
    const source = createCommandSource({ keybindings, context: () => context })
    source.forScope(scope()).add({
      id: 'hidden', title: 'Hidden', when: 'dialog', defaultKeybinding: 'Mod+H', run: () => {},
    })

    const closed = listPalette(source, keybindings, context)
    expect(closed).toHaveLength(1)
    expect(closed[0]?.available).toBe(false)
    await expect(source.execute('hidden')).resolves.toMatchObject({ reason: 'command-unavailable' })

    context = { dialog: true }
    const open = listPalette(source, keybindings, context)
    expect(open[0]?.available).toBe(true)
    await expect(source.execute('hidden')).resolves.toMatchObject({ kind: 'Accepted' })
  })
})

describe('C-07 §3 命令面板清单', () => {
  it('sorts by category then id and shows the resolved binding', () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings })
    const owner = scope()
    source.forScope(owner).add({ id: 'b.view', title: 'Zoom', category: 'View', defaultKeybinding: 'Mod+=', run: () => {} })
    source.forScope(owner).add({ id: 'a.view', title: 'Wrap', category: 'View', run: () => {} })
    source.forScope(owner).add({ id: 'z.chat', title: 'Send', category: 'Chat', defaultKeybinding: 'Ctrl+K, Ctrl+S', run: () => {} })

    // linux 上 `Mod` 解析为 Ctrl，因此清单显示的是解析后的写法。
    expect(listPalette(source, keybindings, {})).toEqual([
      { id: 'z.chat', title: 'Send', category: 'Chat', key: 'Ctrl+K, Ctrl+S', available: true },
      { id: 'a.view', title: 'Wrap', category: 'View', available: true },
      { id: 'b.view', title: 'Zoom', category: 'View', key: 'Ctrl+=', available: true },
    ])
  })

  it('mirrors commands from the pre-existing Commands service', async () => {
    const legacyRan: string[] = []
    const legacy = {
      getSnapshot: () => [{ id: 'legacy.one', title: 'Legacy One', execute: () => 'value' }],
      execute: async (id: string) => { legacyRan.push(id); return 'value' },
    }
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings, legacy })

    expect(listPalette(source, keybindings, {}).map(item => item.id)).toEqual(['legacy.one'])
    await expect(source.execute('legacy.one')).resolves.toMatchObject({ kind: 'Accepted' })
    expect(legacyRan).toEqual(['legacy.one'])
  })
})

describe('C-07 §6 键盘分派', () => {
  it('fires a single-step chord immediately', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'a', key: 'Mod+Shift+P' })
    const chords = boundChords(service)

    const hit = dispatchKey(chords, key({ key: 'p', ctrlKey: true, shiftKey: true }), EMPTY_SEQUENCE, 'linux')
    expect(hit.commandId).toBe('a')
    expect(hit.state.taken).toBe(0)
  })

  it('requires both steps of a sequence and resets on a mismatch', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'seq', key: 'Ctrl+K, Ctrl+S' })
    const chords = boundChords(service)

    const first = dispatchKey(chords, key({ key: 'k', ctrlKey: true }), EMPTY_SEQUENCE, 'linux')
    expect(first.commandId).toBeUndefined()
    expect(first.state.taken).toBe(1)

    const second = dispatchKey(chords, key({ key: 's', ctrlKey: true }), first.state, 'linux')
    expect(second.commandId).toBe('seq')
    expect(second.state.taken).toBe(0)

    // 中途按错：状态归零且不触发，再按正确的两步仍能命中。
    const stray = dispatchKey(chords, key({ key: 'q', ctrlKey: true }), first.state, 'linux')
    expect(stray.commandId).toBeUndefined()
    expect(stray.state.taken).toBe(0)
    const restart = dispatchKey(chords, key({ key: 'k', ctrlKey: true }), stray.state, 'linux')
    expect(dispatchKey(chords, key({ key: 's', ctrlKey: true }), restart.state, 'linux').commandId).toBe('seq')
  })

  it('reads the platform primary modifier from the event', () => {
    const service = createKeybindingService({ platform: 'darwin' })
    service.bind({ commandId: 'mac', key: 'Mod+Enter' })
    const chords = boundChords(service)

    expect(dispatchKey(chords, key({ key: 'Enter', metaKey: true }), EMPTY_SEQUENCE, 'darwin').commandId).toBe('mac')
    expect(dispatchKey(chords, key({ key: 'Enter', ctrlKey: true }), EMPTY_SEQUENCE, 'darwin').commandId).toBeUndefined()
  })

  it('never triggers a command whose binding is absent', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'gone', key: 'Mod+Enter' })
    service.markUnbound('gone')
    expect(dispatchKey(boundChords(service), key({ key: 'Enter', ctrlKey: true }), EMPTY_SEQUENCE, 'linux').commandId)
      .toBeUndefined()
  })
})

describe('C-07 §7.6 键盘全流程：打开面板 → 执行命令 → 关闭对话框', () => {
  it('completes the primary path without a mouse', async () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const reported: string[] = []
    const source = createCommandSource({ keybindings, onError: (id) => { reported.push(id) } })
    const ui = { paletteOpen: false, dialogOpen: false }
    const owner = scope()

    // 宿主自己的 UI 命令：注册到命令源，快捷键交给命令源登记（`defaultKeybinding`）。
    const host = source.forScope(owner)
    host.add({ id: 'ui.palette.open', title: 'Open Command Palette', category: 'View', defaultKeybinding: 'Mod+Shift+P', run: () => { ui.paletteOpen = true } })
    host.add({ id: 'ui.dialog.open', title: 'Open Settings', category: 'View', defaultKeybinding: 'Mod+O', run: () => { ui.paletteOpen = false; ui.dialogOpen = true } })
    host.add({ id: 'ui.dialog.close', title: 'Close Settings', category: 'View', defaultKeybinding: 'Escape', run: () => { ui.dialogOpen = false } })

    /** 模拟一次真实按键：查表 → 若命中则走 execute（三态），永不抛。 */
    const press = async (event: KeyEventLike, state: KeySequenceState = EMPTY_SEQUENCE) => {
      const hit = dispatchKey(boundChords(keybindings), event, state, 'linux')
      if (hit.commandId === undefined) return state
      const outcome = await source.execute(hit.commandId)
      // 三态必须落在 Accepted：这条路径上既没有缺席也没有不可用。
      expect(outcome).toMatchObject({ kind: 'Accepted', commandId: hit.commandId })
      return hit.state
    }

    // 1. Mod+Shift+P 打开命令面板（FR-044 的命令面板入口）。
    await press(key({ key: 'p', ctrlKey: true, shiftKey: true }))
    expect(ui.paletteOpen).toBe(true)
    // 面板打开后，命令面板自身列出全部可用命令及其绑定。
    const palette = listPalette(source, keybindings, { hostReady: true })
    expect(palette.map(item => item.id)).toEqual(['ui.dialog.close', 'ui.dialog.open', 'ui.palette.open'])
    expect(palette.every(item => item.available)).toBe(true)

    // 2. 键盘选中并执行「打开设置」——由 Mod+O 承担面板内的选中与确认。
    await press(key({ key: 'o', ctrlKey: true }))
    expect(ui.paletteOpen).toBe(false)
    expect(ui.dialogOpen).toBe(true)

    // 3. Escape 关闭对话框（「错误关闭」走同一条键盘路径）。
    await press(key({ key: 'Escape' }))
    expect(ui.dialogOpen).toBe(false)

    // 全程没有任何异常上报，也没有一次未绑定的按键。
    expect(reported).toEqual([])
  })

  it('reports command-absent instead of throwing when a bound command has no provider', async () => {
    const keybindings = createKeybindingService({ platform: 'linux' })
    const source = createCommandSource({ keybindings })
    // 只登记绑定、不注册命令：模拟提供者在按键到达前已经缺席。
    keybindings.bind({ commandId: 'vanished', key: 'Mod+Q' })

    const hit = dispatchKey(boundChords(keybindings), key({ key: 'q', ctrlKey: true }), EMPTY_SEQUENCE, 'linux')
    expect(hit.commandId).toBe('vanished')
    await expect(source.execute(hit.commandId as string)).resolves.toMatchObject({
      kind: 'Refused', reason: 'command-absent',
    })
  })
})