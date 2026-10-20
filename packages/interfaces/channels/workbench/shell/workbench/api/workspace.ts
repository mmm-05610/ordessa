import type { IDisposable, ResourceScope } from '@ordessa/extension-api'

/** UI identity only; these contracts never carry domain values or authority. */
export type WorkspaceRegion = 'left' | 'right' | 'bottom' | 'main' | 'top'
export interface WorkspaceDefinition {
  readonly id: string
  readonly title: string
  readonly order?: number
  readonly homeViewId: string
  readonly sidebarViewId?: string
}
export interface PageTargetReference {
  readonly ownerId: string
  readonly targetId: string
  readonly generation: number
}
export interface PageInstance {
  readonly instanceId: string
  readonly viewId: string
  readonly workspaceId: string
  readonly region: WorkspaceRegion
  readonly targetRef?: PageTargetReference
}
export interface PageOpenOptions {
  /** The original edit owner decides; false keeps the view open. */
  readonly beforeClose?: () => boolean | Promise<boolean>
}
export interface CapturedWorkbenchAction { execute(): void }
export interface WorkspaceSnapshot {
  readonly workspaces: readonly WorkspaceDefinition[]
  readonly pages: readonly PageInstance[]
  readonly activeWorkspaceId?: string
  readonly activePageId?: string
}
export interface WorkspaceCapability {
  forScope(scope: ResourceScope): {
    addWorkspace(definition: WorkspaceDefinition): IDisposable
    openPage(instance: PageInstance, options?: PageOpenOptions): IDisposable
  }
  getSnapshot(): WorkspaceSnapshot
  subscribe(listener: () => void): () => void
  activateWorkspace(id: string): void
  activatePage(instanceId: string): void
  closePage(instanceId: string): Promise<boolean>
  captureWorkspace(id: string): CapturedWorkbenchAction
  captureView(id: string): CapturedWorkbenchAction
  capturePage(instanceId: string): CapturedWorkbenchAction
}
export interface WorkbenchLayoutV1 {
  readonly schemaVersion: 1
  readonly placements: Readonly<Record<string, WorkspaceRegion>>
  readonly collapsed: Readonly<Partial<Record<WorkspaceRegion, boolean>>>
  readonly activeViewIds: Readonly<Partial<Record<WorkspaceRegion, string>>>
  readonly panelSizes: Readonly<Partial<Record<WorkspaceRegion, number>>>
  readonly sidebarWidth?: number
  readonly activeWorkspaceId?: string
}
