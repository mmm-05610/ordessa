// @vitest-environment jsdom
/** Picker render gates (PV-10/ux.md §3/G20): immediate label, no status
 * badges, keyboard-reachable select, manage entry present. */
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it, vi } from 'vitest'
import { ProfilePicker } from '../src/picker'
import type { ProfileCatalogGroup } from '@ordessa/plugin-profile-api'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const GROUPS: readonly ProfileCatalogGroup[] = [
  { harnessId: 'pi', harnessTitle: 'Pi', profiles: [
    { harnessId: 'pi', profileId: 'p1', displayName: '开发助手', archived: false },
    { harnessId: 'pi', profileId: 'p2', displayName: '代码审阅', archived: false },
  ] },
  { harnessId: 'codex', harnessTitle: 'Codex', profiles: [
    { harnessId: 'codex', profileId: 'cx1', displayName: '默认', archived: false },
  ] },
]

const cleanup: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanup.splice(0).reverse()) await fn() })

async function mount(element: ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanup.push(async () => { await act(async () => root.unmount()); container.remove() })
  await act(async () => root.render(element))
  return container
}

async function openMenu(container: HTMLElement) {
  await act(async () => {
    container.querySelector('[data-profile-trigger]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
  })
}

it('renders harness groups, the selected name, and a manage entry', async () => {
  let selected: string | null = null
  const container = await mount(
    <ProfilePicker
      label={null}
      groups={GROUPS}
      onOpenManager={() => {}}
      onSelect={(s) => { selected = s.displayName }}
    />,
  )
  const picker = container.querySelector('[data-profile-picker]')
  expect(picker).not.toBeNull()
  await openMenu(container)
  expect(document.querySelector('[data-profile-menu]')?.textContent).toContain('Pi')
  expect(document.querySelector('[data-profile-menu]')?.textContent).toContain('Codex')
  const manage = container.querySelector('[data-profile-manage]')
  expect(manage?.textContent).toBe('管理')

  await act(async () => {
    document.querySelector<HTMLElement>('[data-profile-value="pi::p2"]')!.click()
  })
  expect(selected).toBe('代码审阅')
})

it('shows the selected profile immediately and never renders status badges', async () => {
  const container = await mount(
    <ProfilePicker label="日常" groups={GROUPS} onSelect={() => {}} />,
  )
  const text = container.textContent ?? ''
  expect(text).toContain('日常')
  for (const badge of ['当前使用', '下轮待生效', '待生效', '本会话有修改', '已应用']) {
    expect(text).not.toContain(badge)
  }
})

it('disabled pickers expose their reason instead of failing silently', async () => {
  const container = await mount(
    <ProfilePicker label={null} groups={[]} disabledReason="Profile 未启用" onSelect={() => {}} />,
  )
  const trigger = container.querySelector<HTMLButtonElement>('[data-profile-trigger]')
  expect(trigger?.disabled).toBe(true)
  expect(trigger?.title).toBe('Profile 未启用')
})

it('reselects the current profile on every menu click without clearing it', async () => {
  const onSelect = vi.fn()
  const onClearSelection = vi.fn()
  const onRefresh = vi.fn()
  const container = await mount(<ProfilePicker label="开发助手" groups={GROUPS}
    onSelect={onSelect} onClearSelection={onClearSelection} onRefresh={onRefresh} />)
  expect(onSelect).not.toHaveBeenCalled()
  await openMenu(container)
  await act(async () => document.querySelector<HTMLElement>('[data-profile-value="pi::p1"]')!.click())
  expect(onSelect).toHaveBeenCalledExactlyOnceWith({ harnessId: 'pi', profileId: 'p1', displayName: '开发助手' })
  expect(onClearSelection).not.toHaveBeenCalled()
  expect(onRefresh).not.toHaveBeenCalled()
  await openMenu(container)
  await act(async () => document.querySelector<HTMLElement>('[data-profile-value="pi::p1"]')!.click())
  expect(onSelect).toHaveBeenCalledTimes(2)
  expect(container.querySelector('[data-profile-trigger]')?.textContent).toContain('开发助手')
  expect(container.querySelector('[data-profile-reapply]')).toBeNull()
})

it.each([null, '已移除的预设'])('does not offer reapply without a catalogued selection (%s)', async label => {
  const container = await mount(<ProfilePicker label={label} groups={GROUPS} onSelect={() => {}} />)
  expect(container.querySelector('[data-profile-reapply]')).toBeNull()
})

it.each(['disabled', 'archived'])('cannot choose an unavailable profile (%s)', async state => {
  const onSelect = vi.fn()
  const groups = state === 'archived' ? GROUPS.map(group => ({ ...group,
    profiles: group.profiles.map(profile => ({ ...profile, archived: true })) })) : GROUPS
  const container = await mount(<ProfilePicker label="开发助手" groups={groups}
    disabledReason={state === 'disabled' ? '会话不可用' : undefined} onSelect={onSelect} />)
  if (state === 'disabled') {
    expect(container.querySelector<HTMLButtonElement>('[data-profile-trigger]')?.disabled).toBe(true)
  } else {
    await openMenu(container)
    const item = document.querySelector<HTMLElement>('[data-profile-value="pi::p1"]')!
    expect(item.hasAttribute('data-disabled')).toBe(true)
    await act(async () => item.click())
  }
  expect(onSelect).not.toHaveBeenCalled()
})

it('closes with Escape without selecting or clearing', async () => {
  const onSelect = vi.fn(), onClearSelection = vi.fn()
  const container = await mount(<ProfilePicker label="开发助手" groups={GROUPS} onSelect={onSelect} onClearSelection={onClearSelection} />)
  await openMenu(container)
  await act(async () => document.querySelector('[data-profile-menu]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(document.querySelector('[data-profile-menu]')).toBeNull()
  expect(onSelect).not.toHaveBeenCalled()
  expect(onClearSelection).not.toHaveBeenCalled()
})
