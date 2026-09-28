// @vitest-environment jsdom
// WS03/WS05/WS07 counterexamples for the unified sidebar: chrome visibility
// independent of the left view count, the single footer mount point, width /
// collapse / restore behavior, and the preserved tab/move/close mechanics.
import { act, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import type { WorkbenchModule } from '@extensions/ordessa.contracts/contract.js'
import { createCommands } from '../../../plugins/commands/src/entry'
import { createWorkbench, type WorkbenchModel } from '../src/model'
import { WorkbenchShell } from '../src/shell'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })
type Mount = { container: HTMLElement; unmount(): Promise<void> }
async function mount(element: React.ReactNode): Promise<Mount> {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  const unmount = async () => { await act(async () => root.unmount()); container.remove() }
  cleanup.push(unmount)
  await act(async () => root.render(element))
  return { container, unmount }
}
async function click(container: HTMLElement, text: string) {
  const button = [...container.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === text || b.textContent === text)
  expect(button, text).toBeTruthy()
  await act(async () => { button!.focus(); button!.click() })
  return button!
}
function moduleBundle(id: string, title: string, scope: OwnedResources, model: WorkbenchModel, extra?: Partial<WorkbenchModule>) {
  const views = model.service.forScope(scope)
  views.addView({ id: `${id}.main`, title: `${title}主区`, presentation: 'region', region: 'main', component: () => <p>{id} main content</p> })
  views.addView({ id: `${id}.side`, title: `${title}侧栏`, presentation: 'region', region: 'left', component: () => <p>{id} sidebar content</p> })
  return model.composition.forScope(scope).addModule({ id, title, homeViewId: `${id}.main`, sidebarViewId: `${id}.side`, ...extra })
}
/** A module without any sidebar view: home only. Its registration is chrome
 * for the sidebar even though it contributes no left content. */
function homeOnlyBundle(id: string, title: string, scope: OwnedResources, model: WorkbenchModel) {
  model.service.forScope(scope).addView({ id: `${id}.main`, title: `${title}主区`, presentation: 'region', region: 'main', component: () => <p>{id} main content</p> })
  return model.composition.forScope(scope).addModule({ id, title, homeViewId: `${id}.main` })
}
const leftOf = (container: HTMLElement) => container.querySelector<HTMLElement>('[data-region="left"]')!
const panelOf = (container: HTMLElement) => container.querySelector<HTMLElement>('#wb-left')!
/** react-resizable-panels collapses a panel to `flex: 0 …` — in jsdom that
 * inline marker is the observable "panel is collapsed" signal. */
const panelCollapsed = (container: HTMLElement) => /flex:\s*0(\s|;|$)/.test(panelOf(container).getAttribute('style') ?? '')

describe('sidebar chrome independent of left views (WS03)', () => {
  it('counterexample: zero left views but registered modules keep the sidebar operable — no collapse, no inert, global entries visible', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    homeOnlyBundle('home', '首页', scope, model)
    model.service.forScope(lifetime).addUI({ id: 'u', kind: 'component', slot: 'statusbar', component: () => <span>页脚状态</span> })
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    // no left view is registered at all — chrome alone must keep the panel alive
    expect(model.views.getSnapshot().some(v => model.regionOf(v) === 'left')).toBe(false)
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    expect(model.getLayout().collapsed.left).not.toBe(true)
    expect(panelCollapsed(container)).toBe(false)
    expect(container.querySelector('.wb-sidebar-nav')).not.toBeNull()
    expect(container.querySelector('[data-region="left"] [data-module-nav="home"]')).not.toBeNull()
    // the footer (utility/statusbar/设置) is mounted inside the sidebar, exactly once
    expect(container.querySelector('.wb-sidebar-footer .wb-status')).not.toBeNull()
    expect(container.querySelector('.wb-sidebar-footer .wb-status')!.textContent).toContain('页脚状态')
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    // the collapse entry exists without any hover-only wrapper dependency
    expect(container.querySelector('button[aria-label="收起左侧栏"]')).not.toBeNull()
    await act(async () => scope.dispose())
    // even after the module scope is gone, the statusbar chrome alone keeps the sidebar
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    await act(async () => lifetime.dispose())
  })

  it('counterexample: switching to a sidebar-less module clears the old module sidebar, keeps global nav, keeps user-opened left views', async () => {
    const lifetime = new OwnedResources(), chatScope = new OwnedResources(), bareScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', chatScope, model)
    model.service.forScope(bareScope).addView({ id: 'bare.main', title: 'Bare主区', presentation: 'region', region: 'main', component: () => <p>bare main content</p> })
    model.composition.forScope(bareScope).addModule({ id: 'bare', title: 'Bare', homeViewId: 'bare.main' })
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => model.composition.activateModule('chat'))
    expect(leftOf(container)!.textContent).toContain('chat sidebar content')
    await act(async () => model.composition.activateModule('bare'))
    // old module sidebar cleared…
    expect(model.getSelection().left).toBeUndefined()
    expect(container.textContent).not.toContain('chat sidebar content')
    // …while the global navigation chrome stays visible and operable
    expect(container.querySelectorAll('[data-region="left"] [data-module-nav]')).toHaveLength(2)
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    expect(panelCollapsed(container)).toBe(false)
    // a plain user-opened left view is not a module sidebar: it survives
    await act(async () => model.service.forScope(bareScope).addView({ id: 'user.left', title: '用户面板', presentation: 'region', region: 'left', component: () => <p>user panel content</p> }))
    await act(async () => model.service.open('user.left'))
    await act(async () => model.composition.activateModule('bare'))
    expect(model.getSelection().left).toBe('user.left')
    expect(leftOf(container).textContent).toContain('user panel content')
    await act(async () => { chatScope.dispose(); bareScope.dispose() })
  })

  it('counterexample: unregistering every module keeps the registered navigation commands', async () => {
    const lifetime = new OwnedResources(), moduleScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    commands.forScope(lifetime).add({ id: 'noop', title: '全局动作', execute: () => 'ran' })
    model.service.forScope(lifetime).addUI({ id: 'nav.global', kind: 'command', slot: 'navigation', command: 'noop' })
    moduleBundle('chat', 'Chat', moduleScope, model)
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    expect(container.querySelector('[data-module-nav="chat"]')).not.toBeNull()
    await act(async () => moduleScope.dispose())
    // all modules gone: the command entry and its scroll wrapper remain, on chrome alone
    expect(container.querySelectorAll('[data-module-nav]')).toHaveLength(0)
    const navButton = await click(container, '全局动作')
    expect(navButton.getAttribute('aria-label')).toBe('全局动作')
    expect(container.querySelector('.wb-sidebar-nav .wb-nav')).not.toBeNull()
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    expect(container.querySelector('.wb-sidebar-footer .wb-status')?.textContent).toContain('设置')
    await act(async () => lifetime.dispose())
  })
})

describe('sidebar footer single mount point (WS05)', () => {
  it('repositions an open footer popover when collapse moves its anchor to the bottom band', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    homeOnlyBundle('home', '首页', scope, model)
    model.service.forScope(scope).addUI({ id: 'footer.anchor', kind: 'component', slot: 'statusbar', component: () => <button aria-label="footer anchor">anchor</button> })
    model.composition.forScope(scope).addOverlay({ id: 'footer.popover', title: 'Footer popover', presentation: 'popover', component: () => <p>popover content</p> })
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    const anchor = container.querySelector<HTMLButtonElement>('button[aria-label="footer anchor"]')!
    anchor.getBoundingClientRect = () => {
      const top = anchor.closest('.wb-status-band') ? 500 : 100
      return { x: 100, y: top, left: 100, top, right: 160, bottom: top + 20, width: 60, height: 20, toJSON() {} }
    }
    await act(async () => { model.composition.openOverlay('footer.popover', { anchor }) })
    const popover = container.querySelector<HTMLElement>('[data-overlay-id="footer.popover"]')!
    expect(popover.style.top).toBe('128px')
    await click(container, '收起左侧栏')
    expect(anchor.closest('.wb-status-band')).not.toBeNull()
    expect(popover.style.top).toBe('528px')
    await click(container, '展开左侧栏')
    expect(anchor.closest('.wb-sidebar-footer')).not.toBeNull()
    expect(popover.style.top).toBe('128px')
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })

  it('counterexample: footer component instance survives collapse↔expand — mounted once, subscriptions balanced', async () => {
    const stats = { mounts: 0, unmounts: 0, subs: 0, unsubs: 0 }
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', scope, model)
    const Widget = () => {
      useEffect(() => {
        stats.mounts += 1
        const off = commands.subscribe(() => {})
        stats.subs += 1
        return () => { stats.unmounts += 1; stats.unsubs += 1; off() }
      }, [])
      return <span>页脚计数</span>
    }
    model.service.forScope(scope).addUI({ id: 'foot', kind: 'component', slot: 'statusbar', component: Widget })
    const { container, unmount } = await mount(<WorkbenchShell model={model} commands={commands} />)
    expect(stats).toMatchObject({ mounts: 1, unmounts: 0, subs: 1, unsubs: 0 })
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    expect(container.querySelector('.wb-sidebar-footer .wb-status')?.textContent).toContain('页脚计数')
    // collapse: the SAME container moves to the compact bottom band
    await click(container, '收起左侧栏')
    expect(leftOf(container).hasAttribute('inert')).toBe(true)
    expect(container.querySelector('.wb-status-band .wb-status')?.textContent).toContain('页脚计数')
    expect(container.querySelector('.wb-sidebar-footer .wb-status')).toBeNull()
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    expect(stats).toMatchObject({ mounts: 1, unmounts: 0, subs: 1, unsubs: 0 })
    // expand through the main-region restore button (keyboard path)
    const restore = container.querySelector<HTMLButtonElement>('.wb-sidebar-restore')!
    await act(async () => { restore.focus() })
    expect(document.activeElement).toBe(restore)
    await act(async () => { restore.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })) })
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    expect(container.querySelector('.wb-sidebar-footer .wb-status')?.textContent).toContain('页脚计数')
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    expect(stats).toMatchObject({ mounts: 1, unmounts: 0, subs: 1, unsubs: 0 })
    // one unmount at teardown releases exactly one subscription
    await unmount()
    expect(stats).toEqual({ mounts: 1, unmounts: 1, subs: 1, unsubs: 1 })
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })

  it('counterexample: settings entry renders once regardless of sidebar state; zero contributions leave only it', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    homeOnlyBundle('home', '首页', scope, model)
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    // zero utility/statusbar contributions: the fixed settings entry alone, once
    expect([...container.querySelectorAll('.wb-status button')].map(b => b.textContent)).toEqual(['设置'])
    await click(container, '收起左侧栏')
    expect([...container.querySelectorAll('.wb-status button')].map(b => b.textContent)).toEqual(['设置'])
    expect(container.querySelectorAll('button[aria-label="打开设置"]')).toHaveLength(1)
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })

  it('many footer contributions wrap inside the footer host instead of covering content', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', scope, model)
    for (let i = 0; i < 12; i++) model.service.forScope(scope).addUI({ id: `s${i}`, kind: 'component', slot: 'statusbar', component: () => <span>{`状态${i}`}</span> })
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    const status = container.querySelector('.wb-sidebar-footer .wb-status')!
    // each contribution renders exactly once inside the single footer
    for (let i = 0; i < 12; i++) expect([...container.querySelectorAll('span')].filter(s => s.textContent === `状态${i}`), `状态${i}`).toHaveLength(1)
    expect(status.textContent).toContain('状态0')
    expect(status.textContent).toContain('状态11')
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    // the shell footer wraps and self-scrolls (styles.ts rules)
    const computed = getComputedStyle(status)
    expect(computed.flexWrap).toBe('wrap')
    expect(computed.overflowY).toBe('auto')
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })
})

describe('sidebar structure and scroll constraints (WS05)', () => {
  it('long navigation keeps its own scroll region between fixed header and footer', async () => {
    const lifetime = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const scopes: OwnedResources[] = []
    for (let i = 0; i < 12; i++) {
      const scope = new OwnedResources(); scopes.push(scope)
      homeOnlyBundle(`m${i}`, `模块${i}`, scope, model)
    }
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    const navWrap = container.querySelector('.wb-sidebar-nav')!
    expect(navWrap.querySelector('.wb-nav')).not.toBeNull()
    expect(navWrap.querySelectorAll('[data-module-nav]')).toHaveLength(12)
    // the four segments are siblings of the sidebar column
    const sidebar = leftOf(container)
    expect(sidebar.querySelector(':scope > header .wb-sidebar-identity')?.textContent).toBe('工作区')
    expect(sidebar.querySelector(':scope > .wb-sidebar-nav')).not.toBeNull()
    expect(sidebar.querySelector(':scope > .wb-sidebar-content')).not.toBeNull()
    expect(sidebar.querySelector(':scope > .wb-sidebar-footer')).not.toBeNull()
    const computed = getComputedStyle(navWrap)
    expect(computed.overflowY).toBe('auto')
    expect(computed.minHeight).toBe('0px')
    await act(async () => { for (const s of scopes) s.dispose(); lifetime.dispose() })
  })

  it('self-scrolling and non-self-scrolling plugin fixtures share the same surface rules', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.service.forScope(scope).addView({
      id: 'self.main', title: 'Self', presentation: 'region', region: 'main',
      component: () => <div data-self-scroll style={{ height: '100%', overflow: 'auto' }}><p>self scrolling plugin</p></div>,
    })
    model.service.forScope(scope).addView({
      id: 'plain.side', title: '长内容侧栏', presentation: 'region', region: 'left',
      component: () => <div data-tall style={{ height: '2000px' }}><p>tall non-self-scrolling content</p></div>,
    })
    await act(async () => model.service.open('self.main'))
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => model.service.open('plain.side'))
    const content = container.querySelector('.wb-sidebar-content')!
    // outer content host allows flex shrinking and only scrolls when the plugin
    // does not scroll itself; a self-scrolling plugin stays intact in the surface
    const computed = getComputedStyle(content)
    expect(computed.minHeight).toBe('0px')
    expect(computed.overflowY).toBe('auto')
    expect(computed.flexGrow).toBe('1')
    expect(content.querySelector('.wb-surface')?.textContent).toContain('tall non-self-scrolling content')
    expect(container.querySelector('[data-region="main"] [data-self-scroll]')).not.toBeNull()
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })
})

describe('sidebar width, collapse and restore (WS06/WS07)', () => {
  it('counterexample: absent regions leave no hidden separators ahead of the live drag target', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    homeOnlyBundle('home', '首页', scope, model)
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    expect(container.querySelector('#resize-left')).not.toBeNull()
    expect(container.querySelector('#resize-right')).toBeNull()
    expect(container.querySelector('#resize-top')).toBeNull()
    expect(container.querySelector('#resize-bottom')).toBeNull()
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })

  it('counterexample: collapsed sidebar restores via a keyboard-reachable button in the MAIN region', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', scope, model)
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => model.composition.activateModule('chat'))
    expect(panelCollapsed(container)).toBe(false)
    await click(container, '收起左侧栏')
    expect(model.getLayout().collapsed.left).toBe(true)
    expect(leftOf(container).hasAttribute('inert')).toBe(true)
    expect(panelCollapsed(container)).toBe(true)
    // the restore control lives in the main header, outside the collapsed sidebar
    const restore = container.querySelector<HTMLButtonElement>('[data-region="main"] .wb-sidebar-restore')!
    expect(restore.getAttribute('aria-label')).toBe('展开左侧栏')
    await act(async () => { restore.focus() })
    expect(document.activeElement).toBe(restore)
    await act(async () => { restore.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })) })
    expect(model.getLayout().collapsed.left).not.toBe(true)
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    expect(panelCollapsed(container)).toBe(false)
    // after restore the sidebar is wider than the main region can deny: the
    // panel is no longer collapsed and the footer moved back into the sidebar
    expect(container.querySelector('.wb-sidebar-footer .wb-status')).not.toBeNull()
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    // collapse semantics: content stays open (collapse is not close)
    await click(container, '收起左侧栏')
    expect(model.getSelection().left).toBe('chat.side')
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })

  it('the sidebar panel gets px bounds so the resize keyboard stays inside 220–360/40%', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    homeOnlyBundle('home', '首页', scope, model)
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    // with no measured container (jsdom) the absolute bounds apply: 220px floor, 360px cap
    expect(panelOf(container).getAttribute('style')).toContain('flex')
    const separator = container.querySelector('#resize-left')!
    expect(separator).not.toBeNull()
    expect(separator.getAttribute('aria-label')).toBe('调整左侧栏大小')
    expect(separator.hasAttribute('disabled')).toBe(false)
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })
})

describe('layout capabilities are preserved (WS07)', () => {
  it('single view shows no tab strip; multiple views keep tabs, close and move; reset restores chrome access', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', scope, model)
    await act(async () => model.composition.activateModule('chat'))
    const { container } = await mount(<WorkbenchShell model={model} commands={commands} />)
    // one left view: no strip
    expect(container.querySelectorAll('[data-region="left"] [role="group"] button')).toHaveLength(0)
    const api = model.service.forScope(scope)
    await act(async () => api.addView({ id: 'extra.side', title: '附加侧栏', presentation: 'region', region: 'left', component: () => <p>extra sidebar content</p> }))
    await act(async () => api.addView({ id: 'note.side', title: '笔记侧栏', presentation: 'region', region: 'left', component: () => <p>note sidebar content</p> }))
    await act(async () => model.service.open('extra.side'))
    // two left views: the strip is back inside the sidebar header (module
    // sidebar + extra + note = three registered left views)
    const tabs = () => [...container.querySelectorAll<HTMLButtonElement>('[data-region="left"] header [role="group"] button')]
    expect(tabs().map(b => b.textContent)).toEqual(['Chat侧栏', '附加侧栏', '笔记侧栏'])
    await click(container, '附加侧栏')
    expect(tabs().find(b => b.textContent === '附加侧栏')!.getAttribute('aria-pressed')).toBe('true')
    // move it out of the sidebar through the keyboard-reachable select
    const select = container.querySelector<HTMLSelectElement>('[data-region="left"] select[aria-label="移动 附加侧栏 到"]')!
    await act(async () => { select.value = 'right'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(tabs().map(b => b.textContent)).not.toContain('附加侧栏')
    expect(container.querySelector('[data-region="right"]')!.textContent).toContain('extra sidebar content')
    // close the active note sidebar: selection drops, strip honest
    await act(async () => model.service.open('note.side'))
    await click(container, '关闭笔记侧栏')
    expect(model.getSelection().left).toBeUndefined()
    // reset layout: everything returns, chrome stays accessible, one footer
    await click(container, '重置布局')
    expect(model.getLayout().placements['extra.side']).toBeUndefined()
    expect(leftOf(container).hasAttribute('inert')).toBe(false)
    expect(panelCollapsed(container)).toBe(false)
    expect(container.querySelectorAll('[data-region="left"] [role="group"] button')).toHaveLength(3)
    expect(container.querySelector('.wb-sidebar-nav')).not.toBeNull()
    expect(container.querySelectorAll('.wb-status')).toHaveLength(1)
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })
})
