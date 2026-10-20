export interface Rect { left: number; top: number; right: number; bottom: number; width: number; height: number }
export interface Size { width: number; height: number }

/**
 * Pure popover placement, unit-testable without a layout engine: prefer below
 * the anchor, flip above when the bottom would clip, and always clamp both
 * axes inside the viewport. jsdom has no geometry; Electron smoke verifies
 * real pixels.
 */
export function placePopover(anchor: Rect, viewport: Size, overlay: Size, gap = 8, margin = 8): { left: number; top: number } {
  const left = Math.min(Math.max(margin, anchor.left), Math.max(margin, viewport.width - overlay.width - margin))
  const verticalLimit = Math.max(margin, viewport.height - overlay.height - margin)
  const below = anchor.bottom + gap
  const fitsBelow = viewport.height <= 0 || overlay.height <= 0 || below + overlay.height <= viewport.height - margin
  if (fitsBelow) return { left, top: Math.min(Math.max(margin, below), verticalLimit) }
  const above = anchor.top - gap - overlay.height
  return { left, top: above >= margin ? Math.min(above, verticalLimit) : verticalLimit }
}
