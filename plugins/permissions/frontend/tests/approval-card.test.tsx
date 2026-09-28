// Approval card behavior (US2, FR-04/FR-08/FR-09): the UI can only request a
// decision and render backend facts — it is never an authority.
// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import type { ChatLocation } from '@extensions/ordessa.chat-api/contract.js'
import { computeApprovalCardModel, PermissionsApprovalCard } from '../src/approval-region'
import { FakeApprovalTransport, openView, queryResolved, sessionLocation, stateRecord } from './support'

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const roots: Root[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await act(async () => { root.unmount() })
})

async function mount(element: React.ReactNode) {
  const container = document.createElement('div')
  document.body.append(container)
  const root = createRoot(container)
  roots.push(root)
  await act(async () => { root.render(element) })
  return container
}

const cardText = (container: ParentNode) => container.textContent ?? ''
const cardOf = (container: ParentNode) => container.querySelector('[data-testid="permissions-approval-card"]') as Element
const click = async (container: ParentNode, action: string) => {
  const button = cardOf(container).querySelector(`[data-action="${action}"]`) as HTMLButtonElement
  expect(button, action).toBeTruthy()
  await act(async () => { button.click() })
}
const otherSession: ChatLocation = { kind: 'session', connectionId: 'c1', sessionId: 's2', contextRevision: 1 }

describe('rule 1: a press only sends decide; 待确认 until backend + native receipt confirm', () => {
  it('the press sends exactly permissions.approvals.decide with the backend required params', async () => {
    let observedDecideParams: Record<string, unknown> | null = null
    const transport = new FakeApprovalTransport({
      decide: (params) => { observedDecideParams = { ...params }; return { outcome: 'unknown', reason: 'hold' } },
    })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'allow-once')
    expect(transport.calls.map(c => c.method)).toEqual(['decide'])
    expect(Object.keys(observedDecideParams as unknown as Record<string, unknown>).sort())
      .toEqual(['approvalId', 'decision', 'expectedVersion', 'requestId', 'scope', 'sessionId'])
    expect(observedDecideParams).toMatchObject({
      requestId: 'op-key-1', approvalId: 'approval_abc', expectedVersion: 1, decision: 'allow',
      scope: { kind: 'once' }, sessionId: 's1',
    })
    expect(cardText(container)).not.toContain('已决定')
  })

  it('the card shows 待确认 after the press and only shows 已决定 once the query reports the settled decision AND a confirmed native receipt', async () => {
    const confirmed = { nativeRequestId: 'native-1', approvalId: 'approval_abc', confirmed: true, observedAt: '2026-01-01T00:00:00Z' }
    const transport = new FakeApprovalTransport({
      decide: () => ({ outcome: 'recorded', version: 2, decision: 'allow' }),
      query: () => queryResolved({ ...stateRecord({ state: 'settled', decision: 'allow' }) }, null),
    })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'allow-once')
    // decision recorded on the backend, but no confirmed receipt yet:
    expect(cardText(container)).toContain('待确认')
    expect(cardText(container)).not.toContain('已决定')
    // reconcile reports the confirmed receipt — only now 已决定 appears
    transport.script.query = () => queryResolved({ state: 'settled', decision: 'allow' }, confirmed)
    await click(container, 'query')
    expect(cardText(container)).toContain('已决定')
    expect(cardText(container)).not.toContain('待确认')
  })

  it('a forged local write cannot make the card show 已决定 without backend facts', () => {
    const withAuthority = {
      pending: false, linkLost: false, controlsClosed: false, recordedDecisionLabel: null,
      invalidReason: null, showDecided: true, decidedAs: 'allow', decision: 'allow',
    } as never
    const model = computeApprovalCardModel(openView(), sessionLocation, withAuthority)
    expect(model.showDecided).toBe(false)
    expect(model.headline).not.toContain('已决定')
  })

  it('a pressed allow whose decide never resolves keeps the card at 待确认 and never 已决定/允许生效', async () => {
    const transport = new FakeApprovalTransport({ decide: () => new Promise(() => {}) })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'allow-once')
    expect(cardText(container)).toContain('待确认')
    expect(cardText(container)).not.toContain('已决定')
  })
})

describe('rule 2: AlreadyRecorded / InvalidApproval / stale / cross-session', () => {
  it('AlreadyRecorded renders the existing decision and never re-activates the controls', async () => {
    const transport = new FakeApprovalTransport({
      decide: () => ({ outcome: 'already_recorded', version: 2, decision: 'deny', requestId: 'op-key-1' }),
    })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'deny')
    expect(cardText(container)).toContain('决定已记录')
    expect(cardText(container)).toContain('拒绝')
    expect(cardOf(container).querySelectorAll('[data-action="allow-once"][aria-disabled="false"]')).toHaveLength(0)
    expect(cardOf(container).querySelectorAll('[data-action="deny"][aria-disabled="false"]')).toHaveLength(0)
    await click(container, 'allow-once')
    expect(transport.calls.filter(c => c.method === 'decide')).toHaveLength(1) // no second activation
  })

  it('InvalidApproval makes the card non-actionable with a stated reason', async () => {
    const transport = new FakeApprovalTransport({
      decide: () => ({ outcome: 'invalid', reason: 'APPROVAL_NOT_ACTIONABLE: the execution already ended; start a new turn' }),
    })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'allow-once')
    expect(cardText(container)).toContain('APPROVAL_NOT_ACTIONABLE')
    expect(cardOf(container).querySelectorAll('[data-action="allow-once"][aria-disabled="true"]')).toHaveLength(1)
    await click(container, 'deny')
    expect(transport.calls.filter(c => c.method === 'decide')).toHaveLength(1)
  })

  it('a stale/expired approval view (APPROVAL_STALE) is non-actionable with a reason', async () => {
    const stale = openView({
      status: 'invalid',
      refusal: { code: 'APPROVAL_STALE', message: 'the approval or snapshot no longer refers to this operation' },
    })
    const transport = new FakeApprovalTransport({})
    const container = await mount(<PermissionsApprovalCard view={stale} location={sessionLocation} transport={transport} />)
    expect(cardText(container)).toContain('APPROVAL_STALE')
    await click(container, 'allow-once')
    await click(container, 'deny')
    expect(transport.calls).toEqual([])
  })

  it('a cross-session approval (ChatLocation mismatch) is non-actionable and its actions never reach the transport', async () => {
    const transport = new FakeApprovalTransport({})
    const container = await mount(<PermissionsApprovalCard view={openView()} location={otherSession} transport={transport} />)
    expect(cardText(container)).toContain('会话')
    await click(container, 'allow-once')
    expect(transport.calls).toEqual([])
    expect(cardText(container)).not.toContain('已决定')
  })
})

describe('rule 3: transport error / timeout / unknown ⇒ allow disabled, 查询/恢复 remains (fail-closed)', () => {
  it('a rejecting decide disables the allow actions while 查询/恢复 stays actionable', async () => {
    const transport = new FakeApprovalTransport({
      decide: () => { throw new Error('transport timeout after 30s') },
      query: () => queryResolved({ state: 'open' }),
    })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'allow-once')
    expect(cardText(container)).toContain('查询')
    expect(cardOf(container).querySelector('[data-action="allow-once"]')?.getAttribute('aria-disabled')).toBe('true')
    expect(cardOf(container).querySelector('[data-action="allow-bounded"]')?.getAttribute('aria-disabled')).toBe('true')
    expect(cardOf(container).querySelector('[data-action="query"]')?.getAttribute('aria-disabled')).toBe('false')
    expect(cardText(container)).not.toContain('已决定')
    await click(container, 'query')
    expect(transport.calls.filter(c => c.method === 'decide')).toHaveLength(1) // recovery never re-sends the decision
  })

  it('an unknown query outcome keeps the allow actions disabled and never reads as allowed', async () => {
    const transport = new FakeApprovalTransport({
      decide: () => ({ outcome: 'unknown', reason: 'no answer from the backend' }),
    })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    await click(container, 'allow-once')
    expect(cardOf(container).querySelector('[data-action="allow-once"]')?.getAttribute('aria-disabled')).toBe('true')
    expect(cardText(container)).not.toContain('已决定')
    expect(cardText(container)).not.toContain('安全')
    expect(cardText(container)).toContain('unknown')
  })
})

describe('unknown native receipt', () => {
  it('a settled decision with an unconfirmed receipt yields 待确认/unknown text, never safe/allowed', () => {
    const settled = openView({ status: 'settled', decision: 'allow', nativeReceipt: { kind: 'unknown' } })
    const model = computeApprovalCardModel(settled, sessionLocation, {
      pending: false, linkLost: false, controlsClosed: false, recordedDecisionLabel: null, invalidReason: null,
    })
    expect(model.headline).toContain('待确认')
    expect(model.headline).toContain('unknown')
    expect(model.headline).not.toContain('已决定')
    expect(model.showDecided).toBe(false)
  })
})

describe('rule 4: withdrawal — the card holds no authority of its own', () => {
  it('after unmount and re-mount with the same backend facts, nothing carries over: still 待审批/待确认, never 已决定', async () => {
    const transport = new FakeApprovalTransport({ decide: () => ({ outcome: 'unknown', reason: 'lost' }) })
    const element = <PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />
    const first = await mount(element)
    await click(first, 'allow-once')
    expect(cardText(first)).not.toContain('已决定')
    await act(async () => { roots[roots.length - 1]?.unmount() })
    const freshTransport = new FakeApprovalTransport({})
    const second = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={freshTransport} />)
    expect(cardText(second)).not.toContain('已决定')
    expect(freshTransport.calls).toEqual([])
  })
})

describe('rule 5: refusal codes render as human sentences (FR-09)', () => {
  it('the invalid reason names the operation category, target and limiting layer without leaking arguments', async () => {
    const ceiling = openView({
      status: 'invalid',
      refusal: { code: 'POLICY_CEILING_VIOLATION', message: 'rm -rf /home/user/.ssh --token=abc' },
    })
    const transport = new FakeApprovalTransport({})
    const container = await mount(<PermissionsApprovalCard view={ceiling} location={sessionLocation} transport={transport} />)
    const text = cardText(container)
    expect(text).toContain('POLICY_CEILING_VIOLATION')
    expect(text).toContain('写入文件')      // operation category
    expect(text).toContain('组织上限')     // limiting layer
    expect(text).not.toContain('rm -rf')   // the refusal message never carries raw text through
    expect(text).not.toContain('token=abc')
  })
})

describe('a11y (ux.md 文案和可访问性)', () => {
  it('the card is an ARIA group with labelled focusable actions; disabled actions announce a text reason', async () => {
    const transport = new FakeApprovalTransport({ decide: () => ({ outcome: 'unknown', reason: 'lost' }) })
    const container = await mount(<PermissionsApprovalCard view={openView()} location={sessionLocation} transport={transport} />)
    const card = cardOf(container)
    expect(card.getAttribute('role')).toBe('group')
    expect(card.getAttribute('aria-label')).toBe('待审批操作')
    const allow = card.querySelector('[data-action="allow-once"]') as HTMLButtonElement
    expect(allow.tagName).toBe('BUTTON')
    expect(allow.getAttribute('aria-label')).toBe('允许一次')
    expect(card.querySelector('[data-action="allow-bounded"]')?.getAttribute('aria-label')).toBe('允许受限范围')
    expect(card.querySelector('[data-action="deny"]')?.getAttribute('aria-label')).toBe('拒绝')
    expect(card.querySelector('[data-testid="approval-headline"]')?.getAttribute('aria-live')).toBe('polite')
    await click(container, 'allow-once')
    const disabledAllow = card.querySelector('[data-action="allow-once"]') as HTMLButtonElement
    expect(disabledAllow.getAttribute('aria-disabled')).toBe('true')
    const describedBy = disabledAllow.getAttribute('aria-describedby')
    expect(describedBy).toBeTruthy()
    expect(card.querySelector(`#${describedBy}`)?.textContent?.trim().length).toBeGreaterThan(0)
    await act(async () => { disabledAllow.focus() }) // aria-disabled keeps keyboard access
    expect(container.ownerDocument.activeElement).toBe(disabledAllow)
  })

  it('the bounded action offers only scopes the backend made selectable', async () => {
    const onceOnly = openView({ display: { ...openView().display, selectableScopes: [{ kind: 'once' }] } })
    const transport = new FakeApprovalTransport({})
    const container = await mount(<PermissionsApprovalCard view={onceOnly} location={sessionLocation} transport={transport} />)
    const bounded = cardOf(container).querySelector('[data-action="allow-bounded"]') as HTMLButtonElement
    expect(bounded.getAttribute('aria-disabled')).toBe('true')
    await click(container, 'allow-bounded')
    expect(transport.calls).toEqual([])
  })
})
