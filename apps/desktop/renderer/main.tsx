import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { runtime } from '@ordessa/extension-host'
import type { UiRequirementDiagnostic } from '@ordessa/ui-components/api'
import type { CommandOutcome, Fault } from '@extensions/ordessa.contracts/contract.js'
import { App } from './app'
import { WindowChrome } from './window-chrome'
import { installedExtensions } from './extensions'
import { buildHostServices, listPalette, type DesktopHostBridge } from './host-services'
import { AboutPanel, CommandPalette, FaultScreen, SettingsPage, type AboutInfo } from './desktop-ui'
import './host.css'
// Foundations styles are loaded explicitly by the assembly (C8 F05): importing the
// package itself injects nothing, so a product that does not want them has none.
import '@ordessa/ui/styles.css'
const root = createRoot(document.getElementById('root')!)
const empty = runtime([])
root.render(<><WindowChrome /><App host={empty.host} /></>)
const bridge = (): DesktopHostBridge | undefined => window.desktopHost
// A UI assembly built by the product reports its own missing required components;
// the host only asks for that generic optional capability, it knows no component name.
function requirementsOf(plugins: unknown[]): readonly UiRequirementDiagnostic[] {
  return plugins.flatMap(plugin => typeof (plugin as { inspectRequirements?: () => readonly UiRequirementDiagnostic[] }).inspectRequirements === 'function'
    ? (plugin as { inspectRequirements: () => readonly UiRequirementDiagnostic[] }).inspectRequirements() : [])
}
function Desktop({ desktop, failures, requirements }: {
  desktop: ReturnType<typeof runtime>, failures: {id: string; error: string}[], requirements: readonly UiRequirementDiagnostic[]
}) {
  const states = useSyncExternalStore(desktop.subscribe, desktop.getSnapshot)
  return <>
    <WindowChrome />
    {failures.map((failure, index) => <p role="alert" key={index}>{failure.id}: {failure.error}</p>)}
    {requirements.map((requirement) => <p role="alert" key={`${requirement.componentId}/${requirement.major}`}>
      required ui component unavailable: {requirement.componentId} major {requirement.major}
      {requirement.selectedProviderId ? ` (selected ${requirement.selectedProviderId})` : ' (not selected)'}
    </p>)}
    {states.filter(s => s.phase === 'failed').map(s => <p role="alert" key={s.id}>{s.id}: {s.error}</p>)}
    {states.filter(s => s.phase === 'starting').map(s => <p role="status" key={s.id}>{s.id}: 启动中</p>)}
    <App host={desktop.host} />
  </>
}

/**
 * 宿主外壳：故障屏优先（PA-12）；设置/关于/命令面板都是**按需打开的浮层**，
 * 默认不进入 DOM——产品的页面内容不能被宿主 chrome 污染，既有页面的文本契约保持不变。
 */
function HostShell({ desktop, about, services, failures, requirements }: {
  desktop: ReturnType<typeof runtime>
  about: AboutInfo | null
  services: ReturnType<typeof buildHostServices>
  failures: { id: string; error: string }[]
  requirements: readonly UiRequirementDiagnostic[]
}) {
  const [faults, setFaults] = useState<readonly Fault[]>([])
  const [overlay, setOverlay] = useState<'palette' | 'settings' | 'about' | null>(null)
  const [outcome, setOutcome] = useState<CommandOutcome | null>(null)
  const [updateState, setUpdateState] = useState<{ state: string; version?: string; reason?: string; received?: number; total?: number }>({ state: 'idle' })
  useEffect(() => {
    const host = bridge()
    if (!host) return
    // 宿主能力缺席是**正常**路径（README §3）：探测失败按"无故障"处理，不拖垮启动。
    void host.faults().then(raw => setFaults((raw as Fault[]).filter(fault => typeof fault?.reason === 'string'))).catch(() => setFaults([]))
  }, [])
  const entries = useMemo(() => listPalette(services.commands, services.keybindings, { hostReady: true }), [services])
  const run = useCallback(async (id: string) => { setOutcome(await services.commands.execute(id)) }, [services])
  // 键盘可达（PA-20）：Mod+Shift+P 打开命令面板，Esc 关闭。
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === 'p') {
        event.preventDefault()
        setOverlay(current => (current === 'palette' ? null : 'palette'))
      } else if (event.key === 'Escape') setOverlay(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return <>
    <Desktop desktop={desktop} failures={failures} requirements={requirements} />
    <FaultScreen faults={faults} onExportDiagnostics={() => void bridge()?.exportDiagnostics()} onOpenLogs={() => void bridge()?.openLogs()} />
    <nav className="od-host-chrome" aria-label="宿主入口">
      <button type="button" data-testid="open-palette" onClick={() => setOverlay('palette')}>命令面板</button>
      <button type="button" data-testid="open-settings" onClick={() => setOverlay('settings')}>设置</button>
      <button type="button" data-testid="open-about" onClick={() => setOverlay('about')}>关于</button>
    </nav>
    {overlay === 'palette'
      ? <CommandPalette open entries={entries} outcome={outcome} onRun={run} onClose={() => setOverlay(null)} />
      : null}
    {overlay === 'settings'
      ? <SettingsPage dataRoot="…" logLevel="info" updateState={updateState}
        onLogLevel={() => undefined} onOpenLogs={() => void bridge()?.openLogs()}
        onExportDiagnostics={() => void bridge()?.exportDiagnostics()}
        onCheckUpdate={() => void bridge()?.checkUpdate().then(state => setUpdateState(state as typeof updateState))}
        onDownloadUpdate={() => void bridge()?.downloadUpdate().then(state => setUpdateState(state as typeof updateState))}
        onApplyUpdate={() => void bridge()?.applyUpdate().then(state => setUpdateState(state as typeof updateState))}
        contributed={services.settings.getSnapshot()} onClose={() => setOverlay(null)} />
      : null}
    {overlay === 'about' && about ? <AboutPanel about={about} onOpenLicense={() => void bridge()?.openLicense()} /> : null}
  </>
}
async function start() {
  const host = bridge()
  const services = buildHostServices({ bridge: host })
  const about = host ? await host.about().catch(() => null) as AboutInfo | null : null
  const loaded = await installedExtensions()
  const desktop = runtime(loaded.plugins, services)
  const shell = (requirements: readonly UiRequirementDiagnostic[]) =>
    <HostShell desktop={desktop} about={about} services={services} failures={loaded.failures} requirements={requirements} />
  root.render(shell([]))
  document.documentElement.dataset.ready = 'true'
  await desktop.start().catch(() => undefined)
  // Required-component reporting runs after activation, once (contract C7 §3).
  root.render(shell(requirementsOf(loaded.plugins)))
  document.documentElement.dataset.settled = 'true'
}
void start().catch(error => root.render(<><p role="alert">Startup failed: {String(error)}</p><App host={empty.host} /></>))
