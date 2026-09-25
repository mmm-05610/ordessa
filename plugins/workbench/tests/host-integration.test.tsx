// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { runtime } from '@ordessa/extension-host'
import { WorkbenchToken, type Workbench, type WorkbenchComposition } from '@extensions/ordessa.contracts/contract.js'
import commandsPlugin from '../../commands/src/entry'
import workbenchPlugin from '../src/entry'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
// jsdom has no layout/ResizeObserver. Geometry is verified separately in Electron.
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

describe('workbench plugin through the extension host', () => {
  it('exposes composition on the v1 Workbench service and runs addModule → addView → activateModule end to end', async () => {
    let composition: WorkbenchComposition | undefined
    const app = runtime([commandsPlugin(), workbenchPlugin(), {
      id: 'consumer.chat', requires: [WorkbenchToken],
      activate(ctx, wb: Workbench) {
        // A composition consumer rejects absence explicitly instead of falling back.
        if (!wb.composition) throw Error('Workbench composition capability is absent')
        composition = wb.composition
        const views = wb.forScope(ctx.resources)
        views.addView({ id: 'chat.main', title: 'Chat', presentation: 'region', region: 'main', component: () => <p>chat main via host</p> })
        views.addView({ id: 'chat.side', title: 'Chats', presentation: 'region', region: 'left', component: () => <p>chat sidebar via host</p> })
        composition.forScope(ctx.resources).addModule({ id: 'chat', title: 'Chat', homeViewId: 'chat.main', sidebarViewId: 'chat.side' })
        composition.activateModule('chat')
      },
    }])
    await app.activate('ordessa.workbench')
    await app.activate('consumer.chat')
    expect(app.getSnapshot().find(s => s.id === 'consumer.chat')?.phase).toBe('active')
    expect(composition).toBeDefined()
    // The plugin's mounted root is the real Workbench shell over the real model.
    const Root = app.host.roots.getSnapshot()[0].component
    const container = document.createElement('div'); document.body.append(container)
    const root = createRoot(container)
    cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
    await act(async () => root.render(<Root />))
    // full chain visible: navigation entry derived from the descriptor, home and sidebar selected
    expect(container.querySelector('[data-module-nav="chat"]')).not.toBeNull()
    expect(container.querySelector('[data-region="main"]')?.textContent).toContain('chat main via host')
    expect(container.querySelector('[data-region="left"]')?.textContent).toContain('chat sidebar via host')
    // consumer deactivation erases its contribution; the workbench keeps running
    await act(async () => app.deactivate('consumer.chat'))
    await act(async () => {})
    expect(container.querySelector('[data-module-nav="chat"]')).toBeNull()
    expect(container.textContent).not.toContain('chat main via host')
    expect(container.textContent).not.toContain('chat sidebar via host')
    await act(async () => app.deactivate('ordessa.workbench'))
    expect(app.host.roots.getSnapshot()).toEqual([])
  })

  it('a composition consumer rejects a v1-only Workbench (absent capability) instead of falling back', async () => {
    const legacyOnly = {
      id: 'legacy.workbench', provides: WorkbenchToken,
      activate: () => ({
        forScope: () => ({ addView: () => ({ dispose() {}, isDisposed: true }), addUI: () => ({ dispose() {}, isDisposed: true }) }),
        open() {}, close() {},
      }),
    }
    const app = runtime([commandsPlugin(), legacyOnly, {
      id: 'consumer.strict', requires: [WorkbenchToken],
      activate(_ctx, wb: Workbench) {
        if (!wb.composition) throw Error('composition required')
      },
    }])
    await expect(app.activate('consumer.strict')).rejects.toThrow('composition required')
    expect(app.getSnapshot().find(s => s.id === 'consumer.strict')?.phase).toBe('failed')
  })
})
