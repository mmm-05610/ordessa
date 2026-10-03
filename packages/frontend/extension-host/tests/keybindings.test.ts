import { describe, expect, it } from 'vitest'
import { createKeybindingService, describeChord, isKeyChordError, parseKeyChord } from '../src/services/keybindings'
import type { DisposableLike, ResourceScopeLike } from '../src/services/keybindings'

/** 最小可用的资源作用域，模拟 `@ordessa/extension-api` 的 `OwnedResources`。 */
function scope(): ResourceScopeLike & { disposeAll(): void; readonly items: DisposableLike[] } {
  const items: DisposableLike[] = []
  return {
    items,
    isDisposed: false,
    add(item) { items.push(item); return item },
    disposeAll() { for (const item of items.splice(0).reverse()) item.dispose() },
  }
}

describe('C-07 §2 键位语法', () => {
  it('resolves Mod to the platform primary modifier', () => {
    expect(parseKeyChord('Mod+Enter', 'darwin').steps[0]).toMatchObject({ mod: true, ctrl: false })
    expect(parseKeyChord('Mod+Enter', 'linux').steps[0]).toMatchObject({ mod: false, ctrl: true })
    expect(parseKeyChord('Mod+Enter', 'win32').steps[0]).toMatchObject({ mod: false, ctrl: true })
  })

  it('treats Cmd/Meta/Super as aliases of Mod and rejects mixing them with Ctrl', () => {
    expect(parseKeyChord('Cmd+K', 'darwin').id).toBe(parseKeyChord('Mod+K', 'darwin').id)
    expect(parseKeyChord('Meta+K', 'darwin').id).toBe(parseKeyChord('Mod+K', 'darwin').id)
    expect(() => parseKeyChord('Mod+Ctrl+K', 'darwin')).toThrowError(expect.objectContaining({ code: 'invalid-keybinding' }))
  })

  it('keeps explicit Ctrl/Shift/Alt distinct from Mod', () => {
    const chord = parseKeyChord('Ctrl+Shift+Alt+P', 'linux').steps[0]
    expect(chord).toMatchObject({ mod: false, ctrl: true, shift: true, alt: true, key: 'p' })
  })

  it('parses comma separated sequences into ordered steps', () => {
    const chord = parseKeyChord('Ctrl+K, Ctrl+S', 'linux')
    expect(chord.steps).toHaveLength(2)
    expect(chord.steps[0]).toMatchObject({ ctrl: true, key: 'k' })
    expect(chord.steps[1]).toMatchObject({ ctrl: true, key: 's' })
    expect(chord.source).toBe('Ctrl+K, Ctrl+S')
  })

  it('canonicalises named keys so event.key comparisons line up', () => {
    expect(parseKeyChord('Escape', 'linux').steps[0]?.key).toBe('esc')
    expect(parseKeyChord('Return', 'linux').steps[0]?.key).toBe('enter')
    expect(parseKeyChord('ArrowUp', 'linux').steps[0]?.key).toBe('arrowup')
  })
})

describe('C-07 §2 / §7.2 非法输入一律拒绝', () => {
  const invalid: readonly (readonly [string, string])[] = [
    ['empty string', ''],
    ['whitespace only', '   '],
    ['unknown modifier', 'Hyper+K'],
    ['missing key', 'Ctrl+'],
    ['modifier only', 'Shift'],
    ['duplicated modifier', 'Ctrl+Ctrl+K'],
    ['duplicated shift', 'Shift+Shift+K'],
    ['empty step in sequence', 'Ctrl+K,'],
  ]

  for (const [label, key] of invalid) {
    it(`rejects ${label} with a typed error`, () => {
      let thrown: unknown
      try { parseKeyChord(key, 'linux') } catch (error) { thrown = error }
      expect(isKeyChordError(thrown)).toBe(true)
      expect(thrown).toMatchObject({ code: 'invalid-keybinding', key })
      expect(String((thrown as { reason: string }).reason)).not.toBe('')
    })
  }

  it('does not classify unrelated errors as keybinding errors', () => {
    expect(isKeyChordError(new Error('boom'))).toBe(false)
    expect(isKeyChordError(null)).toBe(false)
    expect(isKeyChordError('invalid-keybinding')).toBe(false)
  })
})

describe('C-07 §2 / §7.1 冲突拒绝', () => {
  it('rejects a second command claiming the same resolved chord and keeps the incumbent', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'first', key: 'Mod+Enter' })

    let thrown: unknown
    try { service.bind({ commandId: 'second', key: 'Mod+Enter' }) } catch (error) { thrown = error }

    expect(isKeyChordError(thrown)).toBe(true)
    expect((thrown as { reason: string }).reason).toContain('first')
    // 既有绑定保留，后来者没有登记。
    expect([...service.resolve().values()]).toEqual(['first'])
    expect(service.getSnapshot().map(item => item.commandId)).toEqual(['first'])
  })

  it('treats different platform spellings of the same chord as one conflict', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'first', key: 'Mod+Enter' })
    // linux 上 `Mod` 即 Ctrl，因此显式 Ctrl 撞的是同一条序列。
    expect(() => service.bind({ commandId: 'second', key: 'Ctrl+Enter' })).toThrowError(
      expect.objectContaining({ code: 'invalid-keybinding' }),
    )
    expect(service.isBound('second')).toBe(false)
  })

  it('treats a full sequence as a distinct key from any of its steps', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'step', key: 'Ctrl+K' })
    service.bind({ commandId: 'sequence', key: 'Ctrl+K, Ctrl+S' })
    expect(service.resolve().size).toBe(2)
  })

  it('leaves the registry intact when a bind throws', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'incumbent', key: 'Mod+Enter' })
    expect(() => service.bind({ commandId: 'bad', key: 'Hyper+Enter' })).toThrow()
    expect(() => service.bind({ commandId: 'bad', key: 'Mod+Enter' })).toThrow()
    // 两次失败都没有留下残条，服务仍可继续接受新绑定。
    expect(service.getSnapshot()).toHaveLength(1)
    service.bind({ commandId: 'fresh', key: 'Alt+Shift+F5' })
    expect([...service.resolve().values()].sort()).toEqual(['fresh', 'incumbent'])
  })

  it('lets the same command re-register its own chord without a conflict', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'same', key: 'Mod+Enter' })
    service.bind({ commandId: 'same', key: 'Mod+Enter' })
    expect(service.getSnapshot()).toHaveLength(1)
  })
})

describe('作用域归属与注销', () => {
  it('removes the binding when the returned disposable is disposed', () => {
    const service = createKeybindingService({ platform: 'linux' })
    const owner = scope()
    const handle = service.forScope(owner).bind({ commandId: 'scoped', key: 'Mod+B' })
    expect(service.isBound('scoped')).toBe(true)
    handle.dispose()
    expect(service.isBound('scoped')).toBe(false)
    expect(service.getSnapshot()).toHaveLength(0)
  })

  it('drops every binding of a scope when the scope is disposed', () => {
    const service = createKeybindingService({ platform: 'linux' })
    const owner = scope()
    const bindings = service.forScope(owner)
    bindings.bind({ commandId: 'a', key: 'Mod+B' })
    bindings.bind({ commandId: 'b', key: 'Mod+C' })
    owner.disposeAll()
    expect(service.getSnapshot()).toHaveLength(0)
    expect(service.resolve().size).toBe(0)
  })

  it('is idempotent on repeated dispose', () => {
    const service = createKeybindingService({ platform: 'linux' })
    const owner = scope()
    const handle = service.forScope(owner).bind({ commandId: 'once', key: 'Mod+B' })
    handle.dispose()
    handle.dispose()
    expect(service.getSnapshot()).toHaveLength(0)
  })

  it('refuses to bind into an already disposed scope', () => {
    const service = createKeybindingService({ platform: 'linux' })
    const owner = scope()
    owner.disposeAll()
    const closed: ResourceScopeLike = { isDisposed: true, add: item => item }
    expect(() => service.forScope(closed).bind({ commandId: 'late', key: 'Mod+B' })).toThrow()
    void owner
  })
})

describe('C-07 §5 卸载与缺席', () => {
  it('keeps the stored configuration but stops resolving an absent provider', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'absent', key: 'Mod+Enter' })
    expect(service.isBound('absent')).toBe(true)

    service.markUnbound('absent')

    // 配置保留（快照里仍在），但不再映射到任何命令。
    expect(service.getSnapshot().map(item => item.commandId)).toEqual(['absent'])
    expect(service.getUnbound().map(item => item.commandId)).toEqual(['absent'])
    expect(service.resolve().size).toBe(0)
    expect(service.isBound('absent')).toBe(false)
  })

  it('restores the binding when the provider registers again', () => {
    const service = createKeybindingService({ platform: 'linux' })
    service.bind({ commandId: 'absent', key: 'Mod+Enter' })
    service.markUnbound('absent')
    expect(service.resolve().size).toBe(0)

    service.markBound('absent')

    expect(service.isBound('absent')).toBe(true)
    expect(service.getUnbound()).toHaveLength(0)
    expect([...service.resolve().values()]).toEqual(['absent'])
  })

  it('notifies subscribers when the registry changes', () => {
    const service = createKeybindingService({ platform: 'linux' })
    let calls = 0
    const stop = service.subscribe(() => { calls += 1 })
    service.bind({ commandId: 'watched', key: 'Mod+B' })
    expect(calls).toBeGreaterThan(0)
    const seen = calls
    stop()
    service.bind({ commandId: 'other', key: 'Mod+C' })
    expect(calls).toBe(seen)
  })
})

describe('describeChord', () => {
  it('renders the resolved modifiers in a stable order', () => {
    // `Mod` 在解析阶段已按平台展开，描述层显示的是解析后的结果。
    expect(describeChord(parseKeyChord('Mod+Shift+P', 'darwin').steps[0]!)).toBe('Mod+Shift+P')
    expect(describeChord(parseKeyChord('Mod+Shift+P', 'linux').steps[0]!)).toBe('Ctrl+Shift+P')
    expect(describeChord(parseKeyChord('Ctrl+Alt+Delete', 'linux').steps[0]!)).toBe('Ctrl+Alt+Delete')
  })

  it('uppercases single character keys and title-cases named ones', () => {
    expect(describeChord(parseKeyChord('mod+enter', 'darwin').steps[0]!)).toBe('Mod+Enter')
    expect(describeChord(parseKeyChord('mod+esc', 'darwin').steps[0]!)).toBe('Mod+Esc')
  })
})
