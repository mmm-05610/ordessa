import { describe, expect, it } from 'vitest'
import { placePopover } from '../src/popover'

const rect = (left: number, top: number, width = 100, height = 50) => ({ left, top, right: left + width, bottom: top + height, width, height })

describe('placePopover (pure clamp, no layout engine needed)', () => {
  const viewport = { width: 800, height: 600 }, overlay = { width: 200, height: 100 }

  it('places below the anchor when there is room', () => {
    expect(placePopover(rect(300, 200), viewport, overlay)).toEqual({ left: 300, top: 258 })
  })

  it('clamps horizontally near the right edge', () => {
    const p = placePopover(rect(700, 200), viewport, overlay)
    expect(p.left).toBe(800 - 200 - 8)
    expect(p.left + overlay.width).toBeLessThanOrEqual(viewport.width)
    expect(p.top).toBe(258)
  })

  it('flips above near the bottom edge', () => {
    const p = placePopover(rect(300, 500), viewport, overlay)
    expect(p.top).toBe(500 - 8 - 100)
    expect(p.top + overlay.height).toBeLessThanOrEqual(viewport.height)
  })

  it('clamps inside the viewport when it fits neither above nor below', () => {
    const p = placePopover(rect(300, 560), viewport, { width: 200, height: 560 })
    expect(p.top).toBeGreaterThanOrEqual(8)
    expect(p.top + 560).toBeLessThanOrEqual(600)
  })

  it('never leaves the viewport for any anchor position or overlay size in a swept grid', () => {
    for (let left = -60; left <= 860; left += 37) {
      for (let top = -60; top <= 660; top += 41) {
        for (const size of [overlay, { width: 780, height: 560 }, { width: 0, height: 0 }]) {
          const p = placePopover(rect(left, top), viewport, size)
          expect(p.left).toBeGreaterThanOrEqual(8)
          expect(p.left + Math.max(size.width, 0)).toBeLessThanOrEqual(viewport.width)
          expect(p.top).toBeGreaterThanOrEqual(8)
          expect(p.top + Math.max(size.height, 0)).toBeLessThanOrEqual(viewport.height)
        }
      }
    }
  })
})
