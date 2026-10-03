/**
 * 平台服务（公开给宿主装配与插件的浏览器安全入口）。
 * 这里的模块不 import 任何 node 内建，因此可进沙箱渲染进程，也可被扩展打包器带走。
 */
export { createThemeService, createNeutralThemeService, completeThemeTokens, themeCssVariables, applyThemeToDocument, NEUTRAL_TOKENS, THEME_CSS_VARIABLE_PREFIX } from './services/theme'
export type { ThemeServiceOptions, ThemeStyleTarget, PartialThemeTokens } from './services/theme'
export { createCommandSource, listPalette, evaluateWhen, dispatchKey, boundChords, EMPTY_SEQUENCE } from './services/commands'
export type { CommandContext, CommandSourceOptions, CommandSourceHost, PaletteEntry, KeyEventLike, KeySequenceState, BoundChord, WhenExpressionError } from './services/commands'
export { createKeybindingService, parseKeyChord, describeChord, isKeyChordError } from './services/keybindings'
// 公开契约类型也一并转发：宿主与插件用同一份形状（C-07 的 `Command` 因与既有
// commands source 同名，以 `C07` 命名空间导出）。
export type { Command, CommandOutcome, CommandSource, Keybinding, KeybindingService, CommandRegistration } from '@extensions/ordessa.contracts/contract.js'
export type { Logger, LogLevel, LogHealth } from '@extensions/ordessa.contracts/contract.js'
export type { ThemeMode, ThemeService, ThemeTokens, ResolvedTheme } from '@extensions/ordessa.contracts/contract.js'
export type { SettingsSection, SettingsItemDescriptor, DiagnosticProvider, Fault, FaultKind, DiagnosticFragment, SettingsContribution, DiagnosticsContribution } from '@extensions/ordessa.contracts/contract.js'
export type { WirePort, WireResult, AbsentWirePort } from '@extensions/ordessa.contracts/contract.js'
export type { HarnessAvailability, AbsentHarnessAvailability, HarnessReport, HarnessState } from '@extensions/ordessa.contracts/contract.js'
export type { Chord, KeyChord, KeyChordError, KeybindingServiceHost, ResourceScopeLike, DisposableLike } from './services/keybindings'
export { createAbsentHarnessAvailability, createFixtureHarnessAvailability, enforceReportInvariant, inspectBounded, INSPECT_TIMEOUT_MS } from './services/harness-availability'
export type { FixtureBrandSpec, FixtureHarnessOptions } from './services/harness-availability'
