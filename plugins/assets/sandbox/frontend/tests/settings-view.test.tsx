// Rendering rules for the "Harness 原生隔离" region (UX §Settings, FR-08/FR-09)
// and its keyboard/ARIA behaviour. The component under test is the one the real
// Workbench registry hands back, so a section that never registered cannot pass.
// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../../packages/workbench/src/model'
import {
  createInMemoryDraftStore,
  createSandboxSettingsRegion,
  sandboxCoverageText,
} from '../src/settings-region'
import {
  REQUEST, claudeDescribe, codexDescribe, describeResult, fakeTransport,
  noProvider, ok, option, providerError, unknownPinDescribe,
} from './fixtures'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const cleanups: (() => Promise<void>)[] = []
afterEach(async () => { for (const fn of cleanups.splice(0).reverse()) await fn() })

async function renderRegion(result: ReturnType<typeof describeResult> | null, responseKind: 'ok' | 'no-provider' | 'error' = 'ok') {
  const scope = new OwnedResources()
  const model = createWorkbench(new OwnedResources())
  const drafts = createInMemoryDraftStore()
  const transport = fakeTransport(
    responseKind === 'no-provider' ? noProvider()
      : responseKind === 'error' ? providerError('describe failed')
        : ok(result!),
  )
  const region = await createSandboxSettingsRegion({
    host: model.composition.forScope(scope), transport: transport.transport, request: REQUEST, drafts,
  })
  const section = model.sections.getSnapshot()[0]
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  cleanups.push(async () => { await act(async () => root.unmount()); container.remove(); scope.dispose() })
  await act(async () => { root.render(createElement(section.component)) })
  return { container, region, drafts, section }
}

const rows = (container: ParentNode) => [...container.querySelectorAll('[role="radio"]')]
const rowText = (container: ParentNode, optionId: string) =>
  rows(container).find(r => r.textContent?.includes(optionId))?.textContent ?? ''
const describedBy = (container: ParentNode, optionId: string) => {
  const row = rows(container).find(r => r.textContent?.includes(optionId))
  const ids = row?.getAttribute('aria-describedby')?.split(' ').filter(Boolean) ?? []
  return ids.map(id => [...container.querySelectorAll('[id]')].find(n => n.id === id)?.textContent ?? '').join(' ')
}

describe('the region renders describe facts only', () => {
  it('offers the measured option vocabulary verbatim, in the contributed order', async () => {
    const { container } = await renderRegion(codexDescribe())
    expect(container.querySelector('[role="radiogroup"]')).toBeTruthy()
    expect(rows(container).map(r => r.textContent)).toEqual([
      expect.stringContaining('sandbox_mode=read-only'),
      expect.stringContaining('sandbox_mode=workspace-write'),
      expect.stringContaining('sandbox_mode=danger-full-access'),
    ])
  })

  it('an unproven provider error reads as unavailable, never as uninstalled', async () => {
    const { container } = await renderRegion(null, 'error')
    const alert = container.querySelector('[role="alert"]')?.textContent ?? ''
    expect(alert).toContain('不可用')
    expect(alert).not.toMatch(/未安装|没有安装|not installed|uninstalled/)
    expect(alert).toContain('PROVIDER_BUSY')
  })

  it('an unknown pin shows no invented menu: zero options, not a default list', async () => {
    const { container } = await renderRegion(unknownPinDescribe())
    expect(rows(container)).toHaveLength(0)
    expect(container.textContent).not.toContain('sandbox_mode=read-only')
    expect(container.textContent).toContain('不提供')
  })

  it('Bash-only coverage is shown as measured scope and never claims all tools are isolated', async () => {
    const claude = option({ optionId: 'bash_sandbox=enabled', status: 'supported', coverage: ['bash'] })
    const text = sandboxCoverageText(claude)
    expect(text).toContain('bash')
    expect(text).toContain('仅')
    expect(text).not.toMatch(/全部工具|所有工具|完全隔离/)
    const { container } = await renderRegion(claudeDescribe())
    expect(rowText(container, 'bash_sandbox=enabled')).toContain('bash')
    expect(container.textContent).not.toMatch(/全部工具|所有工具|完全隔离|fully isolated/)
  })

  it('an option with no coverage evidence is stated as unproven rather than silent', async () => {
    expect(sandboxCoverageText(option({ coverage: [] }))).toMatch(/无实测覆盖|未证实/)
  })

  it('never labels one brand with another brand vocabulary or a generic bypass word', async () => {
    const { container } = await renderRegion(claudeDescribe())
    const body = container.textContent ?? ''
    expect(body).not.toContain('sandbox_mode=')
    expect(body).not.toMatch(/YOLO|bypass|完全访问|自动模式/)
  })
})

describe('administrator limits and unproven options are read-only with a reason', () => {
  it('a locked option is aria-disabled, still focusable, and announces the organisational reason', async () => {
    const { container } = await renderRegion(describeResult({
      lockedByAdministrator: true,
      options: [option({ lockedByAdministrator: true }), option({ optionId: 'sandbox_mode=workspace-write' })],
    }))
    const row = rows(container).find(r => r.textContent?.includes('sandbox_mode=read-only'))!
    expect(row.getAttribute('aria-disabled')).toBe('true')
    expect((row as HTMLButtonElement).disabled).toBe(false) // focusable so the reason is reachable
    expect(describedBy(container, 'sandbox_mode=read-only')).toContain('组织/宿主限制')
  })

  it('unsupported and unknown options are offered as read-only with their evidence status', async () => {
    const { container } = await renderRegion(codexDescribe())
    const danger = rows(container).find(r => r.textContent?.includes('danger-full-access'))!
    expect(danger.getAttribute('aria-disabled')).toBe('true')
    expect(danger.textContent).toContain('不支持')
    const { container: claude } = await renderRegion(claudeDescribe())
    const bash = rows(claude).find(r => r.textContent?.includes('bash_sandbox=enabled'))!
    expect(bash.getAttribute('aria-disabled')).toBe('true')
    expect(bash.textContent).toMatch(/未证实|无法证明/)
  })

  it('keeps every contributed option in the tab order at its DOM position', async () => {
    const { container, drafts } = await renderRegion(codexDescribe())
    const buttons = [...container.querySelectorAll('button')]
    // every row describe reported is keyboard-reachable — a read-only row is
    // announced, not removed from the tab order
    expect(buttons).toHaveLength(3)
    expect(buttons.map(b => b.getAttribute('data-option-id'))).toEqual([
      'sandbox_mode=read-only', 'sandbox_mode=workspace-write', 'sandbox_mode=danger-full-access',
    ])
    expect(buttons.every(b => !(b as HTMLButtonElement).disabled)).toBe(true)
    const selectable = buttons.filter(b => b.getAttribute('aria-disabled') !== 'true')
    expect(selectable.map(b => b.getAttribute('data-option-id'))).toEqual([
      'sandbox_mode=read-only', 'sandbox_mode=workspace-write',
    ])
    await act(async () => { (selectable[1] as HTMLButtonElement).click() })
    expect(drafts.read('codex')).toEqual({ optionId: 'sandbox_mode=workspace-write' })
  })
})
