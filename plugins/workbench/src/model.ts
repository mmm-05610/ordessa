import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type {
  Workbench, WorkbenchComposition, WorkbenchModule, WorkbenchOverlay, WorkbenchOverlayOpenOptions,
  WorkbenchSettingsSection, View, UIContribution, Region,
} from '@extensions/ordessa.contracts/contract.js'
import { registry } from '../shared/registry'

/** The settings page is Workbench-owned; it is not a contribution of any plugin. */
export const SETTINGS_OVERLAY_ID = 'ordessa.workbench.settings'

export type OverlayPresentation = 'popover' | 'dialog' | 'page'
export interface OverlayInstance {
  key: number
  overlayId: string
  anchor?: HTMLElement
  /** Settings page only: the section to locate. */
  sectionId?: string
}

export function createWorkbench(lifetime: ResourceScope) {
  const views = registry<View>(lifetime), ui = registry<UIContribution>(lifetime)
  const modules = registry<WorkbenchModule>(lifetime)
  const overlays = registry<WorkbenchOverlay>(lifetime)
  const sections = registry<WorkbenchSettingsSection>(lifetime)
  type Selection = Partial<Record<Region | 'full-page', string>>
  let selected: Selection = {}
  let layout: { placements: Record<string, Region>; collapsed: Partial<Record<Region, boolean>> } = { placements: {}, collapsed: {} }
  let overlayStack: readonly OverlayInstance[] = []
  let nextInstance = 1
  const regionOf = (view: View) => view.presentation === 'region' ? layout.placements[view.id] ?? view.region : undefined
  const listeners = new Set<() => void>()
  const publish = () => listeners.forEach(f => f())
  const unsubscribe = views.subscribe(() => {
    const ids = new Set(views.getSnapshot().map(v => v.id))
    selected = Object.fromEntries(Object.entries(selected).filter(([, id]) => ids.has(id!)))
    layout = { ...layout, placements: Object.fromEntries(Object.entries(layout.placements).filter(([id]) => ids.has(id))) }
    publish()
  })
  // Unregistered modules lose their navigation entry and any selection that
  // referenced their views; modules that remain keep their selection.
  let claimedViews = new Set<string>()
  const unsubscribeModules = modules.subscribe(() => {
    const next = new Set<string>()
    for (const m of modules.getSnapshot()) { next.add(m.homeViewId); if (m.sidebarViewId) next.add(m.sidebarViewId) }
    const dropped = [...claimedViews].filter(id => !next.has(id))
    claimedViews = next
    if (!dropped.length) return
    const gone = new Set(dropped)
    selected = Object.fromEntries(Object.entries(selected).filter(([, id]) => !gone.has(id)))
    publish()
  })
  // Unregistered overlays close immediately; the shell restores focus on unmount.
  const unsubscribeOverlays = overlays.subscribe(() => {
    const ids = new Set(overlays.getSnapshot().map(o => o.id))
    const kept = overlayStack.filter(i => i.overlayId === SETTINGS_OVERLAY_ID || ids.has(i.overlayId))
    if (kept.length === overlayStack.length) return
    overlayStack = kept
    publish()
  })
  lifetime.add({ isDisposed: false, dispose() { unsubscribe(); unsubscribeModules(); unsubscribeOverlays(); listeners.clear() } })
  const activateModule = (id: string) => {
    if (lifetime.isDisposed) throw Error('Workbench is closed')
    const module = modules.getSnapshot().find(m => m.id === id)
    if (!module) throw Error(`Module unavailable: ${id}`)
    // Both bindings are verified before any selection changes: an absent or
    // misplaced view is a visible error, never a fallback to another view.
    const snapshot = views.getSnapshot()
    const check = (viewId: string, region: Region, role: string): View => {
      const view = snapshot.find(v => v.id === viewId)
      if (!view) throw Error(`Module "${id}" ${role} view is not registered: ${viewId}`)
      if (view.presentation !== 'region' || regionOf(view) !== region) throw Error(`Module "${id}" ${role} view must be a ${region}-region view: ${viewId}`)
      return view
    }
    const home = check(module.homeViewId, 'main', 'home')
    const sidebar = module.sidebarViewId === undefined ? undefined : check(module.sidebarViewId, 'left', 'sidebar')
    selected = { ...selected, main: home.id, ...(sidebar ? { left: sidebar.id } : {}) }
    if (sidebar) layout = { ...layout, collapsed: { ...layout.collapsed, left: false } }
    publish()
  }
  const closeInstance = (key: number) => {
    if (!overlayStack.some(i => i.key === key)) return
    overlayStack = overlayStack.filter(i => i.key !== key)
    publish()
  }
  const openOverlay = (id: string, options?: WorkbenchOverlayOpenOptions): IDisposable => {
    if (lifetime.isDisposed) throw Error('Workbench is closed')
    const overlay = overlays.getSnapshot().find(o => o.id === id)
    if (!overlay) throw Error(`Overlay unavailable: ${id}`)
    if (overlay.presentation !== 'popover' && overlay.presentation !== 'dialog' && overlay.presentation !== 'page') throw Error(`Invalid overlay presentation: ${String(overlay.presentation)}`)
    const anchor = options?.anchor
    // A popover without a live anchor fails explicitly instead of silently not showing.
    if (overlay.presentation === 'popover' && (!anchor || !anchor.isConnected)) throw Error(`Popover requires a connected anchor: ${id}`)
    const key = nextInstance++
    overlayStack = [...overlayStack, { key, overlayId: id, anchor }]
    publish()
    let open = true
    return {
      get isDisposed() { return !open },
      dispose() { if (!open) return; open = false; closeInstance(key) },
    }
  }
  const openSettings = (sectionId?: string) => {
    if (lifetime.isDisposed) throw Error('Workbench is closed')
    if (sectionId !== undefined && !sections.getSnapshot().some(s => s.id === sectionId)) throw Error(`Settings section unavailable: ${sectionId}`)
    const existing = overlayStack.find(i => i.overlayId === SETTINGS_OVERLAY_ID)
    const entry: OverlayInstance = { key: existing?.key ?? nextInstance++, overlayId: SETTINGS_OVERLAY_ID, sectionId }
    overlayStack = [...overlayStack.filter(i => i !== existing), entry]
    publish()
  }
  const closeTopOverlay = () => {
    const top = overlayStack[overlayStack.length - 1]
    if (top) closeInstance(top.key)
  }
  const composition: WorkbenchComposition = {
    forScope: scope => ({
      addModule: module => modules.add(scope, module),
      addOverlay: overlay => overlays.add(scope, overlay),
      addSettingsSection: section => sections.add(scope, section),
    }),
    activateModule,
    openOverlay,
    openSettings,
  }
  const service: Workbench = {
    forScope: scope => ({
      addView: view => {
        if (view.presentation !== 'full-page' && (view.presentation !== 'region' || !['left', 'right', 'bottom', 'main', 'top'].includes(view.region))) throw Error('Invalid view placement')
        return views.add(scope, view)
      },
      addUI: item => {
        if (!['navigation', 'toolbar', 'statusbar'].includes(item.slot) || !['component', 'command'].includes(item.kind) || (item.kind === 'component' && item.slot !== 'statusbar')) throw Error('Invalid UI contribution')
        return ui.add(scope, item)
      },
    }),
    composition,
    open(id) {
      if (lifetime.isDisposed) throw Error('Workbench is closed')
      const view = views.getSnapshot().find(v => v.id === id)
      if (!view) throw Error(`View unavailable: ${id}`)
      const target = view.presentation === 'full-page' ? 'full-page' : regionOf(view)!
      selected = { ...selected, [target]: id }
      if (target !== 'full-page') layout = { ...layout, collapsed: { ...layout.collapsed, [target]: false } }
      publish()
    },
    close(id) { selected = Object.fromEntries(Object.entries(selected).filter(([, value]) => value !== id)); publish() },
  }
  return { service, views, ui, modules, overlays, sections, composition, regionOf, getSelection: () => selected,
    getOverlayStack: () => overlayStack, closeOverlayInstance: closeInstance, closeTopOverlay,
    getLayout: () => layout,
    collapse(region: Region, collapsed: boolean) {
      if (lifetime.isDisposed || region === 'main' || layout.collapsed[region] === collapsed) return
      layout = { ...layout, collapsed: { ...layout.collapsed, [region]: collapsed } }; publish()
    },
    move(id: string, region: Region) {
      if (lifetime.isDisposed) throw Error('Workbench is closed')
      const view = views.getSnapshot().find(v => v.id === id)
      if (!view || view.presentation !== 'region' || !['left', 'right', 'bottom', 'main', 'top'].includes(region)) throw Error('Invalid view move')
      const from = regionOf(view)!
      if (from === region) { service.open(id); return }
      selected = Object.fromEntries(Object.entries(selected).filter(([, value]) => value !== id))
      layout = { placements: { ...layout.placements, [id]: region }, collapsed: { ...layout.collapsed, [region]: false } }
      const replacement = views.getSnapshot().find(v => v.id !== id && regionOf(v) === from)
      if (!selected[from] && replacement) selected[from] = replacement.id
      selected = { ...selected, [region]: id }; publish()
    },
    resetLayout() {
      if (lifetime.isDisposed) return
      layout = { placements: {}, collapsed: {} }
      selected = Object.fromEntries(Object.entries(selected).filter(([key]) => key === 'full-page'))
      for (const view of views.getSnapshot()) if (view.presentation === 'region' && !selected[view.region]) selected[view.region] = view.id
      publish()
    },
    subscribe: (f: () => void) => { listeners.add(f); return () => { listeners.delete(f) } },
  }
}
export type WorkbenchModel = ReturnType<typeof createWorkbench>
