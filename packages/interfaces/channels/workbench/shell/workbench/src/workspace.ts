import { createElement } from 'react'
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type { View, Region, WorkspaceCapability, WorkspaceDefinition, PageInstance, PageOpenOptions, WorkspaceSnapshot } from '../api/workbench'
import { registry } from '../shared/registry'

interface ViewRegistry {
  getSnapshot(): readonly View[]
  subscribe(listener: () => void): () => void
  add(scope: ResourceScope, view: View): IDisposable
}
interface PageRecord {
  readonly page: PageInstance
  readonly definition: View
  readonly workspace: WorkspaceDefinition
  readonly viewId: string
  readonly options?: PageOpenOptions
  handle?: IDisposable
  active: boolean
}

/** UI identity/selection only. Domain values and operations stay in consumers. */
export function createWorkspaceCapability(lifetime: ResourceScope, views: ViewRegistry, actions: {
  open(id: string): void
  close(id: string): void
  activateDefinition(definition: WorkspaceDefinition): void
}): WorkspaceCapability {
  const workspaces = registry<WorkspaceDefinition>(lifetime)
  const pages = new Map<string, PageRecord>()
  const listeners = new Set<() => void>()
  let activeWorkspaceId: string | undefined, activePageId: string | undefined
  let snapshot: WorkspaceSnapshot
  const publish = () => {
    snapshot = Object.freeze({ workspaces: workspaces.getSnapshot(), pages: Object.freeze([...pages.values()].map(record => record.page)), activeWorkspaceId, activePageId })
    for (const listener of [...listeners]) listener()
  }
  publish()
  const alive = () => { if (lifetime.isDisposed) throw Error('Workbench is closed') }
  const currentWorkspace = (id: string) => workspaces.getSnapshot().find(item => item.id === id)
  const currentView = (id: string) => views.getSnapshot().find(item => item.id === id)
  const retire = (record: PageRecord) => {
    if (!record.active) return
    record.active = false
    if (pages.get(record.page.instanceId) === record) pages.delete(record.page.instanceId)
    if (activePageId === record.page.instanceId) activePageId = undefined
    record.handle?.dispose()
    actions.close(record.viewId)
    publish()
  }
  const reconcile = () => {
    for (const record of [...pages.values()]) {
      if (currentView(record.definition.id) !== record.definition || currentWorkspace(record.workspace.id) !== record.workspace || (record.handle && !currentView(record.viewId))) retire(record)
    }
    if (activeWorkspaceId && !currentWorkspace(activeWorkspaceId)) activeWorkspaceId = undefined
    publish()
  }
  const unsubscribeViews = views.subscribe(reconcile), unsubscribeWorkspaces = workspaces.subscribe(reconcile)
  lifetime.add({ isDisposed: false, dispose() { unsubscribeViews(); unsubscribeWorkspaces(); listeners.clear() } })
  const activatePage = (id: string) => {
    alive()
    const record = pages.get(id)
    if (!record?.active) throw Error(`Page unavailable: ${id}`)
    activeWorkspaceId = record.page.workspaceId
    activePageId = id
    actions.open(record.viewId)
    publish()
  }
  return {
    forScope(scope) {
      return {
        addWorkspace(definition) {
          alive()
          if (!definition.homeViewId.trim()) throw Error('Workspace home view is required')
          return workspaces.add(scope, definition)
        },
        openPage(instance, options) {
          alive()
          if (scope.isDisposed) throw Error('Registration scope is closed')
          if (!instance.instanceId.trim() || pages.has(instance.instanceId)) throw Error(`Duplicate or empty page instance: ${instance.instanceId}`)
          const definition = currentView(instance.viewId), workspace = currentWorkspace(instance.workspaceId)
          if (!definition || !workspace) throw Error('Page definition or workspace unavailable')
          if (!['left', 'right', 'bottom', 'main', 'top'].includes(instance.region)) throw Error('Invalid page region')
          if (definition.workspaceId && definition.workspaceId !== workspace.id) throw Error('Page belongs to another workspace')
          const targetRef = instance.targetRef === undefined ? undefined : Object.freeze({ ...instance.targetRef })
          if (targetRef && (!targetRef.ownerId.trim() || !targetRef.targetId.trim() || !Number.isSafeInteger(targetRef.generation) || targetRef.generation < 0)) throw Error('Invalid page target reference')
          const page = Object.freeze({ instanceId: instance.instanceId, viewId: instance.viewId, workspaceId: instance.workspaceId, region: instance.region, ...(targetRef ? { targetRef } : {}) })
          const viewId = `ui.page:${instance.instanceId}`
          const record: PageRecord = { page, definition, workspace, viewId, options, active: true }
          const Content = definition.component
          record.handle = views.add(scope, { id: viewId, title: definition.title, order: definition.order, presentation: 'region', region: instance.region as Region, workspaceId: workspace.id, component: () => createElement(Content, { instance: page }) })
          pages.set(instance.instanceId, record)
          const handle = scope.add({ get isDisposed() { return !record.active }, dispose() { retire(record) } })
          publish()
          return handle
        },
      }
    },
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    activateWorkspace(id) {
      alive()
      const definition = currentWorkspace(id)
      if (!definition) throw Error(`Workspace unavailable: ${id}`)
      actions.activateDefinition(definition)
      activeWorkspaceId = id
      activePageId = undefined
      publish()
    },
    activatePage,
    async closePage(id) {
      alive()
      const record = pages.get(id)
      if (!record?.active) return false
      if (record.options?.beforeClose && !await record.options.beforeClose()) return false
      if (!record.active || pages.get(id) !== record) return false
      retire(record)
      return true
    },
    captureWorkspace(id) {
      const definition = currentWorkspace(id)
      return Object.freeze({ execute() {
        alive()
        if (!definition || currentWorkspace(id) !== definition) throw Error('Workspace target is stale')
        actions.activateDefinition(definition)
        activeWorkspaceId = id; activePageId = undefined; publish()
      } })
    },
    captureView(id) {
      const definition = currentView(id)
      return Object.freeze({ execute() {
        alive()
        if (!definition || currentView(id) !== definition) throw Error('View target is stale')
        actions.open(id)
      } })
    },
    capturePage(id) {
      const record = pages.get(id)
      return Object.freeze({ execute() {
        alive()
        if (!record || !record.active || pages.get(id) !== record) throw Error('Page target is stale')
        activatePage(id)
      } })
    },
  }
}
