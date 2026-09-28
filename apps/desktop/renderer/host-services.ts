/**
 * 渲染进程的平台服务装配（PA-16/19/21/22 的接线点）。
 *
 * 关键约束：
 *   · 令牌只在主进程：这里的 wire 只是一层 IPC 代理，插件与界面拿不到令牌字段；
 *   · 日志服务不直接写盘：渲染进程把记录交给主进程 sink 脱敏，避免渲染侧另起一套格式；
 *   · 缺席的服务用**缺席实现**（C-03 §6 / C-05 §5 / C-08 §4），不返回 null 让界面崩。
 */
import { createAbsentHarnessAvailability, createCommandSource, createKeybindingService, createThemeService, listPalette, type AbsentHarnessAvailability, type CommandSourceHost, type KeybindingServiceHost, type ThemeService } from '@ordessa/extension-host/platform'
import type { CommandOutcome, DiagnosticProvider, Logger, SettingsSection, WirePort, WireResult } from '@extensions/ordessa.contracts/contract.js'
import { NEUTRAL_TOKENS, createNeutralThemeService } from '@ordessa/extension-host/platform'

/** preload 暴露的宿主桥（见 electron/preload.ts）。 */
export interface DesktopHostBridge {
  about(): Promise<unknown>
  openLicense(): Promise<boolean>
  faults(): Promise<unknown[]>
  dataRoot(): Promise<{ dataRoot: string; logsDir: string }>
  openLogs(): Promise<boolean>
  readSetting(id: string): Promise<unknown>
  writeSetting(id: string, value: unknown): Promise<unknown>
  settingFragments(known: string[]): Promise<unknown[]>
  setLogLevel(level: string): Promise<string>
  logHealth(): Promise<{ dropped: number; writable: boolean }>
  exportDiagnostics(): Promise<unknown>
  wireCall(method: string, params: Record<string, unknown>): Promise<unknown>
  wireReady(): Promise<boolean>
  wireScope(): Promise<string | null>
  updateState(): Promise<unknown>
  checkUpdate(): Promise<unknown>
  downloadUpdate(): Promise<unknown>
  applyUpdate(): Promise<unknown>
}

declare global {
  interface Window {
    desktopHost?: DesktopHostBridge
    __ordessaTheme?: { resolved(): 'light' | 'dark'; subscribe(listener: () => void): () => void }
  }
}

/** 渲染进程日志：结构与主进程同构，脱敏仍由主进程 sink 强制。 */
export function createBridgeLogger(sink: (level: 'debug' | 'info' | 'warn' | 'error', msg: string, fields?: Readonly<Record<string, unknown>>) => void, scope = 'host.desktop'): Logger {
  const make = (prefix: string): Logger => ({
    debug: (msg, fields) => sink('debug', msg, { ...fields, scope: prefix }),
    info: (msg, fields) => sink('info', msg, { ...fields, scope: prefix }),
    warn: (msg, fields) => sink('warn', msg, { ...fields, scope: prefix }),
    error: (msg, fields) => sink('error', msg, { ...fields, scope: prefix }),
    child: child => make(`${prefix}.${child}`),
  })
  return make(scope)
}

/** C-03 §4：渲染侧只做代理，任何异常都降级为 `Unknown`，不冒泡到界面。 */
export function createBridgeWirePort(host: DesktopHostBridge | undefined): WirePort {
  if (!host) return { ready: false, scope: null, call: async () => ({ kind: 'Unknown', requestId: 'absent', reason: 'port-absent' }) as WireResult }
  return {
    ready: true,
    scope: null,
    async call(method, params) {
      try { return await host.wireCall(method, params) as WireResult }
      catch { return { kind: 'Unknown', requestId: 'local', reason: 'transport-unreachable' } }
    },
  }
}

export interface HostServices {
  theme: ThemeService
  commands: CommandSourceHost
  keybindings: KeybindingServiceHost
  wire: WirePort
  logger: Logger
  settings: { register(section: SettingsSection): () => void; getSnapshot(): readonly SettingsSection[] }
  diagnostics: { register(provider: DiagnosticProvider): () => void; getSnapshot(): readonly DiagnosticProvider[] }
  /** C-08：插件线交付 Harness 提供者之前，宿主注入**缺席实现**（诚实缺席，不假绿）。 */
  harness: AbsentHarnessAvailability
}

export interface BuildHostServicesOptions {
  bridge?: DesktopHostBridge
  mode?: 'light' | 'dark' | 'system'
  prefersDark?: () => boolean
  onCommandError?: (commandId: string, error: unknown) => void
  /** C-08：插件提供者的实现由后续插件线注入；缺省即缺席实现。 */
  harness?: AbsentHarnessAvailability
}

/** 一次装配：主题、命令、快捷键、wire、日志、设置分区与诊断片段的登记点。 */
export function buildHostServices(options: BuildHostServicesOptions = {}): HostServices {
  const bridge = options.bridge
  const theme = options.mode ? createThemeService({ mode: options.mode, prefersDark: options.prefersDark }) : createNeutralThemeService()
  const keybindings = createKeybindingService()
  const commands = createCommandSource({ keybindings, onError: options.onCommandError })
  const sections: SettingsSection[] = []
  const providers: DiagnosticProvider[] = []
  return {
    theme,
    commands,
    keybindings,
    harness: options.harness ?? createAbsentHarnessAvailability(),
    wire: createBridgeWirePort(bridge),
    logger: createBridgeLogger(() => { /* 渲染侧日志在构建期接主进程 sink；未接时静默丢弃而非阻塞 */ }),
    settings: {
      register(section) {
        sections.push(section)
        return () => { const index = sections.indexOf(section); if (index >= 0) sections.splice(index, 1) }
      },
      getSnapshot: () => [...sections],
    },
    diagnostics: {
      register(provider) {
        providers.push(provider)
        return () => { const index = providers.indexOf(provider); if (index >= 0) providers.splice(index, 1) }
      },
      getSnapshot: () => [...providers],
    },
  }
}

export { NEUTRAL_TOKENS, listPalette }
export type { CommandOutcome }
