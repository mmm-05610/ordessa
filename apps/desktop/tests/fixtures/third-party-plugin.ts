/**
 * 受控第三方 fixture 插件（PA-24 边界反例的正面一侧）。
 *
 * 纪律：只 import 公开面——`@extensions/ordessa.contracts/contract.js`（C-03…C-08）
 * 与 `@ordessa/extension-api`。**不得** import 任何宿主内部（apps 下的实现、
 * 平台包的 src 内部模块），下面的边界测试会逐字扫描并判红。
 *
 * 它完成 6 项接入：① 日志 ② 主题 ③ 设置分区 ④ 诊断片段 ⑤ 命令+快捷键 ⑥ wire 口。
 */
import {
  CommandSourceToken, HarnessAvailabilityToken, DiagnosticsContributionToken, KeybindingServiceToken, LoggerToken, SettingsContributionToken,
  ThemeServiceToken, WirePortToken,
  C07, type DiagnosticProvider, type HarnessReport, type Logger, type SettingsSection,
  type ThemeService, type WirePort, type WireResult,
} from '@extensions/ordessa.contracts/contract.js'
import type { Plugin, PluginContext, ResourceScope } from '@ordessa/extension-api'

export interface FixtureInjected {
  logger: Logger
  theme: ThemeService
  settings: { register(section: SettingsSection): () => void }
  diagnostics: { register(provider: DiagnosticProvider): () => void }
  commands: { forScope(scope: ResourceScope): { add(command: C07.Command): { dispose(): void } } }
  keybindings: { forScope(scope: ResourceScope): { bind(binding: { commandId: string; key: string }): { dispose(): void } } }
  wire: WirePort
}

export const FIXTURE_PLUGIN_ID = 'example.third-party'

/** 探针：测试用它断言"六项接入全部完成"，且插件**无法**读到令牌。 */
export interface FixtureProbe {
  readonly id: string
  readonly logged: number
  readonly themeResolved: 'light' | 'dark'
  readonly settingsSectionId: string | null
  readonly diagnosticFragmentId: string | null
  readonly commandId: string
  readonly bindingKey: string | null
  readonly wireResult: WireResult | null
  /** 插件可见对象的键：绝不能出现 token / tokenFile / origin。 */
  readonly wireKeys: readonly string[]
  readonly harnessReports: readonly HarnessReport[]
}

export function createFixturePlugin(probe: { value: FixtureProbe | null }): Plugin<FixtureProbe> {
  return {
    id: FIXTURE_PLUGIN_ID,
    provides: HarnessAvailabilityToken,
    autoStart: true,
    // 六项接入全部走公开 Token：日志/主题/设置分区/诊断片段/命令+快捷键/wire 口。
    requires: [LoggerToken, ThemeServiceToken, SettingsContributionToken, DiagnosticsContributionToken,
      CommandSourceToken, KeybindingServiceToken, WirePortToken],
    optional: [],
    activate: (context: PluginContext, logger: Logger, theme: ThemeService,
      settings: { register(section: SettingsSection): () => void },
      diagnostics: { register(provider: DiagnosticProvider): () => void },
      commands: FixtureInjected['commands'],
      keybindings: FixtureInjected['keybindings'],
      wire: WirePort): FixtureProbe => {
      const resources = context.resources
      let logged = 0
      const scoped = logger.child('plugin.example.third-party')
      scoped.info('fixture activated')

      const section: SettingsSection = {
        id: 'example.third-party',
        title: '第三方示例',
        order: 15,
        component: () => null,
        items: [{ id: 'example.third-party.enabled', kind: 'boolean', label: '启用' }],
      }
      const unregisterSection = settings.register(section)
      const provider: DiagnosticProvider = { id: 'example.third-party', collect: async () => ({ ok: true }) }
      const unregisterProvider = diagnostics.register(provider)

      const command: C07.Command = {
        id: 'example.third-party.run',
        title: '运行第三方示例命令',
        category: 'Example',
        run: () => { logged++ },
      }
      const registration = commands.forScope(resources).add(command)
      // `Mod+Shift+E`：与宿主命令不冲突，因此注册成功；冲突行为由 C-07 自己的反例覆盖。
      const binding = keybindings.forScope(resources).bind({ commandId: command.id, key: 'Mod+Shift+E' })

      // 探针只记录**已发生的接入**，不保存任何凭据。
      const value: FixtureProbe = {
        id: FIXTURE_PLUGIN_ID,
        logged,
        themeResolved: theme.resolved,
        settingsSectionId: section.id,
        diagnosticFragmentId: provider.id,
        commandId: command.id,
        bindingKey: 'Mod+Shift+E',
        wireResult: null,
        wireKeys: Object.keys(wire).sort(),
        harnessReports: [],
      }
      probe.value = value
      resources.add({
        isDisposed: false,
        dispose() { unregisterSection(); unregisterProvider(); binding.dispose(); registration.dispose() },
      })
      return value
    },
  }
}
