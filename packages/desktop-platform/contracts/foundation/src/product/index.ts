/**
 * 013 Desktop 产品化公开契约聚合入口。
 * 每条契约一个文件；`C07` 以命名空间导出以避开既有 commands source 的 `Command` 同名。
 */
export * from './wire-port'
export * from './logging'
export * from './theme'
export * from './settings-diagnostics'
export * from './harness-availability'
export * from './tokens'
export type { CommandSource, Keybinding, CommandOutcome, CommandRegistration, KeybindingService } from './commands-keybindings'
export * as C07 from './commands-keybindings'
