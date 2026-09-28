// @vitest-environment jsdom
// T020: empty-Workbench coverage at product-realistic level — the shell mounted
// with ZERO registered views, modules, overlays or UI contributions (the same
// state the real product boots into before any extension activates).
// The composition suite's first case proves the empty text and the missing
// module nav; this file closes the remaining structural angles: tab strips,
// region-actions select/close, region labels, and the disabled layout
// controls for empty auxiliary regions.
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createCommands } from '../../../plugins/commands/src/entry'
import { createWorkbench } from '../src/model'
import { WorkbenchShell } from '../src/shell'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanup: (() => void | Promise<void>)[] = []
window.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }
window.matchMedia = (query: string) => ({ matches: false, media: query, onchange: null, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {}, dispatchEvent: () => true })
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })
async function mount(element: React.ReactNode) {
  const container = document.createElement('div'); document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

const regions = ['left', 'main', 'right', 'top', 'bottom'] as const
const labels: Record<typeof regions[number], string> = { left: '左侧栏', main: '主区', right: '右侧栏', top: '顶部面板', bottom: '底部面板' }

describe('empty Workbench: shell with zero registered views and modules', () => {
  it('shows the empty state with no tab strips and no region-actions select/close', async () => {
    const lifetime = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // presence: the empty state itself is the only main-region body content
    expect(container.querySelector('.wb-empty')?.textContent).toContain('工作区已就绪')
    expect(container.querySelectorAll('[data-region].wb-region')).toHaveLength(5)
    // absence: no tab strip anywhere — not even an empty group container
    expect(container.querySelectorAll('[role="group"]')).toHaveLength(0)
    for (const region of regions) {
      expect(container.querySelectorAll(`[data-region="${region}"] [role="group"]`)).toHaveLength(0)
    }
    // absence: region actions hold no move select and no close button —
    // there is no active view to act on
    expect(container.querySelectorAll('.wb-region-actions select')).toHaveLength(0)
    expect(container.querySelectorAll('.wb-region-actions button[aria-label^="关闭"]')).toHaveLength(0)
    // absence pairing: contributions never leaked in (module nav, slots, overlays)
    expect(container.querySelectorAll('[data-module-nav]')).toHaveLength(0)
    expect(container.querySelector('[data-testid="wb-overlays"]')).toBeNull()
    await act(async () => { lifetime.dispose() })
  })

  it('keeps all five region labels present while every region is empty', async () => {
    const lifetime = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    // the label placeholder takes the place of the hidden tab strip in ALL
    // five regions, each inside its own labelled section
    const shown = [...container.querySelectorAll('.wb-region-label')].map(n => n.textContent)
    expect(shown.sort()).toEqual(['主区', '左侧栏', '右侧栏', '顶部面板', '底部面板'].sort())
    expect(shown).toHaveLength(5)
    for (const region of regions) {
      const section = container.querySelector(`[data-region="${region}"]`)
      expect(section, region).not.toBeNull()
      expect(section?.getAttribute('aria-label')).toBe(labels[region])
      expect(section?.querySelector('.wb-region-label')?.textContent).toBe(labels[region])
      // an empty region renders no view surface
      expect(section?.querySelector('.wb-surface')).toBeNull()
      expect(section?.hasAttribute('data-active-view')).toBe(false)
    }
    await act(async () => { lifetime.dispose() })
  })

  it('disables the layout controls for every empty auxiliary region', async () => {
    const lifetime = new OwnedResources()
    const model = createWorkbench(lifetime), commands = createCommands(lifetime)
    const container = await mount(<WorkbenchShell model={model} commands={commands} />)
    const layoutButtons = [...container.querySelectorAll('.wb-layout-actions button')]
    // four auxiliary toggles plus the reset button
    expect(layoutButtons).toHaveLength(5)
    for (const region of ['left', 'right', 'top', 'bottom'] as const) {
      const toggle = layoutButtons.find(b => b.getAttribute('aria-label')?.endsWith(labels[region]))
      expect(toggle, labels[region]).toBeTruthy()
      expect(toggle!.disabled, `${labels[region]} control must be inert while empty`).toBe(true)
      expect(toggle!.getAttribute('title')).toContain('（无视图）')
      // no pressed state is claimed for a region that holds nothing
      expect(toggle!.getAttribute('aria-pressed')).toBe('false')
      // the empty auxiliary region is inert and keeps only its collapse affordance
      const section = container.querySelector(`[data-region="${region}"]`)
      expect(section?.hasAttribute('inert')).toBe(true)
      expect(section!.querySelectorAll('.wb-region-actions button')).toHaveLength(1)
      expect(section!.querySelector('.wb-region-actions button')?.getAttribute('aria-label')).toBe(`收起${labels[region]}`)
    }
    // the main region is the one place that is never inert or collapsible
    expect(container.querySelector('[data-region="main"]')?.hasAttribute('inert')).toBe(false)
    expect(container.querySelectorAll('[data-region="main"] .wb-region-actions button')).toHaveLength(0)
    // reset stays available: it operates on layout state, not on views
    expect(layoutButtons.find(b => b.getAttribute('aria-label') === '重置布局')?.disabled).toBe(false)
    // and the status bar carries no slot contributions — only the fixed entry
    expect([...container.querySelectorAll('.wb-status button')].map(b => b.textContent)).toEqual(['设置'])
    await act(async () => { lifetime.dispose() })
  })
})
