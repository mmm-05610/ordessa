// @vitest-environment jsdom
// T020: the single-view bare-render fallback in src/shell.tsx (activeOf):
// an unclaimed single view renders without any selection; a module-claimed
// single view must NOT (the sidebar-less-activation counterexample in the
// other direction); and the region actions follow the active view.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createCommands } from '../../../plugins/commands/src/entry'
import { createWorkbench } from '../src/model'
import { WorkbenchShell } from '../src/shell'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })
async function mount(element: React.ReactNode) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}
async function click(container: HTMLElement, label: string) {
  const button = [...container.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === label || b.textContent === label)
  expect(button, label).toBeTruthy()
  await act(async () => { button!.focus(); button!.click() })
  return button!
}

describe('single-view bare fallback', () => {
  it('auto-renders a single unclaimed view with no selection, no tab strip, and move/close actions', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.service.forScope(scope).addView({ id: 'solo.main', title: 'Solo主区', presentation: 'region', region: 'main', component: () => <p>solo content</p> })
    // deliberately NOT opened: nothing is selected anywhere
    expect(model.getSelection()).toEqual({})
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const main = container.querySelector('[data-region="main"]')!
    // presence: the single view renders bare — content is visible although no
    // tab strip exists (a strip would need two or more views)
    expect(main.textContent).toContain('solo content')
    expect(main.querySelectorAll('[role="group"]')).toHaveLength(0)
    expect(main.getAttribute('data-active-view')).toBe('Solo主区')
    expect(main.querySelector('.wb-region-label')).toBeNull()
    expect(container.querySelector('.wb-empty')).toBeNull()
    // the move/close controls live in wb-region-actions next to the bare view
    expect(main.querySelector('.wb-region-actions select[aria-label="移动 Solo主区 到"]')).not.toBeNull()
    const close = main.querySelector('.wb-region-actions button[aria-label="关闭Solo主区"]')
    expect(close).not.toBeNull()
    // selection was never faked to achieve the render
    expect(model.getSelection()).toEqual({})
    // DESIGN RULING (T020 finding, T024 review): `close(id)` in the model only
    // drops the SELECTION pointing at that view — it never unregisters a
    // contributor's view. For a single UNCLAIMED view there is no selection to
    // drop, and dismissing it would leave a region with no tab strip and no nav
    // entry, i.e. an empty state nothing can reopen. So × is a deliberate no-op
    // here and the bare render stays. If the shell ever changes this to reach
    // the empty state, these two lines must be flipped explicitly.
    await click(container, '关闭Solo主区')
    expect(model.getSelection()).toEqual({})
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('solo content')
    expect(container.querySelector('.wb-empty')).toBeNull()
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })

  it('counterexample: a module-claimed single view stays hidden while a sidebar-less module is active', async () => {
    const lifetime = new OwnedResources(), chatScope = new OwnedResources(), bareScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const chatViews = model.service.forScope(chatScope)
    chatViews.addView({ id: 'chat.main', title: 'Chat主区', presentation: 'region', region: 'main', component: () => <p>chat main content</p> })
    chatViews.addView({ id: 'chat.side', title: 'Chat侧栏', presentation: 'region', region: 'left', component: () => <p>chat sidebar content</p> })
    const chatModule = model.composition.forScope(chatScope).addModule({ id: 'chat', title: 'Chat', homeViewId: 'chat.main', sidebarViewId: 'chat.side' })
    const bareViews = model.service.forScope(bareScope)
    bareViews.addView({ id: 'bare.main', title: 'Bare主区', presentation: 'region', region: 'main', component: () => <p>bare main content</p> })
    model.composition.forScope(bareScope).addModule({ id: 'bare', title: 'Bare', homeViewId: 'bare.main' })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // before any activation: the only left-region view is claimed by chat —
    // the fallback must not surface another module's sidebar, so it stays hidden
    const left = () => container.querySelector('[data-region="left"]')
    expect(left()!.hasAttribute('data-active-view')).toBe(false)
    expect(left()!.textContent).not.toContain('chat sidebar content')
    expect(left()!.querySelector('.wb-surface')).toBeNull()
    // and the same claim rule holds while the sidebar-less module is active
    await act(async () => model.composition.activateModule('bare'))
    expect(model.getSelection()).toEqual({ main: 'bare.main' })
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('bare main content')
    expect(container.textContent).not.toContain('chat main content')
    expect(left()!.hasAttribute('data-active-view')).toBe(false)
    expect(left()!.textContent).not.toContain('chat sidebar content')
    // once no module claims the sidebar view any more (module handle disposed,
    // view still registered), it is an unclaimed single view again: the bare
    // fallback renders it, exactly like the main-region case above
    await act(async () => chatModule.dispose())
    expect(left()!.getAttribute('data-active-view')).toBe('Chat侧栏')
    expect(left()!.textContent).toContain('chat sidebar content')
    expect(left()!.querySelectorAll('[role="group"]')).toHaveLength(0)
    await act(async () => { chatScope.dispose(); bareScope.dispose(); lifetime.dispose() })
  })

  it('a second view leaving registration collapses the strip 2→1 and keeps the remaining view active, open and rendered', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.service.forScope(scope).addView({ id: 'solo.main', title: 'Solo主区', presentation: 'region', region: 'main', component: () => <p>solo content</p> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // bare single view selected → opens as before; a second view brings the strip
    await act(async () => model.service.open('solo.main'))
    let other!: { dispose(): void }
    await act(async () => { other = model.service.forScope(scope).addView({ id: 'other.main', title: 'Other主区', presentation: 'region', region: 'main', component: () => <p>other content</p> }) })
    const strip = () => [...container.querySelectorAll('[data-region="main"] [role="group"] button')].map(b => b.textContent)
    expect(strip()).toEqual(['Other主区', 'Solo主区'])
    await click(container, 'Solo主区')
    // the region action closes the ACTIVE view by the × control: selection is
    // cleared and, with two views registered, main falls back to the visible
    // but unselected strip — closing never fakes an empty state
    await click(container, '关闭Solo主区')
    expect(model.getSelection().main).toBeUndefined()
    expect(strip()).toEqual(['Other主区', 'Solo主区'])
    expect(container.querySelector('[data-region="main"] .wb-empty')).not.toBeNull()
    // reopening through the tab keeps the strip honest
    await click(container, 'Solo主区')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('solo content')
    // now the OTHER view leaves registration: strip collapses 2→1, the
    // remaining single view keeps its selection, active marker and content
    await act(async () => other.dispose())
    expect(container.querySelectorAll('[data-region="main"] [role="group"]')).toHaveLength(0)
    expect(container.querySelector('[data-region="main"]')?.getAttribute('data-active-view')).toBe('Solo主区')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('solo content')
    expect(container.textContent).not.toContain('other content')
    expect(model.getSelection().main).toBe('solo.main')
    await act(async () => { scope.dispose(); lifetime.dispose() })
  })
})
