/**
 * C-07 §2/§5/§7 —— 快捷键层（键位解析、冲突拒绝、查表、作用域归属）。
 *
 * 这一层是**纯逻辑**：不 import `electron`、不 import 任何 node 内建，
 * 因此主进程与被沙箱化的渲染进程可以共用同一份实现。
 *
 * 冻结契约：`specs/013-desktop-product/contracts/C-07-commands-keybindings.md`（只读）。
 * 类型来自公开契约载体 `@extensions/ordessa.contracts/contract.js`，与插件所见完全一致。
 */

import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type { C07 } from '@extensions/ordessa.contracts/contract.js'

type Keybinding = C07.Keybinding
type KeybindingService = C07.KeybindingService
type KeybindingScope = C07.KeybindingService['forScope']

/**
 * 契约里的 `ResourceScope` / `IDisposable` 住在 `@ordessa/extension-api`（会连带拉进 DI 的
 * Token）。这里只**类型**地转出它们的形状，让快捷键层保持零运行时依赖、可在渲染进程实例化。
 */
export type DisposableLike = IDisposable
export type ResourceScopeLike = ResourceScope

/** `forScope(scope)` 返回的注册句柄类型（契约面：`bind` / `add` 都用它）。 */
export type KeybindingScopeLike = ReturnType<KeybindingScope>

/** 解析后的和弦：修饰键 + 主键，`Mod` 已按平台解析完毕。 */
export interface Chord {
  readonly mod: boolean
  readonly ctrl: boolean
  readonly shift: boolean
  readonly alt: boolean
  readonly key: string
}

/** 完整键位序列（可含多步），来源串保留可读的原始写法。 */
export interface KeyChord {
  readonly id: string
  readonly steps: readonly Chord[]
  readonly source: string
}

/** 解析失败时的类型化错误（C-07 §2「解析失败 → 拒绝注册并给类型化错误」）。 */
export interface KeyChordError {
  readonly code: 'invalid-keybinding'
  readonly key: string
  readonly reason: string
}

/** 宿主实际实现：在契约面之外补两个只读查询，供 C-07 §5 缺席语义使用。 */
export interface KeybindingServiceHost extends KeybindingService {
  /** 绑定是否仍处于「已绑定」状态（unbound / 缺席提供者的命令返回 false）。 */
  isBound(commandId: string): boolean
  /** 组合键序列 → 命令 id 的已解析结果，供键盘事件分派直接查表。 */
  lookup(chord: KeyChord): string | undefined
  /** 缺席（unbound）但配置保留的绑定，C-07 §5 供快捷键表展示。 */
  getUnbound(): readonly Keybinding[]
  /** 本实例解析键位时使用的平台标识（`Mod` 已在这一步展开）。 */
  readonly platform: string
  /** 声明某命令当前缺席：其绑定保留但标记 unbound（配置**不**删除）。 */
  markUnbound(commandId: string): void
  /** 声明某命令重新注册：其原绑定恢复优先权。 */
  markBound(commandId: string): void
  /** 宿主自身声明的键位（无插件作用域归属）。 */
  bind(binding: Keybinding): DisposableLike
}

const MODIFIER_ALIASES: Readonly<Record<string, 'mod' | 'ctrl' | 'shift' | 'alt'>> = {
  mod: 'mod', mod_: 'mod',
  cmd: 'mod', command: 'mod', meta: 'mod', super: 'mod', win: 'mod',
  ctrl: 'ctrl', control: 'ctrl',
  shift: 'shift', alt: 'alt', option: 'alt',
}

/** 修饰键自身作为主键时使用的小写键名（显示层再做大写映射）。 */
const MODIFIER_KEY_NAMES: Readonly<Record<string, string>> = {
  mod: 'mod', ctrl: 'ctrl', shift: 'shift', alt: 'alt',
}

function keyChordError(key: string, reason: string): KeyChordError {
  return { code: 'invalid-keybinding', key, reason }
}

/** 类型判别：宿主/插件可用它把解析失败与其他异常区分开，且无需 `instanceof`。 */
export function isKeyChordError(error: unknown): error is KeyChordError {
  if (typeof error !== 'object' || error === null) return false
  const candidate = error as { code?: unknown }
  return candidate.code === 'invalid-keybinding'
}

function resolvePrimaryModifier(platform: string): 'mod' | 'ctrl' {
  return /mac|darwin|iphone|ipad|ios/i.test(platform) ? 'mod' : 'ctrl'
}

function parseStep(step: string, source: string, platform: string): Chord {
  const raw = step.trim()
  if (raw === '') throw keyChordError(source, '步骤为空：快捷键不能包含空的组合项')
  const parts = raw.split('+').map(part => part.trim())
  if (parts.some(part => part === '')) {
    throw keyChordError(source, `组合项缺少主键或修饰键：${raw}`)
  }
  const seen = new Set<string>()
  let mod = false
  let ctrl = false
  let shift = false
  let alt = false
  let key = ''
  for (const part of parts) {
    const alias = MODIFIER_ALIASES[part.toLowerCase()]
    if (alias === undefined) {
      if (key !== '') throw keyChordError(source, `存在多个主键：${raw}`)
      key = part
      continue
    }
    if (alias === 'mod') {
      // `Mod` 与其显式别名（Cmd/Meta/Super）指向同一位，重复即为非法。
      if (seen.has('mod') || seen.has('ctrl')) throw keyChordError(source, `修饰键重复：${part}`)
      seen.add('mod')
      seen.add('ctrl')
      mod = resolvePrimaryModifier(platform) === 'mod'
      ctrl = !mod
      continue
    }
    if (seen.has(alias)) throw keyChordError(source, `修饰键重复：${part}`)
    seen.add(alias)
    if (alias === 'ctrl') ctrl = true
    else if (alias === 'shift') shift = true
    else alt = true
  }
  if (key === '') throw keyChordError(source, `缺少主键：${raw}`)
  const canonical = MODIFIER_KEY_NAMES[key.toLowerCase()]
  return { mod, ctrl, shift, alt, key: canonical ?? normalizeKeyName(key) }
}

/**
 * 把 `KeyboardEvent.key` 归一到解析器使用的键名（`Escape`→`esc`、`a`→`a`）。
 * 导出是为了让键盘分派与解析共用同一份映射，两边不会各自漂移。
 */
export function normalizeKeyName(name: string): string {
  const lower = name.toLowerCase()
  // 单字符键保持小写，便于与 `KeyboardEvent.key` 直接比较。
  if ([...lower].length === 1) return lower
  switch (lower) {
    case 'escape': return 'esc'
    case 'arrowup': case 'up': return 'arrowup'
    case 'arrowdown': case 'down': return 'arrowdown'
    case 'arrowleft': case 'left': return 'arrowleft'
    case 'arrowright': case 'right': return 'arrowright'
    case 'return': return 'enter'
    case 'spacebar': return ' '
    case 'plus': return '+'
    case 'minus': return '-'
    case 'del': return 'delete'
    case 'pageup': return 'pageup'
    case 'pagedown': return 'pagedown'
    default: return lower
  }
}

function chordKey(chord: Chord): string {
  const bits: string[] = []
  if (chord.mod) bits.push('mod')
  if (chord.ctrl) bits.push('ctrl')
  if (chord.shift) bits.push('shift')
  if (chord.alt) bits.push('alt')
  return [...bits, chord.key].join('+')
}

function sequenceId(steps: readonly Chord[]): string {
  return steps.map(chordKey).join(',')
}

/**
 * 解析键位串。语法见 C-07 §2：`Mod` / `Ctrl` / `Shift` / `Alt`、`+` 组合、`,` 顺序序列。
 * 任何非法输入都抛出 `KeyChordError`（可用 `isKeyChordError` 判别），**不**静默忽略。
 */
export function parseKeyChord(key: string, platform: string = 'linux'): KeyChord {
  if (typeof key !== 'string' || key.trim() === '') {
    throw keyChordError(String(key), '快捷键字符串为空')
  }
  const steps = key.split(',').map(step => parseStep(step, key, platform))
  const chord: KeyChord = { id: sequenceId(steps), steps, source: key.trim() }
  return Object.freeze(chord)
}

const DISPLAY_LABELS: Readonly<Record<string, string>> = {
  mod: 'Mod', ctrl: 'Ctrl', shift: 'Shift', alt: 'Alt',
}

/** 人读写法：「Mod+Shift+P」「Ctrl+K, Ctrl+S」。与平台无关，`Mod` 不展开。 */
export function describeChord(chord: Chord): string {
  const bits: string[] = []
  if (chord.mod) bits.push(DISPLAY_LABELS.mod as string)
  if (chord.ctrl) bits.push(DISPLAY_LABELS.ctrl as string)
  if (chord.shift) bits.push(DISPLAY_LABELS.shift as string)
  if (chord.alt) bits.push(DISPLAY_LABELS.alt as string)
  const key = MODIFIER_KEY_NAMES[chord.key.toLowerCase()] === undefined
    ? (chord.key.length === 1 ? chord.key.toUpperCase() : capitalize(chord.key))
    : (DISPLAY_LABELS[chord.key.toLowerCase()] as string)
  return [...bits, key].join('+')
}

function capitalize(text: string): string {
  return text.length === 0 ? text : text[0]!.toUpperCase() + text.slice(1)
}

/** 内部绑定记录。`bound=false` 表示提供者缺席（C-07 §5：保留配置、标记 unbound）。 */
interface Entry {
  readonly chord: KeyChord
  readonly commandId: string
  when: string | undefined
  readonly scope: ResourceScopeLike | undefined
  bound: boolean
}

class BindingHandle implements DisposableLike {
  isDisposed = false
  constructor(
    private readonly entry: Entry,
    private readonly onDispose: (entry: Entry, handle: BindingHandle) => void,
  ) {}
  dispose(): void {
    if (this.isDisposed) return
    this.isDisposed = true
    this.onDispose(this.entry, this)
  }
}

class HostKeybindingService implements KeybindingServiceHost {
  private readonly entries: Entry[] = []
  private readonly live = new Map<string, Entry>()
  private readonly handles = new Set<BindingHandle>()
  private readonly listeners = new Set<() => void>()
  readonly platform: string

  constructor(platform: string) {
    this.platform = platform
  }

  /** 无归属绑定（宿主自身声明的键位，如命令面板的 `Mod+Shift+P`）。 */
  bind(binding: Keybinding): DisposableLike {
    return this.register(binding, undefined)
  }

  forScope(scope: ResourceScopeLike): KeybindingScopeLike {
    return {
      bind: (binding: Keybinding): DisposableLike => this.register(binding, scope),
      unbind: (commandId: string): void => { this.detach(commandId) },
    }
  }

  private register(binding: Keybinding, scope: ResourceScopeLike | undefined): DisposableLike {
    if (scope?.isDisposed) throw new Error('资源作用域已关闭')
    const chord = parseKeyChord(binding.key, this.platform)
    const id = chord.id
    const owner = this.live.get(id)
    // C-07 §2/§7.1：一条序列至多归属一个命令；后来者被拒，**不**静默覆盖。
    if (owner && owner.commandId !== binding.commandId) {
      if (owner.bound) throw keyChordError(binding.key, `组合键冲突：已被命令 ${owner.commandId} 占用`)
      // 缺席期间被顶替：存为影子条目，重装后原命令自动恢复优先权。
      const shadow: Entry = { chord, commandId: binding.commandId, when: binding.when, scope, bound: true }
      this.entries.push(shadow)
      this.live.set(id, shadow)
      this.emit()
      return this.track(shadow, scope)
    }
    const existing = this.entries.find(entry => entry.chord.id === id && entry.commandId === binding.commandId)
    if (existing) {
      existing.when = binding.when
      existing.bound = true
      this.live.set(id, existing)
      this.emit()
      return this.track(existing, scope)
    }
    const entry: Entry = { chord, commandId: binding.commandId, when: binding.when, scope, bound: true }
    this.entries.push(entry)
    this.live.set(id, entry)
    this.emit()
    return this.track(entry, scope)
  }

  private track(entry: Entry, scope: ResourceScopeLike | undefined): DisposableLike {
    const handle = new BindingHandle(entry, (target, self) => this.drop(target, self))
    this.handles.add(handle)
    if (scope) scope.add(handle)
    return handle
  }

  private drop(entry: Entry, handle: BindingHandle): void {
    this.handles.delete(handle)
    const index = this.entries.indexOf(entry)
    if (index < 0) return
    // 真正的注销（dispose）移除配置；标记 unbound 属于缺席，配置必须保留。
    if (entry.bound) {
      this.entries.splice(index, 1)
      if (this.live.get(entry.chord.id) === entry) this.live.delete(entry.chord.id)
      this.emit()
      return
    }
    this.promote(entry.chord.id)
  }

  private detach(commandId: string): void {
    const owned = this.entries.filter(entry => entry.commandId === commandId && entry.bound)
    if (owned.length === 0) return
    for (const entry of owned) {
      if (this.live.get(entry.chord.id) === entry) this.live.delete(entry.chord.id)
    }
    this.emit()
  }

  /**
   * 声明某命令当前缺席（C-07 §5）：命令消失，绑定保留但标记 unbound。
   * 此时同序列的顶替者临时生效；命令重装后原绑定自动恢复优先权。
   */
  markUnbound(commandId: string): void {
    const owned = this.entries.filter(entry => entry.commandId === commandId)
    if (owned.length === 0) return
    for (const entry of owned) {
      const wasLive = this.live.get(entry.chord.id) === entry
      entry.bound = false
      if (wasLive) {
        this.live.delete(entry.chord.id)
        this.promote(entry.chord.id)
      }
    }
    this.emit()
  }

  /** 声明某命令重新注册：原绑定恢复（先于顶替者）。 */
  markBound(commandId: string): void {
    const owned = this.entries.filter(entry => entry.commandId === commandId && !entry.bound)
    if (owned.length === 0) return
    for (const entry of owned) {
      if (this.entries.includes(entry)) {
        entry.bound = true
        this.live.set(entry.chord.id, entry)
      }
    }
    this.emit()
  }

  private promote(id: string): void {
    if (this.live.has(id)) return
    const candidate = this.entries.find(entry => entry.chord.id === id && entry.bound)
    if (candidate) this.live.set(id, candidate)
  }

  getSnapshot(): readonly Keybinding[] {
    return this.entries.map(entry => Object.freeze({
      commandId: entry.commandId,
      key: entry.chord.source,
      ...(entry.when === undefined ? {} : { when: entry.when }),
    }))
  }

  /** 缺席（unbound）但仍保留配置的绑定，C-07 §5 供快捷键表展示。 */
  getUnbound(): readonly Keybinding[] {
    return this.entries.filter(entry => !entry.bound).map(entry => Object.freeze({
      commandId: entry.commandId, key: entry.chord.source, ...(entry.when === undefined ? {} : { when: entry.when }),
    }))
  }

  isBound(commandId: string): boolean {
    return this.entries.some(entry => entry.commandId === commandId && entry.bound)
  }

  /** 组合键序列 → 命令 id（只含当前生效的绑定）。 */
  resolve(): ReadonlyMap<string, string> {
    return new Map([...this.live].map(([id, entry]) => [id, entry.commandId]))
  }

  lookup(chord: KeyChord): string | undefined {
    return this.live.get(chord.id)?.commandId
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private emit(): void {
    for (const listener of [...this.listeners]) listener()
  }
}

export function createKeybindingService(options: { platform?: string } = {}): KeybindingServiceHost {
  return new HostKeybindingService(options.platform ?? 'linux')
}
