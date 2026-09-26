// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources, type IDisposable } from '@ordessa/extension-api'
import type { WorkbenchModule } from '@extensions/ordessa.contracts/contract.js'
import { createCommands } from '../../commands/src/entry'
import { createWorkbench } from '../src/model'
import { WorkbenchShell } from '../src/shell'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
// jsdom has no layout/ResizeObserver. Geometry is verified separately in Electron.
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn(); vi.restoreAllMocks() })
async function mount(element: React.ReactNode) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}
async function click(container: HTMLElement, text: string) {
  const button = [...container.querySelectorAll('button')].find(b => b.getAttribute('aria-label') === text || b.textContent === text)
  expect(button, text).toBeTruthy()
  await act(async () => { button!.focus(); button!.click() })
  return button!
}
/** Registers one module with its two views (main home + left sidebar) in the given scope; returns the module handle. */
function moduleBundle(id: string, title: string, scope: OwnedResources, model: ReturnType<typeof createWorkbench>, extra?: Partial<WorkbenchModule>) {
  const views = model.service.forScope(scope)
  views.addView({ id: `${id}.main`, title: `${title}主区`, presentation: 'region', region: 'main', component: () => <p>{id} main content</p> })
  views.addView({ id: `${id}.side`, title: `${title}侧栏`, presentation: 'region', region: 'left', component: () => <p>{id} sidebar content</p> })
  return model.composition.forScope(scope).addModule({ id, title, homeViewId: `${id}.main`, sidebarViewId: `${id}.side`, ...extra })
}
function openerButton(label: string) {
  const opener = document.createElement('button'); opener.textContent = label; document.body.append(opener)
  cleanup.push(async () => opener.remove())
  return opener
}
/** Focuses the target and dispatches a (Shift+)Tab keydown, asserting the surface swallowed it. */
function pressTab(target: HTMLElement, shift = false) {
  target.focus()
  const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey: shift, bubbles: true, cancelable: true })
  target.dispatchEvent(event)
  expect(event.defaultPrevented, shift ? 'Shift+Tab' : 'Tab').toBe(true)
}

describe('workbench composition: module registration and navigation', () => {
  it('counterexample: empty product mounts with an empty state, no module entries — and shows one as soon as a module registers', async () => {
    const lifetime = new OwnedResources(), model = createWorkbench(lifetime)
    const container = await mount(<WorkbenchShell model={model} commands={createCommands(lifetime)} />)
    expect(container.querySelectorAll('[data-region]')).toHaveLength(5)
    expect(container.querySelector('.wb-empty')?.textContent).toContain('工作区已就绪')
    // absence: no module navigation entries, and no navigation block reserving space
    expect(container.querySelectorAll('[data-module-nav]')).toHaveLength(0)
    expect(container.querySelector('.wb-nav')).toBeNull()
    // positive pairing: a registered module makes exactly its entry appear
    const scope = new OwnedResources()
    await act(async () => moduleBundle('chat', 'Chat', scope, model))
    await act(async () => model.composition.activateModule('chat'))
    expect(container.querySelectorAll('[data-module-nav]')).toHaveLength(1)
    expect(container.querySelector('[data-module-nav="chat"]')?.getAttribute('aria-pressed')).toBe('true')
    await act(async () => scope.dispose())
  })

  it('counterexample: removing a module erases its navigation, sidebar and main view without breaking a peer', async () => {
    const lifetime = new OwnedResources(), chatScope = new OwnedResources(), workflowScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', chatScope, model)
    const workflowModule = moduleBundle('workflow', 'Workflow', workflowScope, model)
    await act(async () => model.composition.activateModule('chat'))
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // presence before: both entries in order, chat content rendered in main and left
    expect([...container.querySelectorAll('[data-module-nav]')].map(b => b.getAttribute('data-module-nav'))).toEqual(['chat', 'workflow'])
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('chat main content')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('chat sidebar content')
    await act(async () => chatScope.dispose())
    // absence: chat navigation, main and sidebar contributions are gone
    expect(container.querySelector('[data-module-nav="chat"]')).toBeNull()
    expect(container.textContent).not.toContain('chat main content')
    expect(container.textContent).not.toContain('chat sidebar content')
    expect(model.getSelection().main).toBeUndefined()
    // positive: the peer module still activates and its content is intact
    await act(async () => model.composition.activateModule('workflow'))
    expect(container.querySelector('[data-module-nav="workflow"]')).not.toBeNull()
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('workflow main content')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('workflow sidebar content')
    // module-handle disposal alone: navigation entry disappears, selection reference is cleaned,
    // while the scope-owned views stay registered for a future re-registration
    await act(async () => workflowModule.dispose())
    expect(container.querySelector('[data-module-nav="workflow"]')).toBeNull()
    expect(model.getSelection().main).toBeUndefined()
    expect(model.views.getSnapshot().map(v => v.id)).toEqual(expect.arrayContaining(['workflow.main', 'workflow.side']))
    await act(async () => workflowScope.dispose())
  })

  it('counterexample: activation rejects missing or misplaced default views — no fallback, no false success', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const composition = model.composition
    // a valid, selected main view proves activation never selects an unrelated view
    model.service.forScope(scope).addView({ id: 'other', title: 'Other', presentation: 'region', region: 'main', component: () => <p>other content</p> })
    model.service.open('other')
    composition.forScope(scope).addModule({ id: 'ghost', title: 'Ghost', homeViewId: 'ghost.main' })
    model.service.forScope(scope).addView({ id: 'misplaced.main', title: 'Misplaced', presentation: 'region', region: 'left', component: () => <p>misplaced</p> })
    composition.forScope(scope).addModule({ id: 'misplaced', title: 'Misplaced', homeViewId: 'misplaced.main' })
    model.service.forScope(scope).addView({ id: 'badside.main', title: 'BadSide', presentation: 'region', region: 'main', component: () => <p>badside</p> })
    model.service.forScope(scope).addView({ id: 'badside.side', title: 'BadSide side', presentation: 'region', region: 'main', component: () => <p>badside side</p> })
    composition.forScope(scope).addModule({ id: 'badside', title: 'BadSide', homeViewId: 'badside.main', sidebarViewId: 'badside.side' })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    expect(() => composition.activateModule('ghost')).toThrow('not registered')
    expect(() => composition.activateModule('misplaced')).toThrow('main-region')
    expect(() => composition.activateModule('badside')).toThrow('left-region')
    for (const [id, label, message] of [['ghost', 'Ghost', 'not registered'], ['misplaced', 'Misplaced', 'main-region'], ['badside', 'BadSide', 'left-region']] as const) {
      // click the module navigation entry itself (a view tab could share the module's title)
      const nav = container.querySelector<HTMLButtonElement>(`[data-module-nav="${id}"]`)
      expect(nav, id).toBeTruthy()
      await act(async () => { nav!.focus(); nav!.click() })
      // the failure is visible in the shell, not silent
      expect(container.querySelector('[role="alert"]')?.textContent).toContain(message)
      // no false success: the broken module never shows as selected
      expect(nav!.getAttribute('aria-pressed')).toBe('false')
    }
    // selection is exactly what it was before every attempt
    expect(model.getSelection()).toEqual({ main: 'other' })
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('other content')
    await act(async () => scope.dispose())
  })

  it('counterexample: duplicate module id fails with exactly one entry left; closed scopes refuse late writes', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const composition = model.composition, api = composition.forScope(scope)
    moduleBundle('chat', 'Chat', scope, model)
    expect(() => api.addModule({ id: 'chat', title: 'Chat again', homeViewId: 'chat.main' })).toThrow('Duplicate')
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // exactly one entry survives — a positive count, not a zero-match
    expect(container.querySelectorAll('[data-module-nav="chat"]')).toHaveLength(1)
    await act(async () => scope.dispose())
    expect(() => composition.forScope(scope).addModule({ id: 'late', title: 'Late', homeViewId: 'x' })).toThrow('closed')
    expect(() => api.addModule({ id: 'late', title: 'Late', homeViewId: 'x' })).toThrow('closed')
    // the disposed module's entry did not linger
    expect(container.querySelector('[data-module-nav="chat"]')).toBeNull()
    // positive pairing: a fresh scope registers the same ids again
    const fresh = new OwnedResources()
    await act(async () => moduleBundle('chat', 'Chat', fresh, model))
    await act(async () => {})
    expect(container.querySelectorAll('[data-module-nav="chat"]')).toHaveLength(1)
    await act(async () => fresh.dispose())
    // a closed workbench lifetime refuses registration too
    await act(async () => lifetime.dispose())
    const another = new OwnedResources()
    expect(() => composition.forScope(another).addModule({ id: 'x', title: 'X', homeViewId: 'x' })).toThrow('closed')
    expect(() => composition.activateModule('chat')).toThrow('closed')
    await act(async () => another.dispose())
  })

  it('counterexample: close/hide/switch/module operations dispose nothing — while real disposal is observable', async () => {
    const lifetime = new OwnedResources(), chatScope = new OwnedResources(), workflowScope = new OwnedResources(), overlayScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const tracked: { label: string; calls: number }[] = []
    const track = <T extends IDisposable>(label: string, handle: T): T => {
      const record = { label, calls: 0 }
      tracked.push(record)
      const original = handle.dispose.bind(handle)
      ;(handle as { dispose(): void }).dispose = () => { record.calls += 1; original() }
      return handle
    }
    track('chat.module', model.composition.forScope(chatScope).addModule({ id: 'chat', title: 'Chat', homeViewId: 'chat.main', sidebarViewId: 'chat.side' }))
    track('chat.home', model.service.forScope(chatScope).addView({ id: 'chat.main', title: 'Chat主区', presentation: 'region', region: 'main', component: () => <p>chat main content</p> }))
    track('chat.side', model.service.forScope(chatScope).addView({ id: 'chat.side', title: 'Chat侧栏', presentation: 'region', region: 'left', component: () => <p>chat sidebar content</p> }))
    track('workflow.module', model.composition.forScope(workflowScope).addModule({ id: 'workflow', title: 'Workflow', homeViewId: 'workflow.main', sidebarViewId: 'workflow.side' }))
    track('workflow.home', model.service.forScope(workflowScope).addView({ id: 'workflow.main', title: 'Workflow主区', presentation: 'region', region: 'main', component: () => <p>workflow main content</p> }))
    track('workflow.side', model.service.forScope(workflowScope).addView({ id: 'workflow.side', title: 'Workflow侧栏', presentation: 'region', region: 'left', component: () => <p>workflow sidebar content</p> }))
    track('dialog.overlay', model.composition.forScope(overlayScope).addOverlay({ id: 'dialog', title: 'Dialog', presentation: 'dialog', component: () => <p>dialog content</p> }))
    track('settings.section', model.composition.forScope(overlayScope).addSettingsSection({ id: 'general', title: 'General', component: () => <p>general</p> }))
    track('full.page', model.service.forScope(lifetime).addView({ id: 'full', title: 'Full', presentation: 'full-page', component: () => <p>full content</p> }))
    const chatDispose = vi.spyOn(chatScope, 'dispose')
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // the full suite of UI-state operations
    await act(async () => {
      model.composition.activateModule('chat')
      model.composition.activateModule('workflow')
      model.composition.activateModule('chat')
      model.service.open('full')
      model.service.close('full')
      model.service.close('chat.main')
      model.service.open('chat.main')
      model.composition.openOverlay('dialog').dispose()
      model.composition.openSettings()
      model.closeTopOverlay()
    })
    // zero disposal happened; every scope is still alive
    for (const record of tracked) expect(record.calls, record.label).toBe(0)
    expect(chatDispose).not.toHaveBeenCalled()
    expect(chatScope.isDisposed).toBe(false)
    expect(workflowScope.isDisposed).toBe(false)
    expect(overlayScope.isDisposed).toBe(false)
    // presence: the contributions are all still live and renderable
    expect(container.querySelector('[data-module-nav="chat"]')).not.toBeNull()
    expect(model.views.getSnapshot().map(v => v.id)).toEqual(expect.arrayContaining(['chat.main', 'workflow.main', 'full']))
    // falsifiable pairing: the same spies do observe a real disposal
    await act(async () => chatScope.dispose())
    expect(chatDispose).toHaveBeenCalledTimes(1)
    expect(tracked.find(r => r.label === 'chat.module')!.calls).toBe(1)
    expect(tracked.find(r => r.label === 'chat.home')!.calls).toBe(1)
    expect(chatScope.isDisposed).toBe(true)
    expect(tracked.find(r => r.label === 'workflow.module')!.calls).toBe(0)
    await act(async () => { workflowScope.dispose(); overlayScope.dispose(); lifetime.dispose() })
  })
})

describe('workbench composition: overlays', () => {
  it('counterexample: overlay owner unload closes the instance and restores focus to a connected target', async () => {
    const lifetime = new OwnedResources(), owner = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(owner).addOverlay({ id: 'dialog', title: 'Dialog', presentation: 'dialog', component: () => <p>dialog content</p> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const opener = openerButton('opener')
    await act(async () => opener.focus())
    // absence before: no overlay, background interactive
    expect(container.querySelector('[data-testid="wb-overlays"]')).toBeNull()
    expect(container.querySelector('[data-testid="workspace"]')?.hasAttribute('inert')).toBe(false)
    let handle!: IDisposable
    await act(async () => { handle = model.composition.openOverlay('dialog') })
    // presence: dialog open with modal semantics
    expect(container.querySelector('[data-overlay-id="dialog"]')).not.toBeNull()
    expect(container.querySelector('[data-overlay-id="dialog"] [role="dialog"]')?.getAttribute('aria-modal')).toBe('true')
    expect(container.querySelector('[data-testid="workspace"]')?.hasAttribute('inert')).toBe(true)
    await act(async () => owner.dispose())
    await act(async () => {}) // flush the queued focus restoration
    // the overlay is closed and focus sits on a connected element again
    expect(container.querySelector('[data-overlay-id="dialog"]')).toBeNull()
    expect(container.querySelector('[data-testid="workspace"]')?.hasAttribute('inert')).toBe(false)
    expect(opener.isConnected).toBe(true)
    expect(document.activeElement).toBe(opener)
    // the handle reports the truth: the instance is already gone from the stack
    expect(handle.isDisposed).toBe(true)
    // a late dispose of the returned handle is harmless and observable
    handle.dispose()
    expect(handle.isDisposed).toBe(true)
    await act(async () => { owner.dispose(); lifetime.dispose() })
  })

  it('counterexample: a dead or missing popover anchor fails explicitly; a live anchor opens', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(scope).addOverlay({ id: 'picker', title: 'Picker', presentation: 'popover', component: () => <p>picker content</p> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const opener = openerButton('opener')
    await act(async () => opener.focus())
    const detached = document.createElement('button')
    expect(() => model.composition.openOverlay('picker', { anchor: detached })).toThrow('anchor')
    expect(() => model.composition.openOverlay('picker')).toThrow('anchor')
    const attached = document.createElement('button'); document.body.append(attached)
    cleanup.push(async () => attached.remove())
    attached.remove() // connected once, then removed: still a dead anchor
    expect(() => model.composition.openOverlay('picker', { anchor: attached })).toThrow('anchor')
    // focus was not swallowed and nothing opened
    expect(document.activeElement).toBe(opener)
    expect(container.querySelectorAll('[data-presentation="popover"]')).toHaveLength(0)
    // positive pairing: a connected anchor opens the popover inside the viewport
    document.body.append(attached)
    await act(async () => { model.composition.openOverlay('picker', { anchor: attached }) })
    expect(container.querySelector('[data-overlay-id="picker"]')).not.toBeNull()
    expect(container.querySelector('[data-presentation="popover"]')?.getAttribute('aria-modal')).toBeNull()
    const style = (container.querySelector('[data-presentation="popover"]') as HTMLElement).style
    expect(parseInt(style.left, 10)).toBeGreaterThanOrEqual(0)
    expect(parseInt(style.left, 10)).toBeLessThanOrEqual(window.innerWidth)
    expect(parseInt(style.top, 10)).toBeGreaterThanOrEqual(0)
    expect(parseInt(style.top, 10)).toBeLessThanOrEqual(window.innerHeight)
    await act(async () => scope.dispose())
  })

  it('counterexample: a popover whose anchor leaves the DOM closes explicitly and refocuses a safe target', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(scope).addOverlay({ id: 'picker', title: 'Picker', presentation: 'popover', component: () => <p>picker content</p> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const anchor = openerButton('anchor opener')
    await act(async () => anchor.focus())
    let handle!: IDisposable
    await act(async () => { handle = model.composition.openOverlay('picker', { anchor }) })
    expect(container.querySelector('[data-overlay-id="picker"]')).not.toBeNull()
    // the anchor is the restore target too: removing it must close and land focus on the workspace
    await act(async () => { anchor.remove() })
    expect(container.querySelector('[data-overlay-id="picker"]')).toBeNull()
    expect(handle.isDisposed).toBe(true)
    await act(async () => {}) // flush the queued focus restoration
    const workspace = container.querySelector('[data-testid="workspace"]')
    expect(workspace).not.toBeNull()
    const active = document.activeElement
    expect(active === workspace || (workspace as HTMLElement).contains(active)).toBe(true)
    expect((active as HTMLElement).isConnected).toBe(true)
    await act(async () => scope.dispose())
  })

  it('closes the stack LIFO with Escape, one overlay at a time, and unsets modality at empty', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const api = model.composition.forScope(scope)
    api.addOverlay({ id: 'one', title: 'One', presentation: 'dialog', component: () => <p>one content</p> })
    api.addOverlay({ id: 'two', title: 'Two', presentation: 'dialog', component: () => <p>two content</p> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => { model.composition.openOverlay('one'); model.composition.openOverlay('two') })
    const open = () => [...container.querySelectorAll('[data-overlay-id]')].map(n => n.getAttribute('data-overlay-id'))
    expect(open()).toEqual(['one', 'two'])
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
    expect(open()).toEqual(['one'])
    expect(container.textContent).toContain('one content')
    expect(container.querySelector('[data-overlay-id="one"] [role="dialog"]')?.getAttribute('aria-modal')).toBe('true')
    await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
    expect(open()).toEqual([])
    expect(container.querySelector('[data-testid="wb-overlays"]')).toBeNull()
    expect(container.querySelector('[data-testid="workspace"]')?.hasAttribute('inert')).toBe(false)
    await act(async () => scope.dispose())
  })

  it('lets the contributor request close through its component prop and restores focus', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(scope).addOverlay({ id: 'ask', title: 'Ask', presentation: 'dialog', component: ({ close }) => <button onClick={close}>请求关闭</button> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const opener = openerButton('opener')
    await act(async () => opener.focus())
    await act(async () => { model.composition.openOverlay('ask') })
    expect(container.querySelector('[data-overlay-id="ask"]')).not.toBeNull()
    await click(container, '请求关闭')
    expect(container.querySelector('[data-overlay-id="ask"]')).toBeNull()
    await act(async () => {})
    expect(document.activeElement).toBe(opener)
    await act(async () => scope.dispose())
  })

  it('counterexample: workbench errors stay visible above an open overlay', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const api = model.composition.forScope(scope)
    api.addOverlay({ id: 'dialog', title: 'Dialog', presentation: 'dialog', component: () => <p>dialog content</p> })
    api.addModule({ id: 'ghost', title: 'Ghost', homeViewId: 'ghost.main' })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => model.composition.openOverlay('dialog'))
    expect(container.querySelector('[data-overlay-id="dialog"]')).not.toBeNull()
    // jsdom does not block clicks into an inert background: activation fails into the shell error
    const nav = container.querySelector<HTMLButtonElement>('[data-module-nav="ghost"]')
    expect(nav, 'ghost').toBeTruthy()
    await act(async () => { nav!.focus(); nav!.click() })
    const alert = container.querySelector('[role="alert"]')
    expect(alert?.textContent).toContain('not registered')
    const errorZ = parseInt(getComputedStyle(alert as HTMLElement).zIndex, 10)
    const overlayZ = parseInt(getComputedStyle(container.querySelector('.wb-overlays') as HTMLElement).zIndex, 10)
    expect(errorZ).toBeGreaterThan(overlayZ)
    await act(async () => scope.dispose())
  })

  it('counterexample: modal overlay Tab cycling stays inside the surface, off the inert workspace', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(scope).addOverlay({ id: 'dialog', title: 'Dialog', presentation: 'dialog',
      component: () => <><button>内容甲</button><button>内容乙</button></> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => model.composition.openOverlay('dialog'))
    const surface = container.querySelector('.wb-overlay-dialog .wb-overlay-surface') as HTMLElement
    const buttons = [...surface.querySelectorAll('button')]
    expect(buttons.map(b => b.textContent)).toEqual(['×', '内容甲', '内容乙'])
    expect(surface.contains(document.activeElement)).toBe(true)
    const workspace = container.querySelector('[data-testid="workspace"]') as HTMLElement
    const inSurface = () => surface.contains(document.activeElement) && !workspace.contains(document.activeElement)
    // Tab from the last focusable wraps to the first
    pressTab(buttons[buttons.length - 1])
    expect(document.activeElement).toBe(buttons[0])
    expect(inSurface()).toBe(true)
    // Shift+Tab from the first wraps back to the last
    pressTab(buttons[0], true)
    expect(document.activeElement).toBe(buttons[buttons.length - 1])
    expect(inSurface()).toBe(true)
    await act(async () => scope.dispose())
  })

  it('counterexample: the settings page wraps Tab inside its surface too', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(scope).addSettingsSection({ id: 'general', title: 'General', component: () => <><button>设置甲</button><button>设置乙</button></> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await click(container, '打开设置')
    const surface = container.querySelector('.wb-settings') as HTMLElement
    const buttons = [...surface.querySelectorAll('button')]
    const last = buttons[buttons.length - 1]
    pressTab(last)
    expect(document.activeElement).toBe(buttons[0])
    pressTab(buttons[0], true)
    expect(document.activeElement).toBe(last)
    await act(async () => scope.dispose())
  })
})

describe('workbench composition: settings and screen structure', () => {
  it('settings page is Workbench-owned: sections ordered, located, and removed on contributor unload', async () => {
    const lifetime = new OwnedResources(), alpha = new OwnedResources(), zeta = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    model.composition.forScope(zeta).addSettingsSection({ id: 'zeta', title: 'Zeta 分区', order: 2, component: () => <p>zeta controls</p> })
    model.composition.forScope(alpha).addSettingsSection({ id: 'alpha', title: 'Alpha 分区', order: 1, component: () => <p>alpha controls</p> })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await click(container, '打开设置')
    const page = () => container.querySelector('[data-overlay-id="ordessa.workbench.settings"]')
    expect(page()).not.toBeNull()
    // sorted by order/id, not by registration order (zeta was registered first)
    expect([...page()!.querySelectorAll('[data-section-id]')].map(n => n.getAttribute('data-section-id'))).toEqual(['alpha', 'zeta'])
    expect(page()!.textContent).toContain('alpha controls')
    expect(page()!.textContent).toContain('zeta controls')
    // locating a section marks it
    await act(async () => model.composition.openSettings('zeta'))
    expect(page()!.querySelector('[data-section-id="zeta"]')?.hasAttribute('data-active-section')).toBe(true)
    expect(page()!.querySelector('[data-section-id="alpha"]')?.hasAttribute('data-active-section')).toBe(false)
    // unknown sections fail explicitly
    expect(() => model.composition.openSettings('nope')).toThrow('unavailable')
    // contributor unload removes exactly its section; page and peer remain
    await act(async () => alpha.dispose())
    expect([...page()!.querySelectorAll('[data-section-id]')].map(n => n.getAttribute('data-section-id'))).toEqual(['zeta'])
    expect(page()!.textContent).not.toContain('alpha controls')
    expect(page()!.textContent).toContain('zeta controls')
    await click(container, '关闭设置')
    expect(page()).toBeNull()
    await act(async () => { alpha.dispose(); zeta.dispose() })
  })

  it('activates modules to home plus sidebar selection and switches both ways', async () => {
    const lifetime = new OwnedResources(), chatScope = new OwnedResources(), workflowScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', chatScope, model)
    moduleBundle('workflow', 'Workflow', workflowScope, model)
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await click(container, 'Chat')
    expect(model.getSelection()).toEqual({ main: 'chat.main', left: 'chat.side' })
    expect(container.querySelector('[data-module-nav="chat"]')?.getAttribute('aria-pressed')).toBe('true')
    expect(container.querySelector('[data-module-nav="workflow"]')?.getAttribute('aria-pressed')).toBe('false')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('chat main content')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('chat sidebar content')
    await click(container, 'Workflow')
    expect(model.getSelection()).toEqual({ main: 'workflow.main', left: 'workflow.side' })
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('workflow main content')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('workflow sidebar content')
    await click(container, 'Chat')
    expect(model.getSelection()).toEqual({ main: 'chat.main', left: 'chat.side' })
    await act(async () => { chatScope.dispose(); workflowScope.dispose() })
  })

  it('counterexample: activating a sidebar-less module clears the module sidebar yet keeps user-opened views', async () => {
    const lifetime = new OwnedResources(), chatScope = new OwnedResources(), bareScope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', chatScope, model)
    model.service.forScope(bareScope).addView({ id: 'bare.main', title: 'Bare主区', presentation: 'region', region: 'main', component: () => <p>bare main content</p> })
    model.composition.forScope(bareScope).addModule({ id: 'bare', title: 'Bare', homeViewId: 'bare.main' })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await act(async () => model.composition.activateModule('chat'))
    expect(model.getSelection()).toEqual({ main: 'chat.main', left: 'chat.side' })
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('chat sidebar content')
    // a module without a sidebarViewId must not inherit another module's sidebar
    await act(async () => model.composition.activateModule('bare'))
    expect(model.getSelection().left).toBeUndefined()
    expect(container.querySelector('[data-region="left"]')?.textContent).not.toContain('chat sidebar content')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('bare main content')
    // switching back restores the module pair
    await act(async () => model.composition.activateModule('chat'))
    expect(model.getSelection().left).toBe('chat.side')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('chat sidebar content')
    // a user-opened non-module view is not a module sidebar: it survives bare activation
    await act(async () => model.service.forScope(bareScope).addView({ id: 'user.left', title: '用户面板', presentation: 'region', region: 'left', component: () => <p>user panel content</p> }))
    await act(async () => model.service.open('user.left'))
    await act(async () => model.composition.activateModule('bare'))
    expect(model.getSelection().left).toBe('user.left')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('user panel content')
    await act(async () => { chatScope.dispose(); bareScope.dispose() })
  })

  it('counterexample: narrow window keeps navigation usable; single view shows no empty tab strip', async () => {
    const originalWidth = window.innerWidth, originalHeight = window.innerHeight
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 360 })
    Object.defineProperty(window, 'innerHeight', { configurable: true, value: 640 })
    cleanup.push(async () => {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: originalWidth })
      Object.defineProperty(window, 'innerHeight', { configurable: true, value: originalHeight })
    })
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', scope, model)
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // navigation block exists, is vertical, its buttons are present and operable
    const nav = container.querySelector('.wb-nav')
    expect(nav).not.toBeNull()
    const navButtons = [...nav!.querySelectorAll('[data-module-nav]')]
    expect(navButtons.map(b => b.getAttribute('aria-label'))).toContain('Chat')
    await click(container, 'Chat')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('chat main content')
    // a single main view needs no visible tab strip — content and move/close controls stay
    const mainTabs = [...container.querySelectorAll('[data-region="main"] [role="group"] button')]
    expect(mainTabs).toHaveLength(0)
    expect(container.querySelector('[data-region="main"] .wb-region-label')).toBeNull()
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('chat main content')
    expect(container.querySelector('select[aria-label="移动 Chat主区 到"]')).not.toBeNull()
    expect(container.querySelector('button[aria-label="关闭Chat主区"]')).not.toBeNull()
    await act(async () => scope.dispose())
  })

  it('counterexample: unregistered regions keep no tab strip — the region label takes their place', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    moduleBundle('chat', 'Chat', scope, model)
    await act(async () => model.composition.activateModule('chat'))
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // absence where it does not: right/bottom/top have zero tabs and show their label instead
    // main and left each hold exactly one view here — a single view renders no tab strip either
    expect(container.querySelectorAll('[data-region="main"] [role="group"] button')).toHaveLength(0)
    expect(container.querySelectorAll('[data-region="left"] [role="group"] button')).toHaveLength(0)
    for (const [region, label] of [['right', '右侧栏'], ['bottom', '底部面板'], ['top', '顶部面板']] as const) {
      expect(container.querySelectorAll(`[data-region="${region}"] [role="group"] button`)).toHaveLength(0)
      expect(container.querySelector(`[data-region="${region}"] .wb-region-label`)?.textContent).toBe(label)
    }
    await act(async () => scope.dispose())
  })

  it('a second view in a region brings the tab strip back: pressed states and switching work', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const api = model.service.forScope(scope)
    api.addView({ id: 'first.main', title: 'First主区', presentation: 'region', region: 'main', component: () => <p>first content</p> })
    api.addView({ id: 'second.main', title: 'Second主区', presentation: 'region', region: 'main', component: () => <p>second content</p> })
    await act(async () => model.service.open('first.main'))
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const tabs = () => [...container.querySelectorAll('[data-region="main"] [role="group"] button')]
    expect(tabs()).toHaveLength(2)
    expect(tabs()[0].getAttribute('aria-pressed')).toBe('true')
    expect(tabs()[1].getAttribute('aria-pressed')).toBe('false')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('first content')
    await click(container, 'Second主区')
    expect(tabs()[0].getAttribute('aria-pressed')).toBe('false')
    expect(tabs()[1].getAttribute('aria-pressed')).toBe('true')
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('second content')
    await act(async () => scope.dispose())
  })

  it('v1 UI contributions keep working next to module navigation', async () => {
    const lifetime = new OwnedResources(), scope = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    commands.forScope(lifetime).add({ id: 'open.full', title: '打开全页', execute: () => model.service.open('full') })
    model.service.forScope(lifetime).addView({ id: 'full', title: 'Full', presentation: 'full-page', component: () => <p>full content</p> })
    model.service.forScope(scope).addUI({ id: 'nav.full', kind: 'command', slot: 'navigation', command: 'open.full' })
    moduleBundle('chat', 'Chat', scope, model)
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // both coexist in the same navigation block
    expect(container.querySelector('[data-module-nav="chat"]')).not.toBeNull()
    const navButton = await click(container, '打开全页')
    expect(navButton.getAttribute('aria-label')).toBe('打开全页')
    expect(container.querySelector('[data-testid="full-page"]')).not.toBeNull()
    await click(container, '← 返回工作区')
    expect(container.querySelector('[data-testid="full-page"]')).toBeNull()
    await act(async () => scope.dispose())
  })
})
