import { Component, useSyncExternalStore, type ReactNode } from 'react'
import type { Host } from './runtime'
class RootBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() { return { failed: true } }
  render() { return this.state.failed ? <section role="alert">根界面加载失败。请检查已启用的扩展后重新启动。</section> : this.props.children }
}
/** Only a mounting boundary; no layout, views, commands or business vocabulary. */
export function Shell({ host }: { host: Host }) {
  const root = useSyncExternalStore(host.roots.subscribe, host.roots.getSnapshot)[0]
  const View = root?.component
  return View ? <RootBoundary key={root.id}><View /></RootBoundary> :
    <section className="host-diagnostic" data-testid="empty"><h1>Desktop 已启动</h1><p>尚无根界面，请启用一个工作台扩展。</p></section>
}
