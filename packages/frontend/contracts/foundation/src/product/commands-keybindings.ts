/**
 * C-07 — 命令与快捷键类型载体。定义方 P-A，消费方插件。
 * 契约文本：`specs/013-desktop-product/contracts/C-07-commands-keybindings.md`（冻结，只读）。
 *
 * ⚠️ 命名冲突：既有 commands source 契约（`contracts/commands/src/commands.ts`）已在公开
 * 载体内导出 `Command`。C-07 的 `Command` 是**不同的形状**（含 `run`/`when`/`defaultKeybinding`），
 * 因此本模块以命名空间 `C07` 导出，扁平再导出无冲突的 `CommandSource` / `Keybinding`。
 * 契约文本本身不被修改，只是导出形状适配既有同名符号（见 P-A-report「命名裁决」）。
 */

import type { IDisposable, ResourceScope } from '@ordessa/extension-api'

export interface Command {
  /** 稳定 id，如 "ordessa.chat.send"。 */
  readonly id: string
  readonly title: string
  readonly category?: string
  /** 上下文表达式，缺省恒可用。 */
  readonly when?: string
  readonly defaultKeybinding?: string
  run(args?: Readonly<Record<string, unknown>>): void | Promise<void>
}

export interface Keybinding {
  readonly commandId: string
  /** "Mod+Enter" / "Ctrl+Shift+P" / 顺序序列 "Ctrl+K, Ctrl+S"。 */
  readonly key: string
  readonly when?: string
}

/** C-07 §4 三态与失败：不存在/不可用/执行异常/宿主未就绪。 */
export type CommandOutcome =
  | { readonly kind: 'Accepted'; readonly commandId: string; readonly value: unknown }
  | { readonly kind: 'Refused'; readonly commandId: string; readonly reason: string; readonly retryable: boolean }
  | { readonly kind: 'Unknown'; readonly commandId: string; readonly reason: string }

export interface CommandRegistration extends IDisposable {
  readonly commandId: string
}

export interface CommandSource {
  forScope(scope: ResourceScope): {
    add(command: Command): CommandRegistration
  }
  getSnapshot(): readonly Command[]
  subscribe(listener: () => void): () => void
  execute(id: string, args?: Readonly<Record<string, unknown>>): Promise<CommandOutcome>
}

/** 快捷键层：解析、冲突拒绝、查表（C-07 §2/§3）。 */
export interface KeybindingService {
  forScope(scope: ResourceScope): { bind(binding: Keybinding): IDisposable; unbind(commandId: string): void }
  getSnapshot(): readonly Keybinding[]
  /** 解析后的组合键列表，按注册序；冲突时后注册者被拒。 */
  resolve(): ReadonlyMap<string, string>
  subscribe(listener: () => void): () => void
}
