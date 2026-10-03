/**
 * 平台服务 DI 载体。Token 身份必须**唯一**：宿主与插件都从公开契约载体
 * （`@extensions/ordessa.contracts/contract.js`）导入它，因此 Token 定义在这里，
 * 而不是各自实现里（否则 lumino 的服务解析会拿到不同身份）。
 *
 * 每个 Token 一个模块（`token/`），本文件只做聚合再导出。
 */
export { LoggerToken } from './token/LoggerToken'
export { ThemeServiceToken } from './token/ThemeServiceToken'
export { SettingsContributionToken } from './token/SettingsContributionToken'
export { DiagnosticsContributionToken } from './token/DiagnosticsContributionToken'
export { CommandSourceToken } from './token/CommandSourceToken'
export { KeybindingServiceToken } from './token/KeybindingServiceToken'
export { WirePortToken } from './token/WirePortToken'
export { HarnessAvailabilityToken } from './token/HarnessAvailabilityToken'

import type { Logger } from './logging'
import type { ThemeService } from './theme'
import type { SettingsContribution, DiagnosticsContribution } from './settings-diagnostics'
import type { CommandSource, KeybindingService } from './commands-keybindings'
import type { WirePort } from './wire-port'
import type { HarnessAvailability } from './harness-availability'

/** 宿主注入的整套平台服务；缺席语义由各服务自身实现（C-05 §5 / C-03 §6 / C-08 §4）。 */
export interface PlatformServices {
  readonly logger?: Logger
  readonly theme?: ThemeService
  readonly settings?: SettingsContribution
  readonly diagnostics?: DiagnosticsContribution
  readonly commands?: CommandSource
  readonly keybindings?: KeybindingService
  readonly wire?: WirePort
  readonly harness?: HarnessAvailability
}
