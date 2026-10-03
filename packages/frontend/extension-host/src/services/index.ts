/**
 * 主进程侧的节点服务（PA-05/06/15 的实现入口）。
 *
 * 边界：这里的模块 import `node:fs`，因此**只**允许主进程与构建期使用；
 * 渲染进程侧的同名能力走浏览器安全的 `@ordessa/extension-host`（theme/commands/keybindings）。
 */
export { createLogService, redactValue } from './logging'
export type { LogService, LogSinkOptions } from './logging'
export { collectDiagnostics } from './diagnostics'
export type { DiagnosticsInput, DiagnosticsResult } from './diagnostics'
