// Controlled browser-acceptance fixture for the Workbench shell.
// This file is bundled standalone by build.mjs (no host, no real plugins); it is
// deliberately NOT named *.test.tsx so the vitest include never picks it up.
// External driver handle: window.__workbenchPreview (see handle below).
import { useSyncExternalStore } from 'react'
import { createRoot } from 'react-dom/client'
import { OwnedResources } from '@ordessa/extension-api'
import type { Commands, IDisposable, View } from '@extensions/ordessa.contracts/contract.js'
import { createCommands } from '../../../../plugins/commands/src/entry'
import { createWorkbench } from '../../src/model'
import { WorkbenchShell } from '../../src/shell'

// ---------- scenario knobs -------------------------------------------------
// Self-scroll vs non-self-scroll: one main view whose content switches between
// an internally scrolling box (fixed height + overflow-y:auto) and the same
// long content at natural height (the region's own scroller must take over).
type ScrollMode = 'internal' | 'external'
let scrollMode: ScrollMode = 'internal'
const scrollListeners = new Set<() => void>()
const setScrollMode = (mode: ScrollMode) => { scrollMode = mode; scrollListeners.forEach(f => f()) }
const useScrollMode = () => useSyncExternalStore(
  f => { scrollListeners.add(f); return () => { scrollListeners.delete(f) } },
  () => scrollMode)
const LONG_TEXT = Array.from({ length: 240 }, (_, i) => `验收长文本 ${i + 1}：Workbench 预览夹具内容段落。`)

function ScrollDemo() {
  const mode = useScrollMode()
  const paragraphs = LONG_TEXT.map(line => <p key={line}>{line}</p>)
  return <div>
    <p role="status">滚动模式：{mode === 'internal' ? '自滚动（视图内部固定高度容器）' : '非自滚动（自然超长高度）'}</p>
    <p>
      <button aria-label="切换为自滚动" onClick={() => setScrollMode('internal')}>自滚动</button>
      <button aria-label="切换为非自滚动" onClick={() => setScrollMode('external')}>非自滚动</button>
    </p>
    {mode === 'internal'
      ? <div data-testid="internal-scroller" style={{ height: 360, overflowY: 'auto', border: '1px solid currentColor', padding: 8 }}>{paragraphs}</div>
      : <div data-testid="natural-height">{paragraphs}</div>}
  </div>
}

// Popover anchor: a button contributed into the footer (statusbar component).
// handle.openPopover() anchors the popover overlay at exactly this live node.
let footerAnchor: HTMLButtonElement | null = null
function PopoverAnchorContribution() {
  return <button ref={node => { footerAnchor = node }} aria-label="打开 Popover"
    onClick={() => { try { handle.openPopover() } catch (e) { console.error(e) } }}>Popover</button>
}
function StatusCounterContribution() {
  const [count, setCount] = useCount()
  return <span data-testid="status-counter" title="状态栏组件 2">状态 {count} <button onClick={() => setCount(c => c + 1)}>+1</button></span>
}
// Local micro-store so the statusbar component contribution is interactive
// without pulling state from anywhere else.
let counterValue = 0
const counterListeners = new Set<(v: number) => void>()
function useCount(): [number, (f: (v: number) => number) => void] {
  const value = useSyncExternalStore(f => { counterListeners.add(f); return () => { counterListeners.delete(f) } }, () => counterValue)
  return [value, updater => { counterValue = updater(counterValue); counterListeners.forEach(f => f(counterValue)) }]
}

// ---------- composition ----------------------------------------------------
const lifetime = new OwnedResources()
const scope = new OwnedResources()
const model = createWorkbench(lifetime)
const commands: Commands = createCommands(lifetime)
const views = model.service.forScope(scope)
const composition = model.composition.forScope(scope)

// 1) Three modules, each with its home main view + sidebar left view.
const MODULES = [
  { id: 'chat', title: '对话' },
  { id: 'workflow', title: '工作流' },
  { id: 'sessions', title: '会话' },
] as const
for (const { id, title } of MODULES) {
  views.addView({ id: `${id}.main`, title: `${title}主区`, presentation: 'region', region: 'main', component: () => <p>{id} 主区内容（模块 home view）。</p> } satisfies View)
  views.addView({ id: `${id}.side`, title: `${title}侧栏`, presentation: 'region', region: 'left', component: () => <p>{id} 侧栏内容（模块 sidebar view）。</p> } satisfies View)
  composition.addModule({ id, title, homeViewId: `${id}.main`, sidebarViewId: `${id}.side` })
}

// 2) Twelve navigation command contributions for the long-navigation scroll test.
//    Eight open plain main views (also growing the tab strip), the last four
//    drive the dialog / scroll / long-title / settings scenarios.
for (let i = 1; i <= 8; i++) {
  const viewId = `nav.view.${i}`
  commands.forScope(scope).add({ id: `nav.cmd.${i}`, title: `导航视图 ${i}`, execute: () => model.service.open(viewId) })
  views.addView({ id: viewId, title: `导航视图 ${i}主区`, presentation: 'region', region: 'main', component: () => <p>导航视图 {i} 的主区内容。</p> } satisfies View)
  views.addUI({ id: `nav.ui.${i}`, kind: 'command', slot: 'navigation', command: `nav.cmd.${i}` })
}
commands.forScope(scope).add({ id: 'nav.cmd.dialog', title: '打开对话框', execute: () => { handle.openDialog() } })
views.addUI({ id: 'nav.ui.dialog', kind: 'command', slot: 'navigation', command: 'nav.cmd.dialog' })
commands.forScope(scope).add({ id: 'nav.cmd.scroll', title: '滚动演示', execute: () => model.service.open('preview.scroll') })
views.addUI({ id: 'nav.ui.scroll', kind: 'command', slot: 'navigation', command: 'nav.cmd.scroll' })
views.addView({ id: 'preview.scroll', title: '滚动模式演示主区', presentation: 'region', region: 'main', component: ScrollDemo } satisfies View)
const LONG_TITLE = '这是一个刻意超长的视图标题，用于在侧栏与主区标签栏中验证省略号截断行为是否稳定可靠，永不撑破布局'
commands.forScope(scope).add({ id: 'nav.cmd.longtitle', title: '超长标题', execute: () => model.service.open('preview.longtitle') })
views.addUI({ id: 'nav.ui.longtitle', kind: 'command', slot: 'navigation', command: 'nav.cmd.longtitle' })
views.addView({ id: 'preview.longtitle', title: LONG_TITLE, presentation: 'region', region: 'main', component: () => <p>超长标题视图内容：检查上方标题是否被截断。</p> } satisfies View)
commands.forScope(scope).add({ id: 'nav.cmd.settings', title: '设置到快捷键', execute: () => model.composition.openSettings('section.b') })
views.addUI({ id: 'nav.ui.settings', kind: 'command', slot: 'navigation', command: 'nav.cmd.settings' })

// 3) Footer contributions: two statusbar components + one utility command.
views.addUI({ id: 'footer.ui.anchor', kind: 'component', slot: 'statusbar', component: PopoverAnchorContribution })
views.addUI({ id: 'footer.ui.counter', kind: 'component', slot: 'statusbar', component: StatusCounterContribution })
commands.forScope(scope).add({ id: 'footer.cmd.about', title: '关于', execute: () => model.service.open('preview.about') })
views.addUI({ id: 'footer.ui.about', kind: 'command', slot: 'navigation', section: 'utility', command: 'footer.cmd.about' })
views.addView({ id: 'preview.about', title: '关于（全页）', presentation: 'full-page', component: () => <p>全页视图内容：工作区预览夹具的关于页。</p> } satisfies View)

// 4) Two settings sections.
composition.addSettingsSection({ id: 'section.a', order: 1, title: '外观分区', component: () => <>
  <p>外观设置内容。</p><button>预览主题</button><button>重置外观</button></> })
composition.addSettingsSection({ id: 'section.b', order: 2, title: '快捷键分区', component: () => <>
  <p>快捷键设置内容（openSettings("section.b") 会定位到这里）。</p><button>录制快捷键</button></> })

// 5) One popover overlay (anchored at the footer button above) and one dialog.
composition.addOverlay({ id: 'preview.popover', title: 'Popover 浮层', presentation: 'popover', component: ({ close }) => <>
  <p>锚点在底部状态栏按钮上的 popover。</p><button onClick={close}>关闭浮层</button></> })
composition.addOverlay({ id: 'preview.dialog', title: '对话框浮层', presentation: 'dialog', component: ({ close }) => <>
  <p>模式对话框内容：验证焦点圈定与遮罩。</p>
  <button onClick={close}>请求关闭</button><button>另一个可聚焦点</button></> })

// ---------- window handle + mount ------------------------------------------
const handle = {
  model, commands,
  activateModule(id: string) { model.composition.activateModule(id) },
  openView(id: string) { model.service.open(id) },
  closeView(id: string) { model.service.close(id) },
  openSettings(sectionId?: string) { model.composition.openSettings(sectionId) },
  openDialog(): IDisposable { return model.composition.openOverlay('preview.dialog') },
  openPopover(): IDisposable {
    if (!footerAnchor?.isConnected) throw Error('footer popover anchor is not mounted')
    return model.composition.openOverlay('preview.popover', { anchor: footerAnchor })
  },
  setScrollMode, getScrollMode: () => scrollMode,
  dispose() { root.unmount(); scope.dispose(); lifetime.dispose() },
}
declare global { interface Window { __workbenchPreview: typeof handle } }

const container = document.getElementById('root')
if (!container) throw Error('preview fixture requires <div id="root"> in preview.html')
const root = createRoot(container)
window.__workbenchPreview = handle
root.render(<WorkbenchShell model={model} commands={commands} />)

// ?selfcheck=1 drives the window handle through its key paths right after the
// first commit and stamps the outcome on <html data-selfcheck="ok:<overlays>"
// or "error:<message>", so a headless page dump can verify the fixture end to end.
if (new URLSearchParams(location.search).has('selfcheck')) {
  const wait = () => {
    if (!document.querySelector('[data-region="left"]')) { setTimeout(wait, 16); return }
    try {
      handle.activateModule('workflow')
      handle.openView('preview.scroll')
      handle.setScrollMode('external')
      handle.openDialog()
      handle.openPopover()
      handle.openSettings('section.b')
      // The opens above are state publishes: give React one task to commit
      // before the outcome is stamped, so the overlay count is truthful.
      setTimeout(() => { document.documentElement.dataset.selfcheck = `ok:${document.querySelectorAll('[data-overlay-id]').length}` }, 0)
    } catch (e) { document.documentElement.dataset.selfcheck = `error:${String(e)}` }
  }
  wait()
}
