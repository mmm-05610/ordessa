// T015 red-first: the describe-driven 「权限与审批」 view (jsdom level).
// Proves: the four ux.md §Settings areas render from the closed describe
// round-trip; ready:false reads as 无法证明生效 (never 未安装); an unverified
// source ceiling is disclosed as non-enforceable instead of presented as an
// organization limit; needsReview items read 待复核…不放行 with their reason;
// desiredMode stays a brand-bound pair with no cross-brand synonym labels;
// forbidden strings absent; widening click refused with the stable code.
// @vitest-environment jsdom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../packages/workbench/src/model'
import { createPermissionsSettingsRegion } from '../src/settings-region'
import {
  approvalsSource, approvalPayload, describeCeilingRow, describeIntentRow, describePayload,
  FakeDescribeTransport, readyPayload, settledPayload,
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

async function mount(payload: unknown, approvals: readonly unknown[] = []) {
  const region = await createPermissionsSettingsRegion({
    host: host().host,
    transport: new FakeDescribeTransport([{ status: 'ok', payload }]),
    approvalFacts: { load: async () => approvals },
  })
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => { root.render(createElement(region.section.component, {})) })
  return { region, container }
}

const textOf = (container: ParentNode) => container.textContent ?? ''
const lower = (container: ParentNode) => textOf(container).toLowerCase()

describe('the four ux.md §Settings areas are driven by real describe data', () => {
  it('规则来源 / 组织上限只读摘要 / 用户默认意图 / 审批历史 all present and fed from the payload', async () => {
    const { container } = await mount(readyPayload(), [approvalPayload('approval_a'), settledApproval()])
    const headings = [...container.querySelectorAll('h3')].map(h => h.textContent)
    expect(headings).toEqual(expect.arrayContaining(['规则来源', '组织上限（只读）', '用户默认意图', '审批历史过滤']))
    // 规则来源: derived from the describe ceiling + intent rows
    expect(container.querySelector('[data-rule-source]')!.textContent).toContain('org-ceiling@3')
    // 组织上限: the describe row digest and entries
    expect(container.querySelector('[data-ceiling-digest]')!.textContent).toContain('org-ceiling@3')
    expect(textOf(container)).toContain('硬性拒绝：bash(/etc/**)、webfetch')
    // 用户默认意图: the describe intent row
    expect(textOf(container)).toContain('legacy-profile:p1@1')
    // 审批历史: decoded approval rows from the same refresh round-trip
    expect(container.querySelectorAll('[data-history-row]').length).toBe(2)
  })

  it('ceiling widen stays aria-disabled with the reason and a click is refused with the stable code', async () => {
    const { region, container } = await mount(readyPayload())
    const widen = container.querySelector('[data-ceiling-widen]') as HTMLButtonElement
    expect(widen.getAttribute('aria-disabled')).toBe('true')
    const reasonId = widen.getAttribute('aria-describedby')
    expect(container.querySelector(`[id="${reasonId}"]`)!.textContent).toContain('该项由组织/宿主限制')
    await act(async () => { widen.click() })
    expect(container.querySelector('[role="status"]')!.textContent).toContain('POLICY_CEILING_VIOLATION')
    expect(region.getSnapshot().lastCeilingOutcome?.status).toBe('refused')
  })

  it('a ready:false answer reads 无法证明生效 — never 未安装 and never 已生效', async () => {
    const { container } = await mount(describePayload({ ready: false }))
    expect(textOf(container)).toContain('无法证明生效')
    expect(textOf(container)).not.toContain('未安装')
    expect(textOf(container)).not.toContain('not installed')
    // and while unproven the ceiling summary is never presented as enforceable
    expect(textOf(container)).toContain('非可执行')
  })

  it('an unverified-source ceiling is rendered as non-enforceable, not as an organization limit', async () => {
    const { container } = await mount(describePayload({
      ceilings: [describeCeilingRow({ source: 'unverified', signed: false })],
    }))
    expect(textOf(container)).toContain('非可执行')
    expect(textOf(container)).toContain('未通过可信来源校验')
    // it never enters the organization-limit row set
    for (const row of container.querySelectorAll('[data-ceiling-row]')) {
      expect(row.textContent).not.toContain('unverified')
    }
  })

  it('desiredMode renders only as its own brand-scoped pair with the equivalence disclaimer', async () => {
    const { container } = await mount(describePayload({
      intents: [describeIntentRow({ desiredMode: { brand: 'claude-code', name: 'plan' } })],
    }))
    expect(textOf(container)).toContain('claude-code:plan')
    expect(textOf(container)).toContain('不做跨品牌等价')
  })

  it('needsReview items surface 待复核 with their reason and 不放行 — nothing auto-allows them', async () => {
    const { container } = await mount(describePayload({
      needsReview: [{ source: 'legacy-profile:p1', index: 2, reason: '旧规则语义无法核验' }],
    }))
    const review = container.querySelector('[data-needs-review]')
    expect(review).not.toBeNull()
    expect(review!.textContent).toContain('旧规则语义无法核验')
    expect(review!.textContent).toContain('待复核')
    expect(review!.textContent).toContain('不放行')
    // no interactive control exists on a review row: it can never be "confirmed away"
    expect(review!.querySelector('button, select, input')).toBeNull()
  })

  it('no cross-brand synonym labels are ever presented (FR-09/US4)', async () => {
    const { container } = await mount(readyPayload(), [approvalPayload('approval_a')])
    const text = lower(container)
    for (const forbidden of ['yolo', 'full access', 'bypass']) {
      expect(text, forbidden).not.toContain(forbidden)
    }
    expect(textOf(container)).not.toMatch(/\bauto\b/)
    expect(textOf(container)).toContain('只读')
  })
})

function settledApproval() {
  return {
    approvalId: 'approval_b', sessionId: 's2', nativeRequestId: 'native-approval_b',
    requestId: 'op-approval_b', version: 2, state: 'settled', decision: 'deny',
    scope: { kind: 'once' },
    receipt: { nativeRequestId: 'native-approval_b', approvalId: 'approval_b', confirmed: true, observedAt: '2026-01-02T00:00:00Z' },
    refusal: null,
    display: {
      operationCategory: '执行命令', targetSummary: '<目标已脱敏：bash>',
      policySource: '组织上限', selectableScopes: [{ kind: 'once' }],
    },
  }
}
