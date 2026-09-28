// @vitest-environment jsdom
// T020: independent contributor unload through the real extension host.
// Disposing contributor A's scope must remove ALL of A's views, tab entries,
// navigation and toolbar/statusbar UI, while contributor B's live handles,
// subscriptions, React state and open/selected views are completely
// unaffected — and A's late writes after close can never resurrect UI.
import { act, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { runtime } from '@ordessa/extension-host'
import type { PluginContext } from '@ordessa/extension-api'
import { CommandsToken, WorkbenchToken, type Commands, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import commandsPlugin from '../../../plugins/commands/src/entry'
import workbenchPlugin from '../src/entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
// jsdom has no layout/ResizeObserver. Geometry is verified separately in Electron.
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

const region = (container: HTMLElement, name: string) => container.querySelector(`[data-region="${name}"]`)
const tabs = (container: HTMLElement, name: string) => [...container.querySelectorAll(`[data-region="${name}"] [role="group"] button`)].map(b => b.textContent)
type Consumer = { id: string; requires: unknown[]; activate(ctx: PluginContext, ...services: unknown[]): void }

describe('independent contributor unload through the extension host', () => {
  it('unloading contributor A erases A everywhere while B keeps its handle, subscription, state and open views intact', async () => {
    // Captured from each consumer's activation: post-deactivate probes below.
    let aApi!: ReturnType<Workbench['forScope']>
    let aWorkbench!: Workbench
    let aCommands!: Commands
    const bEvents: string[] = []
    let bMounts = 0

    const contributorA: Consumer = {
      id: 'contributor.a', requires: [WorkbenchToken, CommandsToken],
      activate(ctx: PluginContext, wb: Workbench, commands: Commands) {
        aWorkbench = wb; aCommands = commands
        aApi = wb.forScope(ctx.resources)
        aApi.addView({ id: 'a.1', title: 'A视图一', presentation: 'region', region: 'main', component: () => <p>a1 content</p> })
        aApi.addView({ id: 'a.2', title: 'A视图二', presentation: 'region', region: 'main', component: () => <p>a2 content</p> })
        aApi.addView({ id: 'a.side', title: 'A侧栏', presentation: 'region', region: 'left', component: () => <p>a sidebar content</p> })
        commands.forScope(ctx.resources).add({ id: 'a.tool', title: 'A工具栏', execute: () => 'ran-a' })
        aApi.addUI({ id: 'a.toolbar', kind: 'command', slot: 'toolbar', command: 'a.tool' })
        aApi.addUI({ id: 'a.status', kind: 'component', slot: 'statusbar', component: () => <span>A 状态栏</span> })
        wb.open('a.2')
      },
    }
    const contributorB: Consumer = {
      id: 'contributor.b', requires: [WorkbenchToken, CommandsToken],
      activate(ctx: PluginContext, wb: Workbench, commands: Commands) {
        const api = wb.forScope(ctx.resources)
        // A stateful component: mount count + internal counter prove the very
        // same React instance survives A's unload (useEffect counts mounts,
        // not re-renders).
        const Counter = () => {
          const [count, setCount] = useState(0)
          useEffect(() => { bMounts += 1 }, [])
          return <button onClick={() => setCount(c => c + 1)}>B计数 {count}</button>
        }
        api.addView({ id: 'b.1', title: 'B视图一', presentation: 'region', region: 'main', component: Counter })
        api.addView({ id: 'b.2', title: 'B视图二', presentation: 'region', region: 'main', component: () => <p>b2 content</p> })
        api.addView({ id: 'b.side', title: 'B侧栏', presentation: 'region', region: 'left', component: () => <p>b sidebar content</p> })
        commands.forScope(ctx.resources).add({ id: 'b.tool', title: 'B工具栏', execute: () => 'ran-b' })
        api.addUI({ id: 'b.toolbar', kind: 'command', slot: 'toolbar', command: 'b.tool' })
        api.addUI({ id: 'b.status', kind: 'component', slot: 'statusbar', component: () => <span>B 状态栏</span> })
        // B keeps a live subscription on a shared service across A's unload.
        const unsubscribeCommands = commands.subscribe(() => bEvents.push('commands-change'))
        cleanup.push(async () => unsubscribeCommands())
        wb.open('b.1')
        wb.open('b.side')
      },
    }

    const App = runtime([commandsPlugin(), workbenchPlugin(), contributorA, contributorB])

    await App.activate('ordessa.workbench')
    await App.activate('contributor.a')
    await App.activate('contributor.b')

    const Root = App.host.roots.getSnapshot()[0].component
    const container = document.createElement('div'); document.body.append(container)
    const root = createRoot(container)
    cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
    await act(async () => root.render(<Root />))

    // ---- snapshot BEFORE A unloads ----
    // four main views coexist in one tab strip; B's view holds the selection
    expect(tabs(container, 'main')).toEqual(['A视图一', 'A视图二', 'B视图一', 'B视图二'])
    expect(region(container, 'main')?.textContent).toContain('B计数 0')
    expect(container.textContent).not.toContain('a2 content')
    // A's and B's side views share a two-tab strip; B's side view is selected
    expect(tabs(container, 'left')).toEqual(['A侧栏', 'B侧栏'])
    expect(region(container, 'left')?.textContent).toContain('b sidebar content')
    // toolbar and statusbar slots show both contributors' UI
    const aToolBefore = container.querySelector<HTMLButtonElement>('button[aria-label="A工具栏"]')
    const bToolBefore = container.querySelector<HTMLButtonElement>('button[aria-label="B工具栏"]')
    expect(aToolBefore).not.toBeNull()
    expect(bToolBefore).not.toBeNull()
    expect(container.querySelector('.wb-status')?.textContent).toContain('A 状态栏')
    expect(container.querySelector('.wb-status')?.textContent).toContain('B 状态栏')
    // B's live React state: one click before the unload
    const bButtonBefore = [...container.querySelectorAll('button')].find(b => b.textContent === 'B计数 0')
    expect(bButtonBefore, 'B counter rendered').toBeTruthy()
    await act(async () => { bButtonBefore!.click() })
    expect(bButtonBefore!.textContent).toBe('B计数 1')
    const mountsBeforeUnload = bMounts
    const eventsBeforeUnload = bEvents.length

    // ---- unload contributor A through the host ----
    await act(async () => { await App.deactivate('contributor.a') })

    // A is gone from every surface: tabs, content, toolbar, statusbar
    expect(container.textContent).not.toContain('a1 content')
    expect(container.textContent).not.toContain('a sidebar content')
    expect(container.querySelector('button[aria-label="A工具栏"]')).toBeNull()
    expect(container.querySelector('.wb-status')?.textContent).not.toContain('A 状态栏')
    // main tab strip collapsed 4→2 with B's views intact, and B stays open/selected
    expect(tabs(container, 'main')).toEqual(['B视图一', 'B视图二'])
    expect(region(container, 'main')?.textContent).toContain('B计数 1')
    // the left strip collapsed 2→1: no tab strip, B's remaining side view
    // renders bare, still active and open
    expect(container.querySelectorAll('[data-region="left"] [role="group"] button')).toHaveLength(0)
    expect(region(container, 'left')?.getAttribute('data-active-view')).toBe('B侧栏')
    expect(region(container, 'left')?.textContent).toContain('b sidebar content')
    // B's UI is untouched — same DOM instances, still operable
    expect(container.querySelector('button[aria-label="B工具栏"]')).toBe(bToolBefore)
    expect(container.querySelector('.wb-status')?.textContent).toContain('B 状态栏')
    // B's state is NOT reset and the component never remounted
    expect(bMounts).toBe(mountsBeforeUnload)
    const bButtonAfter = [...container.querySelectorAll('button')].find(b => b.textContent === 'B计数 1')
    expect(bButtonAfter).toBe(bButtonBefore)
    await act(async () => { bButtonAfter!.click() })
    expect(bButtonBefore!.textContent).toBe('B计数 2')
    // B's live subscription observed A's command removal and keeps working
    expect(bEvents.length).toBeGreaterThan(eventsBeforeUnload)
    // B's toolbar command still executes through the shared service
    await act(async () => { bToolBefore!.click() })
    expect(container.querySelector('[role="alert"]')).toBeNull()

    // ---- A's late writes and late opens cannot resurrect UI ----
    expect(() => aApi.addView({ id: 'a.late', title: 'A迟来视图', presentation: 'region', region: 'main', component: () => <p>late</p> })).toThrow(/closed/)
    expect(() => aApi.addUI({ id: 'a.late-ui', kind: 'component', slot: 'statusbar', component: () => <p>late</p> })).toThrow(/closed/)
    expect(() => aWorkbench.open('a.1')).toThrow('View unavailable')
    await expect(aCommands.execute('a.tool')).resolves.toMatchObject({ ok: false, error: 'Command unavailable: a.tool' })
    await act(async () => {})
    // the failed resurrection attempts changed nothing on screen
    expect(tabs(container, 'main')).toEqual(['B视图一', 'B视图二'])
    expect(container.textContent).not.toContain('A迟来视图')
    expect(container.querySelector('.wb-status')?.textContent).not.toContain('A 状态栏')

    // ---- counterexample pairing: B's own unload is just as clean ----
    await act(async () => { await App.deactivate('contributor.b') })
    expect(container.textContent).not.toContain('B计数')
    expect(container.querySelector('button[aria-label="B工具栏"]')).toBeNull()
    // the workbench itself keeps serving
    expect(App.getSnapshot().find(s => s.id === 'ordessa.workbench')?.phase).toBe('active')
  })
})
