// @vitest-environment jsdom
// V01 counterexample half: merely importing @ordessa/ui must not create DOM,
// inject styles or register any global listener, and must not need the
// registry. This file therefore performs NO static import of ../src — the
// package is only reached through the dynamic import below, so anything the
// module did at import time is observable.
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  for (const fn of cleanups.splice(0).reverse()) await fn()
  vi.restoreAllMocks()
})

describe('V01 import purity', () => {
  it('V01 importing @ordessa/ui injects no style nodes and registers no global listener or timer', async () => {
    const styleNodesBefore = document.querySelectorAll('style, link[rel="stylesheet"]').length
    const headNodesBefore = document.head.childNodes.length
    const bodyNodesBefore = document.body.childNodes.length
    const globalHooks: string[] = []
    const originalWindowOn = window.addEventListener
    const originalDocumentOn = document.addEventListener
    const originalMatchMedia = window.matchMedia
    const originalSetTimeout = globalThis.setTimeout
    window.addEventListener = ((type: string, ...rest: unknown[]) => {
      globalHooks.push(`window:${type}`)
      return (originalWindowOn as (...args: unknown[]) => void)(type, ...rest)
    }) as typeof window.addEventListener
    document.addEventListener = ((type: string, ...rest: unknown[]) => {
      globalHooks.push(`document:${type}`)
      return (originalDocumentOn as (...args: unknown[]) => void)(type, ...rest)
    }) as typeof document.addEventListener
    window.matchMedia = ((query: string) => {
      globalHooks.push(`matchMedia:${query}`)
      return {
        matches: false, media: query, onchange: null, addListener() {}, removeListener() {},
        addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true,
      } as unknown as MediaQueryList
    }) as unknown as typeof window.matchMedia
    globalThis.setTimeout = ((fn: unknown, ms?: number, ...args: unknown[]) => {
      globalHooks.push(`setTimeout:${String(typeof fn === 'function' ? fn.name || 'anonymous' : fn)}`)
      return originalSetTimeout(fn as (...a: unknown[]) => void, ms, ...args)
    }) as typeof setTimeout
    let ui: typeof import('../src/index')
    try {
      ui = await import('../src/index')
      // F05/V01 negative: importing the JS never touches the document, the
      // window or timers — and nothing here needed `import('@ordessa/ui-components')`
      // (the registry) to produce these exports.
      expect(ui.Button, 'Button export').toBeDefined()
      expect(ui.Card.Root, 'Card namespace export').toBeDefined()
      expect(ui.Field.Control, 'Field namespace export').toBeDefined()
      expect(globalHooks, `global hooks: ${globalHooks.join(', ')}`).toEqual([])
    } finally {
      window.addEventListener = originalWindowOn
      document.addEventListener = originalDocumentOn
      window.matchMedia = originalMatchMedia
      globalThis.setTimeout = originalSetTimeout
    }
    expect(document.querySelectorAll('style, link[rel="stylesheet"]').length).toBe(styleNodesBefore)
    expect(document.head.childNodes.length).toBe(headNodesBefore)
    expect(document.body.childNodes.length).toBe(bodyNodesBefore)
  })

  it('V01 the freshly imported module renders in a plain root without any stylesheet present', async () => {
    const ui = await import('../src/index')
    const container = document.createElement('div')
    document.body.append(container)
    const root = createRoot(container)
    cleanups.push(async () => {
      await act(async () => root.unmount())
      container.remove()
    })
    await act(async () => root.render(createElement(ui.Button, null, 'bare')))
    const button = container.querySelector('button.ods-ui-button')
    expect(button?.textContent).toBe('bare')
    // styles remain an explicit, separately loaded entry (./styles.css) — the
    // rendered tree did not bring its own <style> tag along
    expect(document.querySelectorAll('style').length).toBe(0)
  })
})
