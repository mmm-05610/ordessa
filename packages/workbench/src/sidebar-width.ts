/**
 * Pure width bounds for the Workbench sidebar (left panel). Ported with
 * modification from the `clampWorkspaceSidebarWidth` idea in ZCode's
 * `app-shell/WorkspaceShellLayout.tsx` @ 29628c9 (see PROVENANCE.md):
 * Ordessa bounds replace the upstream ones, and NOTHING else is carried over —
 * no localStorage persistence, no legacy-ratio migration and no pointer resize
 * engine (react-resizable-panels keeps owning the actual resizing here).
 */
export const SIDEBAR_MIN_WIDTH_PX = 220
export const SIDEBAR_MAX_WIDTH_PX = 360
export const SIDEBAR_INITIAL_WIDTH_PX = 264
export const SIDEBAR_MAX_WIDTH_RATIO = 0.4

export interface SidebarWidthBounds {
  min: number
  max: number
  /** True when the container cannot even hold the operating minimum width:
   * the floor is lowered to the cap (可操作性优先，允许更小宽度) and the
   * collapse affordance stays available so the sidebar can get out of the way. */
  constrained: boolean
}

export function sidebarWidthBounds(containerWidthPx?: number): SidebarWidthBounds {
  const max = containerWidthPx && containerWidthPx > 0
    ? Math.round(Math.min(SIDEBAR_MAX_WIDTH_PX, containerWidthPx * SIDEBAR_MAX_WIDTH_RATIO))
    : SIDEBAR_MAX_WIDTH_PX
  const min = Math.min(SIDEBAR_MIN_WIDTH_PX, max)
  return { min, max, constrained: max < SIDEBAR_MIN_WIDTH_PX }
}

/** Clamp a desired width into the bounds for the given container. */
export function clampSidebarWidth(widthPx: number, containerWidthPx?: number): number {
  const { min, max } = sidebarWidthBounds(containerWidthPx)
  return Math.round(Math.min(Math.max(widthPx, min), max))
}

/** The initial/reset width (design target 264px, container-aware). */
export function sidebarDefaultWidthPx(containerWidthPx?: number): number {
  return clampSidebarWidth(SIDEBAR_INITIAL_WIDTH_PX, containerWidthPx)
}
