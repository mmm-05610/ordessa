/**
 * C-07 §3/§4/§5/§6 —— 宿主侧命令源：`when` 求值、命令面板清单、三态执行、缺席、键盘分派。
 *
 * 既有 `contracts/commands` 契约（`Commands` 服务）已经提供了注册/查询/执行；
 * 这一层是它**之上**的绑定与可用性层：快捷键只是命令的绑定，不另造执行机制。
 *
 * 纯逻辑，不 import `electron` / 任何 node 内建，主进程与沙箱化渲染进程共用同一份实现。
 *
 * 冻结契约：`specs/013-desktop-product/contracts/C-07-commands-keybindings.md`（只读）。
 */

import type { C07 } from '@extensions/ordessa.contracts/contract.js'
import {
  describeChord,
  normalizeKeyName,
  parseKeyChord,
  type Chord,
  type DisposableLike,
  type KeyChord,
  type KeybindingServiceHost,
  type ResourceScopeLike,
} from './keybindings.js'

type Command = C07.Command
type CommandOutcome = C07.CommandOutcome
type CommandSource = C07.CommandSource

/** `when` 求值上下文；`hostReady` 映射 C-07 §4 的 `host-not-ready` 分支。 */
export interface CommandContext {
  readonly [key: string]: unknown
  readonly hostReady?: boolean
}

/** `when` 表达式的语法错误：确定性抛出，绝不静默（见 `evaluateWhen`）。 */
export interface WhenExpressionError {
  readonly code: 'invalid-when-expression'
  readonly expression: string
  readonly reason: string
}

/** C-07 §3 命令面板的一行。多步序列以「, 」连接。 */
export interface PaletteEntry {
  readonly id: string
  readonly title: string
  readonly category?: string
  readonly key?: string
  readonly available: boolean
}

// ── `when` 表达式 ────────────────────────────────────────────────────────────
type WhenNode =
  | { readonly kind: 'ref'; readonly name: string }
  | { readonly kind: 'not'; readonly operand: WhenNode }
  | { readonly kind: 'and'; readonly left: WhenNode; readonly right: WhenNode }
  | { readonly kind: 'or'; readonly left: WhenNode; readonly right: WhenNode }

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_.-]*/

/** 语法：`or := and ('||' and)*`；`and := unary ('&&' unary)*`；`unary := '!' unary | primary`；`primary := '(' or ')' | ident`。 */
function parseWhen(expression: string): WhenNode {
  const text = expression
  let position = 0

  // 用函数声明而非 const 箭头：只有声明形式才能让 TS 在调用点收窄为 `never`。
  function fail(reason: string): never {
    throw { code: 'invalid-when-expression', expression: text, reason } satisfies WhenExpressionError
  }
  const skip = (): void => {
    while (position < text.length && /\s/.test(text[position] as string)) position += 1
  }

  function or(): WhenNode {
    let left = and()
    for (;;) {
      skip()
      if (!text.startsWith('||', position)) return left
      position += 2
      left = { kind: 'or', left, right: and() }
    }
  }
  function and(): WhenNode {
    let left = unary()
    for (;;) {
      skip()
      if (!text.startsWith('&&', position)) return left
      position += 2
      left = { kind: 'and', left, right: unary() }
    }
  }
  function unary(): WhenNode {
    skip()
    if (text[position] !== '!') return primary()
    position += 1
    return { kind: 'not', operand: unary() }
  }
  function primary(): WhenNode {
    skip()
    if (position >= text.length) fail('表达式意外结束')
    if (text[position] === '(') {
      position += 1
      const inner = or()
      skip()
      if (text[position] !== ')') fail('缺少右括号')
      position += 1
      return inner
    }
    const match = IDENTIFIER.exec(text.slice(position))
    if (!match) fail(`意外的记号：${text[position]}`)
    const token = match[0]
    position += token.length
    return { kind: 'ref', name: token }
  }

  const root = or()
  skip()
  if (position < text.length) fail(`尾部存在多余记号：${text.slice(position)}`)
  return root
}

function evaluateWhenNode(node: WhenNode, context: CommandContext): boolean {
  switch (node.kind) {
    case 'ref': return truthy(context[node.name])
    case 'not': return !evaluateWhenNode(node.operand, context)
    case 'and': return evaluateWhenNode(node.left, context) && evaluateWhenNode(node.right, context)
    case 'or': return evaluateWhenNode(node.left, context) || evaluateWhenNode(node.right, context)
  }
}

function truthy(value: unknown): boolean {
  return value !== undefined && value !== null && value !== false
}

/**
 * 求值 `when`。缺省（undefined / 空白）恒为真。
 * 非法表达式在此**确定性地**抛出 `WhenExpressionError`；`add()` 在登记前也调用同一个
 * 解析器，于是「注册时」与「求值时」两个入口行为一致，且不会留下半条记录。
 */
export function evaluateWhen(expression: string | undefined, context: CommandContext): boolean {
  if (expression === undefined) return true
  const text = expression.trim()
  if (text === '') return true
  return evaluateWhenNode(parseWhen(text), context)
}

/** 面板清单与执行判定用：语法非法的命令按不可用处理，而不是让整个面板崩掉。 */
function whenIsSatisfied(when: string | undefined, context: CommandContext): boolean {
  try {
    return evaluateWhen(when, context)
  } catch {
    return false
  }
}

type CommandRegistration = C07.CommandRegistration
/** 契约面 `forScope(scope)` 的返回形状。 */
type CommandScopeLike = ReturnType<CommandSource['forScope']>

/** 命令注册句柄：`dispose` 等价于「该提供者卸载」（C-07 §5）。 */
class CommandRegistrationHandle implements CommandRegistration {
  isDisposed = false
  constructor(readonly commandId: string, private readonly onDispose: () => void) {}
  dispose(): void {
    if (this.isDisposed) return
    this.isDisposed = true
    this.onDispose()
  }
}

// ── 命令源 ───────────────────────────────────────────────────────────────────
/** 内部记录。`active=false` 表示提供者已卸载（C-07 §5）。 */
interface CommandRecord {
  readonly command: Command
  readonly run: (args?: Readonly<Record<string, unknown>>) => unknown
  active: boolean
}

export interface CommandSourceOptions {
  keybindings?: KeybindingServiceHost
  context?: () => CommandContext
  /** 命令 `run` 抛异常时的回调（C-07 §4：记日志 + 上报，绝不崩）。 */
  onError?: (commandId: string, error: unknown) => void
  /** 既有 `Commands` 扩展服务的适配器；存在时其命令被镜像进本源。 */
  legacy?: {
    getSnapshot(): readonly { id: string; title: string; execute(): unknown }[]
    execute(id: string): Promise<unknown>
  }
}

/** 宿主实际实现：在契约面之外补 `unload`，供 C-07 §5 的缺席语义与再注册使用。 */
export interface CommandSourceHost extends CommandSource {
  /** 提供者卸载：命令离开面板，其绑定在快捷键服务里标记为 unbound（配置保留）。 */
  unload(commandId: string): void
}

/** 宿主自身贡献的命令没有插件作用域，用一个不回收的哨兵作用域表示。 */
const HOST_SCOPE: ResourceScopeLike = { isDisposed: false, add: item => item }

class HostCommandSource implements CommandSourceHost {
  private readonly records: CommandRecord[] = []
  private readonly listeners = new Set<() => void>()
  private readonly keybindings: KeybindingServiceHost | undefined
  private readonly context: () => CommandContext
  private readonly onError: (commandId: string, error: unknown) => void

  constructor(options: CommandSourceOptions) {
    this.keybindings = options.keybindings
    this.context = options.context ?? (() => ({ hostReady: true }))
    this.onError = options.onError ?? (() => {})
  }

  forScope(scope: ResourceScopeLike): CommandScopeLike {
    return { add: (command: Command): CommandRegistration => this.register(command, scope) }
  }

  private register(command: Command, scope: ResourceScopeLike): CommandRegistration {
    if (typeof command.id !== 'string' || command.id.trim() === '') throw new Error('命令必须带非空 id')
    // 语法先于登记：非法 `when` / 非法 `defaultKeybinding` 在注册点被拒，不留下半条记录。
    if (command.when !== undefined) parseWhen(command.when.trim())
    const chord = command.defaultKeybinding === undefined
      ? undefined
      : parseKeyChord(command.defaultKeybinding, this.keybindings?.platform ?? 'linux')
    const record: CommandRecord = { command, run: command.run, active: true }
    this.records.push(record)
    // C-07：命令的 `defaultKeybinding` 就是经快捷键服务登记的一条绑定。
    if (chord) this.attachDefaultBinding(record, chord, scope)
    this.emit()
    return new CommandRegistrationHandle(command.id, () => this.unload(command.id))
  }

  private attachDefaultBinding(record: CommandRecord, chord: KeyChord, scope: ResourceScopeLike): void {
    if (!this.keybindings || scope.isDisposed) return
    // 重装恢复：先把此前标记 unbound 的原绑定取回优先权。
    this.keybindings.markBound(record.command.id)
    try {
      this.keybindings.forScope(scope).bind({
        commandId: record.command.id,
        key: chord.source,
        ...(record.command.when === undefined ? {} : { when: record.command.when }),
      })
    } catch (error) {
      // 冲突：命令本身仍然可用（只是拿不到快捷键），冲突信息经 onError 留痕。
      this.onError(record.command.id, error)
    }
  }

  unload(commandId: string): void {
    const record = this.records.find(item => item.command.id === commandId)
    if (!record || !record.active) return
    record.active = false
    this.keybindings?.markUnbound(commandId)
    this.emit()
  }

  getSnapshot(): readonly Command[] {
    return this.records.filter(record => record.active).map(record => record.command)
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener)
    return () => { this.listeners.delete(listener) }
  }

  private emit(): void {
    for (const listener of [...this.listeners]) listener()
  }

  /** C-07 §4 的四态判定；**任何**路径都不得把异常抛给调用方。 */
  async execute(id: string, args?: Readonly<Record<string, unknown>>): Promise<CommandOutcome> {
    if (this.context().hostReady === false) return { kind: 'Unknown', commandId: id, reason: 'host-not-ready' }
    const record = this.records.find(item => item.command.id === id && item.active)
    if (!record) return { kind: 'Refused', commandId: id, reason: 'command-absent', retryable: false }
    const when = record.command.when
    if (when !== undefined && !whenIsSatisfied(when, this.context())) {
      return { kind: 'Refused', commandId: id, reason: 'command-unavailable', retryable: false }
    }
    try {
      const value = await record.run(args)
      return { kind: 'Accepted', commandId: id, value }
    } catch (error) {
      // 捕获 + 回调留痕；服务保持可用，不静默回退（README §1「不得假绿」）。
      this.onError(id, error)
      return { kind: 'Refused', commandId: id, reason: 'command-failed', retryable: false }
    }
  }
}

export function createCommandSource(options: CommandSourceOptions): CommandSourceHost {
  const source = new HostCommandSource(options)
  if (options.legacy) {
    // 既有 `Commands` 服务的命令被镜像进来，id 与键位同处一个命名空间。
    const legacy = options.legacy
    for (const item of legacy.getSnapshot()) {
      source.forScope(HOST_SCOPE).add({
        id: item.id,
        title: item.title,
        // 既有服务返回任意值；C-07 的 `run` 只承诺 void，这里丢弃返回值。
        run: async (): Promise<void> => { await legacy.execute(item.id) },
      })
    }
  }
  return source
}

// ── 命令面板（C-07 §3）───────────────────────────────────────────────────────
function describeKey(keybindings: KeybindingServiceHost, commandId: string): string | undefined {
  const binding = keybindings.getSnapshot().find(item => item.commandId === commandId)
  if (!binding) return undefined
  try {
    return parseKeyChord(binding.key, keybindings.platform).steps.map(describeChord).join(', ')
  } catch {
    return undefined
  }
}

/**
 * C-07 §3 命令面板清单：带 `available` 标记（`when` 为假即不可用）、按
 * category → id 稳定排序，并显示已解析的绑定写法。
 */
export function listPalette(
  source: CommandSource,
  keybindings: KeybindingServiceHost,
  context: CommandContext,
): readonly PaletteEntry[] {
  return source
    .getSnapshot()
    .map(command => {
      const key = describeKey(keybindings, command.id)
      return {
        id: command.id,
        title: command.title,
        ...(command.category === undefined ? {} : { category: command.category }),
        ...(key === undefined ? {} : { key }),
        available: whenIsSatisfied(command.when, context),
      }
    })
    .sort((left, right) => {
      const category = (left.category ?? '').localeCompare(right.category ?? '')
      return category !== 0 ? category : left.id.localeCompare(right.id)
    })
    .map(entry => Object.freeze(entry))
}

// ── 键盘分派（C-07 §6）───────────────────────────────────────────────────────
/** 一条已解析键位连同它归属的命令，供键盘分派直接消费。 */
export interface BoundChord {
  readonly chord: KeyChord
  readonly commandId: string
}

/** 键盘事件最小形状：`KeyboardEvent` 的结构子集，便于在无 DOM 处驱动。 */
export interface KeyEventLike {
  readonly key: string
  readonly ctrlKey: boolean
  readonly shiftKey: boolean
  readonly altKey: boolean
  readonly metaKey: boolean
}

/** 序列键位（`Ctrl+K, Ctrl+S`）已按下的步数状态。 */
export interface KeySequenceState {
  readonly taken: number
}

export const EMPTY_SEQUENCE: KeySequenceState = { taken: 0 }

/**
 * 归一化后的单步按键。修饰键解析规则与 `parseStep` 完全一致：
 * 非 mac 平台上 `Mod` 就是 `Ctrl`（`mod:false, ctrl:true`），mac 上才是 `Cmd`。
 * 只有两边用同一套映射，`dispatchKey` 的比较才有意义。
 */
function eventStep(event: KeyEventLike, platform: string): Chord {
  const mac = /mac|darwin|iphone|ipad|ios/i.test(platform)
  return {
    mod: mac ? event.metaKey : false,
    ctrl: event.ctrlKey,
    shift: event.shiftKey,
    alt: event.altKey,
    key: normalizeKeyName(event.key),
  }
}

/**
 * 纯函数式键盘分派（C-07 §6）：把一个键盘事件按到给定的序列状态上，
 * 返回新的状态以及此刻应当触发的命令。
 *
 * 单步键位立即触发；多步序列在中间步只推进 `taken`，走完整序列才触发。
 * 任何不匹配都把 `taken` 归零并返回 `commandId: undefined`（不触发、不崩）。
 * 渲染进程与测试共用这一个实现，避免两处分派逻辑漂移。
 */
export function dispatchKey(
  chords: readonly BoundChord[],
  event: KeyEventLike,
  state: KeySequenceState = EMPTY_SEQUENCE,
  platform: string = 'linux',
): { readonly state: KeySequenceState; readonly commandId: string | undefined; readonly chordId: string | undefined } {
  const signature = describeChord(eventStep(event, platform))
  // 只有仍在进行中的序列才允许继续（长度不足的条目被滤掉）。
  const candidates = chords.filter(item => item.chord.steps.length > state.taken)
  for (const item of candidates) {
    const at = item.chord.steps[state.taken]
    if (!at || describeChord(at) !== signature) continue
    const taken = state.taken + 1
    if (taken < item.chord.steps.length) return { state: { taken }, commandId: undefined, chordId: undefined }
    // 完整走完：交出命令 id 与和弦 id，序列归零。
    return { state: EMPTY_SEQUENCE, commandId: item.commandId, chordId: item.chord.id }
  }
  return { state: EMPTY_SEQUENCE, commandId: undefined, chordId: undefined }
}

/**
 * 取**当前生效**的键位表供 `dispatchKey` 消费。
 *
 * 这里刻意用 `resolve()` 而不是 `getSnapshot()`：快照按 C-07 §5 保留了缺席提供者的
 * unbound 配置，若一并下发，键盘就会去触发一个并不存在的命令。
 */
export function boundChords(keybindings: KeybindingServiceHost): readonly BoundChord[] {
  const byId = new Map<string, KeyChord>()
  for (const binding of keybindings.getSnapshot()) {
    try {
      const chord = parseKeyChord(binding.key, keybindings.platform)
      byId.set(chord.id, chord)
    } catch {
      // 存储里若混入了非法串（外部写坏的配置），跳过而不是让键盘整体失灵。
    }
  }
  const out: BoundChord[] = []
  for (const [chordId, commandId] of keybindings.resolve()) {
    const chord = byId.get(chordId)
    if (chord) out.push({ chord, commandId })
  }
  return out
}
