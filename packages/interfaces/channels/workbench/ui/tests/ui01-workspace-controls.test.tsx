// @vitest-environment jsdom
import { act, type ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  Disclosure,
  ListGroup,
  ListRow,
  LoadingState,
  MenuContent,
  MenuGroup,
  MenuItem,
  SearchInput,
  SettingsGroup,
  SettingsRow,
  SubmenuItem,
  Switch,
  Tabs,
  Tooltip,
} from '../src/workspace-controls'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: Array<() => void | Promise<void>> = []
afterEach(async () => {
  for (const cleanup of cleanups.splice(0).reverse()) await cleanup()
  vi.restoreAllMocks()
})
async function mount(element: ReactNode): Promise<{ container: HTMLElement; render(node: ReactNode): Promise<void> }> {
  const container = document.createElement('div')
  document.body.append(container)
  const root: Root = createRoot(container)
  cleanups.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return { container, render: async node => { await act(async () => root.render(node)) } }
}

describe('UI01 pure workspace controls', () => {
  it('menu content exposes labels, skips disabled items with arrow keys, and delegates Escape', async () => {
    const onEscape = vi.fn()
    const { container } = await mount(<MenuContent label="Workspace actions" onEscape={onEscape}>
      <MenuGroup label="Views">
        <MenuItem label="Open view">Open view</MenuItem>
        <MenuItem label="Unavailable" disabled>Unavailable</MenuItem>
        <MenuItem label="Close view">Close view</MenuItem>
      </MenuGroup>
    </MenuContent>)
    const menu = container.querySelector('[role="menu"]') as HTMLElement
    const items = [...container.querySelectorAll<HTMLButtonElement>('[role="menuitem"]')]
    expect(menu.getAttribute('aria-label')).toBe('Workspace actions')
    expect(container.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe('Views')
    expect(items[1]!.disabled).toBe(true)
    items[0]!.focus()
    await act(async () => { items[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })) })
    expect(document.activeElement).toBe(items[2])
    await act(async () => { menu.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })) })
    expect(onEscape).toHaveBeenCalledTimes(1)
  })

  it('submenu open state is controlled by its consumer and disabled items cannot open', async () => {
    const onOpenChange = vi.fn()
    const { container, render } = await mount(<SubmenuItem label="More" open={false} onOpenChange={onOpenChange}>
      <MenuContent label="More actions"><MenuItem label="Duplicate">Duplicate</MenuItem></MenuContent>
    </SubmenuItem>)
    const trigger = container.querySelector('[aria-haspopup="menu"]') as HTMLButtonElement
    expect(container.querySelector('[role="menu"]')).toBeNull()
    await act(async () => trigger.click())
    expect(onOpenChange).toHaveBeenCalledWith(true)
    expect(trigger.getAttribute('aria-expanded')).toBe('false')
    await render(<SubmenuItem label="More" open={false} disabled onOpenChange={onOpenChange}><span>Content</span></SubmenuItem>)
    await act(async () => (container.querySelector('[aria-haspopup="menu"]') as HTMLButtonElement).click())
    expect(onOpenChange).toHaveBeenCalledTimes(1)
  })

  it('tooltip associates its text with the focusable child without a portal', async () => {
    const { container } = await mount(<Tooltip content="Close this view"><button type="button" aria-label="Close">×</button></Tooltip>)
    const button = container.querySelector('button')!
    const id = button.getAttribute('aria-describedby')!
    expect(document.getElementById(id)?.getAttribute('role')).toBe('tooltip')
    expect(container.querySelector('.ods-ui-tooltip')?.contains(button)).toBe(true)
    expect(container.querySelector('[data-portal]')).toBeNull()
  })

  it('list selection, search, settings and loading remain consumer-owned and accessible', async () => {
    const onSelect = vi.fn(), onSearch = vi.fn()
    const { container } = await mount(<>
      <ListGroup label="Workspaces" description="Choose a workspace">
        <ListRow label="Alpha" selected onSelect={onSelect} actions={<button aria-label="Alpha options">⋯</button>}>Alpha</ListRow>
      </ListGroup>
      <SearchInput aria-label="Search settings" value="" onChange={onSearch} />
      <SettingsGroup label="Display"><SettingsRow label="Compact" description="Use less space"><Switch label="Compact mode" checked={false} onCheckedChange={() => undefined} /></SettingsRow></SettingsGroup>
      <LoadingState label="Loading preferences" />
    </>)
    expect(container.querySelector('[role="listbox"]')?.getAttribute('aria-label')).toBe('Workspaces')
    const option = container.querySelector('[role="option"]') as HTMLButtonElement
    expect(option.getAttribute('aria-selected')).toBe('true')
    await act(async () => option.click())
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(container.querySelector('[aria-label="Alpha options"]')).toBeTruthy()
    expect(container.querySelector('input[type="search"]')?.getAttribute('aria-label')).toBe('Search settings')
    expect(container.querySelector('fieldset legend')?.textContent).toBe('Display')
    expect(container.querySelector('[role="status"]')?.getAttribute('aria-live')).toBe('polite')
    expect(container.querySelector('.ods-ui-loading-state')?.className).not.toContain('danger')
  })

  it('tabs use controlled selection and keyboard navigation while skipping disabled tabs', async () => {
    const onValueChange = vi.fn()
    const { container } = await mount(<Tabs label="Settings pages" value="general" onValueChange={onValueChange}
      tabs={[{ id: 'general', label: 'General' }, { id: 'blocked', label: 'Blocked', disabled: true }, { id: 'advanced', label: 'Advanced' }]} />)
    const tabs = [...container.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
    expect(container.querySelector('[role="tablist"]')?.getAttribute('aria-label')).toBe('Settings pages')
    expect(tabs[0]!.getAttribute('aria-selected')).toBe('true')
    expect(tabs[1]!.disabled).toBe(true)
    tabs[0]!.focus()
    await act(async () => { tabs[0]!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true, cancelable: true })) })
    expect(onValueChange).toHaveBeenCalledWith('advanced')
    expect(document.activeElement).toBe(tabs[2])
    expect(tabs[0]!.getAttribute('aria-selected')).toBe('true')
  })

  it('switch and disclosure expose controlled state and refuse interaction while disabled', async () => {
    const onCheckedChange = vi.fn(), onOpenChange = vi.fn()
    const { container, render } = await mount(<>
      <Switch label="Enable hints" checked={false} onCheckedChange={onCheckedChange} />
      <Disclosure label="Advanced options" open={false} onOpenChange={onOpenChange}><p>Details</p></Disclosure>
    </>)
    const toggle = container.querySelector('[role="switch"]') as HTMLButtonElement
    expect(toggle.getAttribute('aria-label')).toBe('Enable hints')
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    await act(async () => toggle.click())
    expect(onCheckedChange).toHaveBeenCalledWith(true)
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    const disclosure = container.querySelector('[aria-expanded]') as HTMLButtonElement
    expect(disclosure.getAttribute('aria-controls')).toBeTruthy()
    await act(async () => disclosure.click())
    expect(onOpenChange).toHaveBeenCalledWith(true)
    await render(<Switch label="Enable hints" checked={false} disabled onCheckedChange={onCheckedChange} />)
    const disabledSwitch = container.querySelector('[role="switch"]') as HTMLButtonElement
    await act(async () => disabledSwitch.click())
    expect(onCheckedChange).toHaveBeenCalledTimes(1)
  })
})
