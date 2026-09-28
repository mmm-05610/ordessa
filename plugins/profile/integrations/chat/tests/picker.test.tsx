// @vitest-environment jsdom
/** Picker render gates (PV-10/ux.md §3/G20): immediate label, no status
 * badges, keyboard-reachable select, manage entry present. */
import { act, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, expect, it } from 'vitest'
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
  const select = picker?.querySelector('select')
  expect(select).not.toBeNull()
  const groups = select?.querySelectorAll('optgroup')
  expect(groups?.length).toBe(2)
  expect(groups?.[0]?.getAttribute('label')).toBe('Pi')
  const manage = container.querySelector('[data-profile-manage]')
  expect(manage?.textContent).toBe('管理')

  await act(async () => {
    select!.value = 'pi::p2'
    select!.dispatchEvent(new Event('change', { bubbles: true }))
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
  const select = container.querySelector('select')
  expect((select as HTMLSelectElement | null)?.disabled).toBe(true)
  expect((select as HTMLSelectElement | null)?.title).toBe('Profile 未启用')
})
