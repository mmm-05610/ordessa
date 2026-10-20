import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../src/model'

const view = (id: string) => ({ id, title: id, presentation: 'region' as const, region: 'main' as const, instanceOnly: true, component: () => null })
describe('UI01 workspace/page identity mechanism', () => {
  it('opens two instances over one definition without copying the domain owner and rejects stale captures', async () => {
    const lifetime = new OwnedResources(), a = new OwnedResources(), b = new OwnedResources()
    const model = createWorkbench(lifetime), capability = model.service.workspace!
    model.service.forScope(a).addView(view('definition.a'))
    capability.forScope(a).addWorkspace({ id: 'workspace.a', title: 'A', homeViewId: 'definition.a' })
    capability.forScope(a).openPage({ instanceId: 'instance.one', viewId: 'definition.a', workspaceId: 'workspace.a', region: 'main', targetRef: { ownerId: 'owner.a', targetId: 'target.one', generation: 1 } })
    capability.forScope(a).openPage({ instanceId: 'instance.two', viewId: 'definition.a', workspaceId: 'workspace.a', region: 'right', targetRef: { ownerId: 'owner.a', targetId: 'target.one', generation: 1 } })
    expect(capability.getSnapshot().pages.map(page => page.instanceId)).toEqual(['instance.one', 'instance.two'])
    expect(capability.getSnapshot().pages.map(page => page.targetRef?.ownerId)).toEqual(['owner.a', 'owner.a'])
    const captured = capability.capturePage('instance.one')
    await expect(capability.closePage('instance.one')).resolves.toBe(true)
    capability.forScope(b).openPage({ instanceId: 'instance.one', viewId: 'definition.a', workspaceId: 'workspace.a', region: 'bottom' })
    expect(() => captured.execute()).toThrow(/stale/i)
    a.dispose()
    expect(capability.getSnapshot().pages).toEqual([])
    expect(capability.getSnapshot().workspaces).toEqual([])
    b.dispose(); lifetime.dispose()
  })

  it('late close permission never closes a new instance and denied dirty close keeps the original', async () => {
    const lifetime = new OwnedResources(), a = new OwnedResources()
    const model = createWorkbench(lifetime), capability = model.service.workspace!
    model.service.forScope(a).addView(view('definition'))
    capability.forScope(a).addWorkspace({ id: 'workspace', title: 'W', homeViewId: 'definition' })
    capability.forScope(a).openPage({ instanceId: 'dirty', viewId: 'definition', workspaceId: 'workspace', region: 'main' }, { beforeClose: () => false })
    await expect(capability.closePage('dirty')).resolves.toBe(false)
    expect(capability.getSnapshot().pages).toHaveLength(1)
    let allow!: (value: boolean) => void
    const old = capability.forScope(a).openPage({ instanceId: 'late', viewId: 'definition', workspaceId: 'workspace', region: 'right' }, { beforeClose: () => new Promise(resolve => { allow = resolve }) })
    const closing = capability.closePage('late')
    old.dispose()
    capability.forScope(a).openPage({ instanceId: 'late', viewId: 'definition', workspaceId: 'workspace', region: 'bottom' })
    allow(true)
    await expect(closing).resolves.toBe(false)
    expect(capability.getSnapshot().pages.find(page => page.instanceId === 'late')?.region).toBe('bottom')
    a.dispose(); lifetime.dispose()
  })

  it('old workspace and view captures cannot activate same-id replacements', () => {
    const lifetime = new OwnedResources(), a = new OwnedResources(), b = new OwnedResources()
    const model = createWorkbench(lifetime), capability = model.service.workspace!
    model.service.forScope(a).addView(view('same.definition'))
    capability.forScope(a).addWorkspace({ id: 'same.workspace', title: 'A', homeViewId: 'same.definition' })
    const workspace = capability.captureWorkspace('same.workspace'), definition = capability.captureView('same.definition')
    a.dispose()
    model.service.forScope(b).addView(view('same.definition'))
    capability.forScope(b).addWorkspace({ id: 'same.workspace', title: 'B', homeViewId: 'same.definition' })
    expect(() => workspace.execute()).toThrow(/stale/i)
    expect(() => definition.execute()).toThrow(/stale/i)
    expect(capability.getSnapshot().activeWorkspaceId).toBeUndefined()
    b.dispose(); lifetime.dispose()
  })
})
