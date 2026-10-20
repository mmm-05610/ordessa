/**
 * 013 Desktop 产品化公开契约聚合入口。
 * 每条契约一个文件；`C07` 以命名空间导出以避开既有 commands source 的 `Command` 同名。
 */
export type { WireReason, WireResult, WirePort, AbsentWirePort } from '@ordessa/interface-contracts'
export * from './logging'
export * from './theme'
export * from './settings-diagnostics'
export * from './tokens'
export type { CommandSource, Keybinding, CommandOutcome, CommandRegistration, KeybindingService } from './commands-keybindings'
export * as C07 from './commands-keybindings'
