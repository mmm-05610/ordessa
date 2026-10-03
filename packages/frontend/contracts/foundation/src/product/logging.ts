/**
 * C-04 — 日志（Logger）类型载体。定义方 P-A（TS）/ P-B（Python），消费方插件 / P-C。
 *
 * 契约文本：`specs/013-desktop-product/contracts/C-04-logging.md`（冻结，只读）。
 * 脱敏在 sink 层强制（C-04 §4），类型层不得给调用方绕过入口。
 */

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

/** `fields` 只接受普通 JSON 值（C-04 §1）。 */
export type LogFields = Readonly<Record<string, unknown>>

export interface Logger {
  debug(msg: string, fields?: LogFields): void
  info(msg: string, fields?: LogFields): void
  warn(msg: string, fields?: LogFields): void
  error(msg: string, fields?: LogFields): void
  /** 派生带 scope 的子 logger；scope 形如 "plugin.<id>"，可嵌套。 */
  child(scope: string): Logger
}

/** 记录格式（C-04 §2）：JSON Lines，`ts/level/scope/msg` 之后才是附加字段。 */
export interface LogRecord {
  readonly ts: string
  readonly level: LogLevel
  readonly scope: string
  readonly msg: string
  readonly [field: string]: unknown
}

/** sink 写失败时的可观测事实（C-04 §6：丢弃并计数，不影响主流程）。 */
export interface LogHealth {
  readonly writable: boolean
  readonly dropped: number
  readonly consecutiveFailures: number
  readonly lastError: string | null
}
