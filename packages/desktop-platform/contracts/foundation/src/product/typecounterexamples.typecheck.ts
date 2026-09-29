/**
 * 类型反例（PA-01）：C-03/04/05/06/07/08 的公开类型必须**不可变**且三态/缺席语义真实成立。
 * 每一处 `@ts-expect-error` 都必须真实触发：删掉注释即编译失败（`npm run typecheck` 覆盖本文件，
 * 因为 desktop tsconfig 的 include 包含 `packages/desktop-platform/contracts/某包/src`）。
 * 本文件不参与任何运行时加载。
 */
import type {
  AbsentWirePort, CommandOutcome, CommandSource, DiagnosticFragment, Fault, HarnessReport, HarnessState,
  Keybinding, LogFields, LogLevel, SettingsSection, ThemeMode, ThemeTokens, WirePort, WireResult,
} from './index'
import type { Command } from './commands-keybindings'
import type { ResourceScope } from '@ordessa/extension-api'

declare const scope: ResourceScope
declare const wire: WirePort
declare const result: WireResult
declare const tokens: ThemeTokens
declare const section: SettingsSection
declare const report: HarnessReport
declare const outcome: CommandOutcome
declare const source: CommandSource
declare const absent: AbsentWirePort
declare const runCommand: (id: string, args?: Readonly<Record<string, unknown>>) => Promise<CommandOutcome>

// --- 正例 -------------------------------------------------------------------
const level: LogLevel = 'warn'
void level
const mode: ThemeMode = 'system'
void mode
const accepted: WireResult = { kind: 'Accepted', requestId: 'r1', result: { ok: true } }
void accepted
const refused: WireResult = { kind: 'Refused', requestId: 'r2', reason: 'server-refused', retryable: false }
void refused
const unknown: WireResult = { kind: 'Unknown', requestId: 'r3', reason: 'host-not-ready' }
void unknown
const fragment: DiagnosticFragment = { id: 'example', state: 'unknown', reason: 'timeout' }
void fragment
const fault: Fault = { kind: 'port-conflict', reason: '端口被占用', remedy: '释放端口后重启', logRef: 'desktop.log#L1' }
void fault
const command: Command = { id: 'example.send', title: '发送', run: () => undefined }
void source.forScope(scope).add(command)
const key: Keybinding = { commandId: 'example.send', key: 'Mod+Enter' }
void key
void wire.call('example.method', { a: 1 })
void report.state
void outcome.kind
void absent.ready
void tokens.color.accent

// --- 反例：不可变 -----------------------------------------------------------
// @ts-expect-error 契约类型不可变：颜色令牌不得就地改写（C-05 §1 不变量）。
tokens.color.accent = '#fff'
// @ts-expect-error 嵌套结构同样不可变（C-05 §1、README §5）。
tokens.color = { bg: '#fff' } as ThemeTokens['color']
// @ts-expect-error 令牌对象整体不得替换。
tokens = {} as ThemeTokens
// @ts-expect-error 命令 id 只读。
command.id = 'other'
// @ts-expect-error 设置分区 id 只读。
section.id = 'other'
// @ts-expect-error 可用性报告不可变。
report.state = 'available'
// @ts-expect-error 三态结果不可变：不得把 Refused 就地升级为 Accepted。
result.kind = 'Accepted'
// @ts-expect-error 传输口 ready 是只读事实。
wire.ready = true

// --- 反例：三态与类型化形状 --------------------------------------------------
// @ts-expect-error 非法状态名：不得自造第四态。
const badState: HarnessState = 'ready'
void badState
// @ts-expect-error `unknown` 不得携带 retryable：无法确定时没有重试判据。
const unknownWithRetry: WireResult = { kind: 'Unknown', requestId: 'r', reason: 'x', retryable: true }
void unknownWithRetry
// @ts-expect-error `Accepted` 必须带 requestId。
const acceptedWithoutId: WireResult = { kind: 'Accepted', result: {} }
void acceptedWithoutId
// @ts-expect-error `Refused` 必须带 retryable（C-03 §3 表）。
const refusedWithoutRetry: WireResult = { kind: 'Refused', requestId: 'r', reason: 'x' }
void refusedWithoutRetry
// @ts-expect-error 缺席传输口的 ready 恒为 false。
const absentReady: true = absent.ready
void absentReady
// @ts-expect-error 缺席传输口的 scope 恒为 null。
const absentScope: string = absent.scope
void absentScope
// 注：`LogFields` 是 `Readonly<Record<string, unknown>>`，普通值约束在类型上不可表达
// （函数也是 unknown 的合法子类型），因此"只接受普通 JSON 值"由 sink 运行时强制，
// 对应反例见 extension-host tests/logging-redaction.test.ts。
const goodFields: LogFields = { count: 1, nested: { ok: true }, list: [1, 'two'] }
void goodFields
// @ts-expect-error 快捷键组合键只读：改绑必须走 unbind/bind，不得就地改写（C-07 §3）。
key.key = 'Mod+K'
// @ts-expect-error 缺席实现不能被当成就绪传输口。
const notPort: AbsentWirePort = wire
void notPort
// @ts-expect-error 诊断片段的 collected 变体必须带数据。
const badFragment: DiagnosticFragment = { id: 'x', state: 'collected' }
// @ts-expect-error 命令执行结果三态不得自造第四态。
const badOutcome: CommandOutcome = { kind: 'Succeeded', commandId: 'x' }
void badOutcome
