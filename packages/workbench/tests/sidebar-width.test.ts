import { describe, expect, it } from 'vitest'
import {
  SIDEBAR_INITIAL_WIDTH_PX, SIDEBAR_MAX_WIDTH_PX, SIDEBAR_MIN_WIDTH_PX,
  clampSidebarWidth, sidebarDefaultWidthPx, sidebarWidthBounds,
} from '../src/sidebar-width'

// Pure unit tests for the ported clamp (see PROVENANCE.md). jsdom has no
// geometry, so the container-dependent rules live here; the browser-side
// resize/keyboard wiring stays with react-resizable-panels.
describe('sidebar width bounds (pure)', () => {
  it('starts at the 264px design target in a roomy container', () => {
    expect(SIDEBAR_INITIAL_WIDTH_PX).toBe(264)
    expect(sidebarDefaultWidthPx(1280)).toBe(264)
    expect(clampSidebarWidth(264, 1280)).toBe(264)
  })

  it('keeps the 220px operating floor', () => {
    expect(SIDEBAR_MIN_WIDTH_PX).toBe(220)
    expect(clampSidebarWidth(100, 1280)).toBe(220)
    expect(clampSidebarWidth(220, 1280)).toBe(220)
  })

  it('caps at min(360px, container × 40%)', () => {
    expect(SIDEBAR_MAX_WIDTH_PX).toBe(360)
    // wide container: the absolute 360px cap wins
    expect(clampSidebarWidth(500, 1280)).toBe(360)
    expect(sidebarWidthBounds(900)).toEqual({ min: 220, max: 360, constrained: false })
    // medium container: 40% of the container wins (700 × 0.4 = 280)
    expect(sidebarWidthBounds(700)).toEqual({ min: 220, max: 280, constrained: false })
    expect(clampSidebarWidth(500, 700)).toBe(280)
    expect(sidebarDefaultWidthPx(700)).toBe(264)
  })

  it('conflict: an extremely narrow container prefers an operable smaller width and flags it', () => {
    // 480 × 0.4 = 192 < 220 floor → the bounds collapse onto the container cap
    const bounds = sidebarWidthBounds(480)
    expect(bounds).toEqual({ min: 192, max: 192, constrained: true })
    expect(clampSidebarWidth(264, 480)).toBe(192)
    expect(clampSidebarWidth(50, 480)).toBe(192)
    expect(sidebarDefaultWidthPx(480)).toBe(192)
  })

  it('falls back to the absolute bounds when the container is not measured (jsdom)', () => {
    expect(sidebarWidthBounds()).toEqual({ min: 220, max: 360, constrained: false })
    expect(sidebarWidthBounds(0)).toEqual({ min: 220, max: 360, constrained: false })
    expect(clampSidebarWidth(264)).toBe(264)
    expect(clampSidebarWidth(999)).toBe(360)
    expect(clampSidebarWidth(10)).toBe(220)
  })
})
