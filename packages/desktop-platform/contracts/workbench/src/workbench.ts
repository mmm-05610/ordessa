import { Token, type ResourceScope, type IDisposable } from '@ordessa/extension-api'
import type { ComponentType } from 'react'
export type Region = 'left' | 'right' | 'bottom' | 'main' | 'top'
interface ViewBase { id: string; title: string; order?: number; component: ComponentType }
export type View = ViewBase & ({ presentation: 'region'; region: Region } | { presentation: 'full-page' })

/** A product module owns its navigation entry and its default workspace views. */
export interface WorkbenchModule {
  id: string
  title: string
  order?: number
  icon?: ComponentType
  homeViewId: string
  sidebarViewId?: string
}

/** Overlay content is owned by its contributor; the Workbench owns dismissal. */
export interface WorkbenchOverlayContentProps { close(): void }
export type WorkbenchOverlay = { id: string; title: string; order?: number; component: ComponentType<WorkbenchOverlayContentProps> } & (
  { presentation: 'popover' } |
  { presentation: 'dialog' | 'page' }
)
export type WorkbenchOverlayOpenOptions = { anchor?: HTMLElement }

export interface WorkbenchSettingsSection {
  id: string
  title: string
  order?: number
  component: ComponentType
}

/**
 * Versioned composition capability. Its presence means the whole registration
 * surface is implemented; consumers must reject absence rather than silently
 * substituting legacy navigation or view IDs. Registrations are scope-owned.
 */
export interface WorkbenchComposition {
  forScope(scope: ResourceScope): {
    addModule(module: WorkbenchModule): IDisposable
    addOverlay(overlay: WorkbenchOverlay): IDisposable
    addSettingsSection(section: WorkbenchSettingsSection): IDisposable
  }
  activateModule(id: string): void
  openOverlay(id: string, options?: WorkbenchOverlayOpenOptions): IDisposable
  openSettings(sectionId?: string): void
}

export type UIContribution = { id: string; order?: number } & (
  { kind: 'command'; slot: 'navigation' | 'toolbar' | 'statusbar'; command: string; label?: string; section?: 'primary' | 'utility'; icon?: ComponentType } |
  { kind: 'component'; slot: 'statusbar'; component: ComponentType }
)
export interface Workbench {
  forScope(scope: ResourceScope): { addView(view: View): IDisposable; addUI(item: UIContribution): IDisposable }
  open(id: string): void
  close(id: string): void
  /** Absent in the baseline Workbench; required by modules using composition. */
  readonly composition?: WorkbenchComposition
}
export const WorkbenchToken = new Token<Workbench>('ordessa.workbench.v1')
