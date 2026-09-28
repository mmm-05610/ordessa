// T011 view-level assertions (jsdom level — a screen-reader/Electron pass is
// registered as not run in the README): [role=alert] wording, read-only
// ceiling rows with a stated reason, keyboard focusability, the four content
// areas and the absence of cross-brand synonym labels (FR-09/US4). Since
// T015 the mounted facts come from a `permissions.policy.describe`
// round-trip on the injected fake transport — never a stubbed provider.
// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../packages/workbench/src/model'
import { createPermissionsSettingsRegion } from '../src/settings-region'
import {
  approvalsSource, ceilingAbsentPayload, describeCeilingRow, describeIntentRow, describePayload,
  errorTransport, noProviderTransport, readyPayload,
} from './settings-fixtures'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const roots: Root[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => { root.unmount() })
})

function host() {
  const lifetime = new OwnedResources()
  const scope = new OwnedResources()
  const model = createWorkbench(lifetime)
  return { host: model.composition.forScope(scope) }
}

async function mountRegion(transport: Parameters<typeof createPermissionsSettingsRegion>[0]['transport'], approvals: readonly unknown[] = []) {
  const region = await createPermissionsSettingsRegion({
    host: host().host, transport, approvalFacts: approvalsSource(approvals),
  })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => { root.render(createElement(region.section.component, {})) })
  return { region, container }
}

const okTransport = (payload: unknown) => ({ describe: async () => ({ status: 'ok' as const, payload }) })

const textOf = (container: ParentNode) => container.textContent ?? ''
const lower = (container: ParentNode) => textOf(container).toLowerCase()

describe('provider states worded honestly (FR-08)', () => {
  it('a failing provider announces itself as an error state, never as an uninstallation', async () => {
    const { container } = await mountRegion(errorTransport())
    const alert = container.querySelector('[role="alert"]')
    expect(alert).not.toBeNull()
    expect(alert!.textContent).toContain('POLICY_SCOPE_UNVERIFIED')
    expect(textOf(container)).not.toContain('未安装')
    expect(textOf(container)).not.toContain('not installed')
    // and it still does not claim any authority verdict
    expect(textOf(container)).not.toContain('已放行')
    expect(textOf(container)).not.toContain('已放宽')
  })

  it('no provider => the component never mounts through the registry (nothing to assert)', async () => {
    const { container, region } = await mountRegion(noProviderTransport())
    expect(region.registered).toBe(false)
    expect(container.querySelector('[role="alert"]')).toBeNull()
  })

  it('an absent ceiling record is modelled as unverified, never as "no limit applies"', async () => {
    const { container } = await mountRegion(okTransport(ceilingAbsentPayload()))
    expect(textOf(container)).toContain('未证实没有上限，不等于没有上限')
    expect(textOf(container)).not.toContain('无限制')
  })
})

describe('the ready region renders the four ux.md §Settings areas', () => {
  it('headings: 规则来源 / 组织上限（只读） / 用户默认意图 / 审批历史', async () => {
    const { container } = await mountRegion(readyTransport())
    const headings = [...container.querySelectorAll('h3')].map(h => h.textContent)
    expect(headings).toEqual(expect.arrayContaining(['规则来源', '组织上限（只读）', '用户默认意图', '审批历史过滤']))
    // each region block is labelled by its heading
    for (const block of container.querySelectorAll('[data-settings-area]')) {
      expect(block.getAttribute('aria-labelledby')).toBeTruthy()
    }
  })

  it('ceiling rows are read-only, state the disabling reason, and a widening click is refused with the stable code', async () => {
    const { region, container } = await mountRegion(readyTransport())
    const widen = container.querySelector('[data-ceiling-widen]') as HTMLButtonElement
    expect(widen).not.toBeNull()
    expect(widen.getAttribute('aria-disabled')).toBe('true')
    const reasonId = widen.getAttribute('aria-describedby')
    expect(reasonId).toBeTruthy()
    expect(container.querySelector(`[id="${reasonId}"]`)!.textContent).toContain('该项由组织/宿主限制')
    await act(async () => { widen.click() })
    const outcome = container.querySelector('[data-ceiling-outcome]')
    expect(outcome!.textContent).toContain('POLICY_CEILING_VIOLATION')
    // refusal surfaced, never a silent write: facts unchanged
    expect(JSON.stringify(region.getSnapshot().state)).toContain('org-ceiling')
    expect(region.getSnapshot().lastCeilingOutcome?.status).toBe('refused')
  })

  it('no cross-brand synonym labels are ever presented (FR-09/US4)', async () => {
    const { container } = await mountRegion(readyTransport())
    const text = lower(container)
    for (const forbidden of ['yolo', 'full access', 'bypass']) {
      expect(text, forbidden).not.toContain(forbidden)
    }
    expect(textOf(container)).not.toMatch(/\bauto\b/)
    // the exposure level is rendered as an Ordessa interpretation label, not a
    // brand mode name — the ceiling's `maximumExposure: read` shows as 档位文案
    expect(textOf(container)).toContain('只读')
  })

  it('untrusted ceiling provenance is disclosed as non-enforceable instead of summarized as a bound', async () => {
    const { container } = await mountRegion(okTransport(describePayload({
      ceilings: [describeCeilingRow({ signed: false, source: 'unverified' })],
    })))
    expect(textOf(container)).toContain('未通过可信来源校验')
    expect(textOf(container)).toContain('非可执行')
    expect(textOf(container)).not.toContain('无限制')
  })

  it('the user intent summary binds a desiredMode to its own brand and disclaims equivalence', async () => {
    const { container } = await mountRegion(okTransport(describePayload({
      intents: [describeIntentRow({ desiredMode: { brand: 'claude-code', name: 'plan' } })],
    })))
    expect(textOf(container)).toContain('claude-code:plan')
    expect(textOf(container)).toContain('不做跨品牌等价')
  })

  it('legacy needsReview items surface as review debt with their reason, never as allowances', async () => {
    const { container } = await mountRegion(okTransport(describePayload({
      needsReview: [{ source: 'legacy-profile:p1', index: 2, reason: '旧规则语义无法核验' }],
    })))
    expect(textOf(container)).toContain('待复核')
    expect(textOf(container)).toContain('旧规则语义无法核验')
    expect(textOf(container)).toContain('不放行')
  })
})

describe('approval history filtering, focus and ARIA (jsdom level)', () => {
  it('the filter selects drive the list from backend facts only', async () => {
    const { container } = await mountRegion(readyTransport(), [
      {
        approvalId: 'approval_a', sessionId: 's1', nativeRequestId: 'native-approval_a',
        requestId: 'op-approval_a', version: 1, state: 'open', decision: null, scope: null,
        receipt: null, refusal: null,
        display: {
          operationCategory: '写入文件', targetSummary: '<目标已脱敏>',
          policySource: 'Profile 意图 + 组织上限', selectableScopes: [{ kind: 'once' }],
        },
      },
      {
        approvalId: 'approval_b', sessionId: 's2', nativeRequestId: 'native-approval_b',
        requestId: 'op-approval_b', version: 2, state: 'settled', decision: 'deny',
        scope: { kind: 'once' },
        receipt: { nativeRequestId: 'native-approval_b', approvalId: 'approval_b', confirmed: true, observedAt: '2026-01-02T00:00:00Z' },
        refusal: null,
        display: {
          operationCategory: '执行命令', targetSummary: '<目标已脱敏：bash>',
          policySource: '组织上限', selectableScopes: [{ kind: 'once' }],
        },
      },
    ])
    const statusSelect = container.querySelector('[data-history-filter="status"]') as HTMLSelectElement
    const rowsBefore = container.querySelectorAll('[data-history-row]').length
    expect(rowsBefore).toBe(2)
    await act(async () => {
      statusSelect.value = 'settled'
      statusSelect.dispatchEvent(new Event('change', { bubbles: true }))
    })
    const rows = [...container.querySelectorAll('[data-history-row]')]
    expect(rows.map(r => r.getAttribute('data-history-id'))).toEqual(['approval_b'])
    expect(textOf(container)).toContain('已决定拒绝')
    // filtering an unknown session returns nothing — it never fabricates a row
    const sessionInput = container.querySelector('[data-history-filter="session"]') as HTMLInputElement
    const valueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
    await act(async () => {
      valueSetter.call(sessionInput, 's-nope')
      sessionInput.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.querySelectorAll('[data-history-row]').length).toBe(0)
    expect(textOf(container)).toContain('没有匹配的后端审批记录')
  })

  it('read-only controls stay keyboard focusable and announce their reason', async () => {
    const { container } = await mountRegion(readyTransport())
    const widen = container.querySelector('[data-ceiling-widen]') as HTMLButtonElement
    widen.focus()
    expect(document.activeElement).toBe(widen)
    const statusSelect = container.querySelector('[data-history-filter="status"]') as HTMLSelectElement
    expect(statusSelect.getAttribute('aria-label')).toBeTruthy()
    statusSelect.focus()
    expect(document.activeElement).toBe(statusSelect)
  })
})

function readyTransport() {
  return okTransport(readyPayload())
}
