import { useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { runtime } from '@ordessa/extension-host'
import type { UiRequirementDiagnostic } from '@ordessa/ui-components/api'
import { App } from './app'
import { WindowChrome } from './window-chrome'
import { installedExtensions } from './extensions'
import './host.css'
// Foundations styles are loaded explicitly by the assembly (C8 F05): importing the
// package itself injects nothing, so a product that does not want them has none.
import '@ordessa/ui/styles.css'
const root = createRoot(document.getElementById('root')!)
const empty = runtime([])
root.render(<><WindowChrome /><App host={empty.host} /></>)
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
    {requirements.map(requirement => <p role="alert" key={`${requirement.componentId}/${requirement.major}`}>
      required ui component unavailable: {requirement.componentId} major {requirement.major}
      {requirement.selectedProviderId ? ` (selected ${requirement.selectedProviderId})` : ' (not selected)'}
    </p>)}
    {states.filter(s => s.phase === 'failed').map(s => <p role="alert" key={s.id}>{s.id}: {s.error}</p>)}
    {states.filter(s => s.phase === 'starting').map(s => <p role="status" key={s.id}>{s.id}: 启动中</p>)}
    <App host={desktop.host} />
  </>
}
async function start() {
  const loaded = await installedExtensions()
  const desktop = runtime(loaded.plugins)
  root.render(<Desktop desktop={desktop} failures={loaded.failures} requirements={[]} />)
  document.documentElement.dataset.ready = 'true'
  await desktop.start().catch(() => undefined)
  // Required-component reporting runs after activation, once (contract C7 §3).
  root.render(<Desktop desktop={desktop} failures={loaded.failures} requirements={requirementsOf(loaded.plugins)} />)
  document.documentElement.dataset.settled = 'true'
}
void start().catch(error => root.render(<><p role="alert">Startup failed: {String(error)}</p><App host={empty.host} /></>))
