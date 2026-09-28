// @vitest-environment jsdom
import { act, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { runtime } from '@ordessa/extension-host'
import type { Commands, Workbench, Region } from '@extensions/ordessa.contracts/contract.js'
import { CommandsToken, WorkbenchToken } from '@extensions/ordessa.contracts/contract.js'
import commandsPlugin, { createCommands } from '../../../plugins/commands/src/entry'
import workbenchPlugin from '../../../packages/workbench/src/entry'
import { createWorkbench } from '../../../packages/workbench/src/model'
import { WorkbenchShell } from '../../../packages/workbench/src/shell'

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
describe('foundation service boundaries', () => {
  it('rejects duplicate views and refuses late writes', () => {
    const scope = new OwnedResources(), owner = new OwnedResources(), wb = createWorkbench(scope)
    const view = { id: 'v', title: 'V', presentation: 'full-page' as const, component: () => null }
    wb.service.forScope(owner).addView(view)
    expect(() => wb.service.forScope(scope).addView(view)).toThrow('Duplicate')
    owner.dispose()
    expect(() => wb.service.forScope(owner).addView(view)).toThrow('closed')
    expect(() => wb.service.forScope(owner).addUI({ id: 'u', kind: 'command', slot: 'toolbar', command: 'missing' })).toThrow('closed')
    scope.dispose()
  })
  it('owns registrations across services; rejects duplicates and late additions', async () => {
    const lifetime = new OwnedResources(), a = new OwnedResources(), b = new OwnedResources()
    const commands = createCommands(lifetime), wb = createWorkbench(lifetime)
    commands.forScope(a).add({ id: 'a', title: 'A', execute: () => 7 })
    commands.forScope(b).add({ id: 'b', title: 'B', execute: () => { throw Error('explicit failure') } })
    expect(() => commands.forScope(b).add({ id: 'a', title: 'duplicate', execute() {} })).toThrow('Duplicate')
    expect(await commands.execute('a')).toEqual({ ok: true, value: 7 })
    expect(await commands.execute('b')).toMatchObject({ ok: false, error: expect.stringContaining('explicit failure') })
    wb.service.forScope(a).addView({ id: 'a', title: 'A', presentation: 'full-page', component: () => null })
    wb.service.forScope(a).addUI({ id: 'a', kind: 'command', slot: 'toolbar', command: 'a' })
    wb.service.open('a')
    a.dispose()
    expect(commands.getSnapshot().map(c => c.id)).toEqual(['b'])
    expect(await commands.execute('a')).toMatchObject({ ok: false })
    expect(wb.views.getSnapshot()).toEqual([]); expect(wb.ui.getSnapshot()).toEqual([]); expect(wb.getSelection()).toEqual({})
    expect(() => commands.forScope(a).add({ id: 'late', title: 'late', execute() {} })).toThrow('closed')
    lifetime.dispose()
    expect(() => commands.forScope(b).add({ id: 'later', title: 'later', execute() {} })).toThrow('closed')
    b.dispose()
  })
  it('rolls back a consumer across foundation registries on activation failure', async () => {
    let commands!: Commands, wb!: Workbench
    const app = runtime([commandsPlugin(), workbenchPlugin(), {
      id: 'bad', requires: [CommandsToken, WorkbenchToken],
      activate(ctx, c: Commands, w: Workbench) {
        commands = c; wb = w
        c.forScope(ctx.resources).add({ id: 'bad', title: 'bad', execute() {} })
        w.forScope(ctx.resources).addView({ id: 'bad', title: 'bad', presentation: 'full-page', component: () => null })
        throw Error('broken consumer')
      },
    }])
    await expect(app.activate('bad')).rejects.toThrow('broken consumer')
    expect(await commands.execute('bad')).toMatchObject({ ok: false })
    expect(() => wb.open('bad')).toThrow('unavailable')
    await app.deactivate('ordessa.workbench')
    expect(app.host.roots.getSnapshot()).toEqual([])
  })
})

describe('workbench UI', () => {
  it('moves an active component without remounting, and collapse is not close', async () => {
    const owner = new OwnedResources(), model = createWorkbench(owner), commands = createCommands(owner)
    function Counter() { const [n, set] = useState(0); return <button onClick={() => set(n + 1)}>move count {n}</button> }
    const view = { id: 'counter', title: 'Counter', presentation: 'region' as const, region: 'main' as const, component: Counter }
    const handle = model.service.forScope(owner).addView(view)
    model.service.open('counter')
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    await click(container, 'move count 0')
    await act(async () => model.move('counter', 'right'))
    expect(container.querySelector('[data-region=right]')?.textContent).toContain('move count 1')
    expect(container.querySelector('[data-region=main]')?.textContent).not.toContain('move count')
    await act(async () => model.collapse('right', true))
    expect(model.getSelection().right).toBe('counter')
    await act(async () => model.collapse('right', false))
    expect(container.querySelector('[data-region=right]')?.textContent).toContain('move count 1')
    await act(async () => model.resetLayout())
    expect(container.querySelector('[data-region=main]')?.textContent).toContain('move count 1')
    await act(async () => { handle.dispose(); model.service.forScope(owner).addView(view) })
    expect(model.regionOf(view)).toBe('main')
    expect(() => model.move('unknown', 'left')).toThrow('Invalid')
  })
  it('covers all five regions, preserves background state/focus across full-page, cleans removed pages', async () => {
    const lifetime = new OwnedResources(), fullOwner = new OwnedResources()
    const commands = createCommands(lifetime), model = createWorkbench(lifetime)
    function Counter() { const [n, set] = useState(0); return <button onClick={() => set(n + 1)}>count {n}</button> }
    for (const region of ['left', 'right', 'bottom', 'main', 'top'] as Region[]) {
      model.service.forScope(lifetime).addView({ id: region, title: region, presentation: 'region', region, component: region === 'main' ? Counter : () => <p>{region} content</p> })
      model.service.open(region)
    }
    model.service.forScope(fullOwner).addView({ id: 'full', title: 'Full', presentation: 'full-page', component: () => <p>Full content</p> })
    commands.forScope(lifetime).add({ id: 'open', title: 'Open full', execute: () => model.service.open('full') })
    model.service.forScope(lifetime).addUI({ id: 'open', kind: 'command', slot: 'navigation', command: 'open' })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    expect(container.querySelectorAll('[data-region]')).toHaveLength(5)
    await click(container, 'count 0')
    const entry = await click(container, 'Open full')
    expect(container.querySelector('[data-testid=workspace]')?.hasAttribute('inert')).toBe(true)
    expect(document.activeElement?.textContent).toBe('← 返回工作区')
    await click(container, '← 返回工作区')
    expect(container.textContent).toContain('count 1')
    expect(document.activeElement).toBe(entry)
    await click(container, 'Open full')
    await act(async () => fullOwner.dispose())
    expect(container.querySelector('[data-testid=full-page]')).toBeNull()
    expect(container.textContent).toContain('count 1')
  })
  it('isolates broken full-page rendering and missing commands; order is deterministic', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const scope = new OwnedResources(), commands = createCommands(scope), model = createWorkbench(scope)
    model.service.forScope(scope).addView({ id: 'bad', title: 'Bad', presentation: 'full-page', component: () => { throw Error('render') } })
    model.service.forScope(scope).addUI({ id: 'b', order: 2, kind: 'command', slot: 'toolbar', command: 'missing' })
    model.service.forScope(scope).addUI({ id: 'a', order: 1, kind: 'command', slot: 'toolbar', command: 'also-missing' })
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    expect([...container.querySelectorAll('.wb-actions button')].map(b => b.textContent)).toEqual(['also-missing（不可用）', 'missing（不可用）'])
    expect(container.querySelectorAll('.wb-actions button:disabled')).toHaveLength(2)
    await act(async () => model.service.open('bad'))
    expect(container.querySelector('[role=alert]')).not.toBeNull()
    await click(container, '← 返回工作区')
    expect(container.querySelector('[data-testid=full-page]')).toBeNull()
  })
})
