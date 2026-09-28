import { PluginRegistry, type Token } from '@lumino/coreutils'
import { Contributions, OwnedResources, type Host, type RootView, type Plugin, type PluginContext } from '@ordessa/extension-api'
import { CommandSourceToken, DiagnosticsContributionToken, HarnessAvailabilityToken, KeybindingServiceToken, LoggerToken, SettingsContributionToken, ThemeServiceToken, WirePortToken } from '../../contracts/foundation/src/product/tokens'
export { scoped, OwnedResources } from '@ordessa/extension-api'
export type { Host, RootView, Plugin } from '@ordessa/extension-api'
export interface PluginState { id: string; phase: 'registered' | 'starting' | 'active' | 'stopped' | 'failed'; error?: string }

// 平台服务类型从公开契约模块内联取（相对路径），使 runtime.ts 不依赖任何构建期别名。
type Logger = import('../../contracts/foundation/src/product/logging').Logger
type ThemeService = import('../../contracts/foundation/src/product/theme').ThemeService
type SettingsContribution = import('../../contracts/foundation/src/product/settings-diagnostics').SettingsContribution
type DiagnosticsContribution = import('../../contracts/foundation/src/product/settings-diagnostics').DiagnosticsContribution
type CommandSource = import('../../contracts/foundation/src/product/commands-keybindings').CommandSource
type KeybindingService = import('../../contracts/foundation/src/product/commands-keybindings').KeybindingService
type WirePort = import('../../contracts/foundation/src/product/wire-port').WirePort
type HarnessAvailability = import('../../contracts/foundation/src/product/harness-availability').HarnessAvailability

export interface PlatformServiceMap {
  logger?: Logger; theme?: ThemeService; settings?: SettingsContribution
  diagnostics?: DiagnosticsContribution; commands?: CommandSource; keybindings?: KeybindingService
  wire?: WirePort; harness?: HarnessAvailability
}

/**
 * 平台服务注册为**宿主自带的提供者插件**：lumino 只认 `provides`（没有 application 兜底），
 * 因此每个 token 一个内部 provider，插件用 `requires` 拿到对应实例。
 * 缺席的服务不注册 → 解析失败是显式的 `No provider`，而不是一个 undefined 悄悄流下去。
 */
function registerHostServices(registry: PluginRegistry<Host>, services: PlatformServiceMap) {
  const pairs: [Token<unknown>, unknown][] = [
    [LoggerToken, services.logger], [ThemeServiceToken, services.theme],
    [SettingsContributionToken, services.settings], [DiagnosticsContributionToken, services.diagnostics],
    [CommandSourceToken, services.commands], [KeybindingServiceToken, services.keybindings],
    [WirePortToken, services.wire], [HarnessAvailabilityToken, services.harness],
  ]
  for (const [token, service] of pairs) {
    if (service === undefined) continue
    registry.registerPlugin({ id: `ordessa.host.${token.name}`, provides: token, activate: () => service as never })
  }
}
/**
 * `services` 是宿主注入的平台服务（C-03/04/05/06/07/08）。缺席的服务**不注册**：
 * 插件若把它列进 `requires` 会得到显式的 `No provider`，列进 `optional` 则拿到 null
 * （README §3 缺席语义），两者都不会把 undefined 悄悄传下去。
 */
export function runtime(plugins: Plugin<any>[], services: PlatformServiceMap = {}) {
  const providers = new Set(), ids = new Set<string>()
  for (const plugin of plugins) {
    if (ids.has(plugin.id)) throw Error('Duplicate plugin: ' + plugin.id)
    ids.add(plugin.id)
    if (plugin.provides && providers.has(plugin.provides)) throw Error('Duplicate provider: ' + plugin.provides.name)
    if (plugin.provides) providers.add(plugin.provides)
  }
  // lumino 按 `application[token.name]` 解析服务，故宿主对象带 token 名字键；
  // 这些键不进入 `Host` 的公开形状（插件看到的公开面仍是 C-0x 契约本身）。
  const host: Host = { roots: new Contributions<RootView>() }
  const registry = new PluginRegistry<Host>()
  registry.application = host
  registerHostServices(registry, services)
  const failures: { id: string; error: string }[] = []
  const states = new Map<string, PluginState>(), listeners = new Set<() => void>()
  let snapshot: PluginState[] = []
  function update(id: string, phase: PluginState['phase'], error?: string) {
    states.set(id, { id, phase, ...(error ? { error } : {}) })
    snapshot = [...states.values()]
    listeners.forEach(listener => listener())
  }
  function failed(id: string, error: unknown) {
    const message = String(error)
    if (!failures.some(f => f.id === id && f.error === message)) failures.push({ id, error: message })
    update(id, 'failed', message)
  }
  for (const plugin of plugins) {
    let owned: OwnedResources | undefined
    let active: { context: PluginContext; services: any[] } | undefined
    const close = () => { const resources = owned; owned = undefined; resources?.dispose() }
    try {
      registry.registerPlugin({
        ...plugin,
        async activate(_host, ...services) {
          update(plugin.id, 'starting')
          const resources = new OwnedResources()
          owned = resources
          const context: PluginContext = Object.freeze({
            root: Object.freeze({ mount(view: RootView) {
              if (resources.isDisposed) throw Error('Plugin scope is closed')
              if (host.roots.getSnapshot().length) throw Error('Root view already mounted')
              return resources.add(host.roots.add(view))
            } }),
            resources: Object.freeze({ get isDisposed() { return resources.isDisposed }, add: resources.add.bind(resources) }),
          })
          active = { context, services }
          try {
            const result = await plugin.activate(context, ...services)
            update(plugin.id, 'active')
            return result
          } catch (error) {
            let cause = error
            try { close() } catch (cleanup) { cause = new AggregateError([error, cleanup], 'Activation and cleanup failed') }
            failed(plugin.id, cause)
            active = undefined
            throw cause
          }
        },
        async deactivate() {
          const errors: unknown[] = []
          const previous = active
          active = undefined
          // Close first: even callbacks during async cleanup cannot register again.
          try { close() } catch (error) { errors.push(error) }
          try { if (previous) await plugin.deactivate?.(previous.context, ...previous.services) } catch (error) { errors.push(error) }
          if (errors.length) {
            const error = new AggregateError(errors, 'Deactivation cleanup failed')
            failed(plugin.id, error)
            throw error
          }
          update(plugin.id, 'stopped')
        },
      })
      update(plugin.id, 'registered')
    } catch (error) { failed(plugin.id, error) }
  }
  async function activate(id: string) {
    if (states.get(id)?.phase !== 'active') update(id, 'starting')
    try { return await registry.activatePlugin(id) }
    catch (error) { failed(id, error); throw error }
  }
  return {
    host, failures, activate,
    getSnapshot: () => snapshot,
    subscribe: (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener) } },
    deactivate: (id: string) => registry.deactivatePlugin(id),
    async start() {
      // Lumino still resolves real dependencies. Unrelated autoStart plugins start concurrently.
      await Promise.allSettled(plugins.filter(p => p.autoStart === true).map(p => activate(p.id)))
    },
  }
}
