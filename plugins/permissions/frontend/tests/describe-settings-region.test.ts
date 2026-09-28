// T015 red-first: the 「权限与审批」 Settings region driven by a real
// `permissions.policy.describe` round-trip through the injected transport
// (fake transport only — no network). Guarantees kept from T011: absent
// provider ⇒ no registration; provider error ⇒ local alert; ceiling rows
// read-only with widening always refused POLICY_CEILING_VIOLATION and no
// local write; needsReview items are never auto-allowed.
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../packages/workbench/src/model'
import {
  PERMISSIONS_SETTINGS_SECTION_ID,
  createPermissionsSettingsRegion, permissionsRuleSources, resolvePermissionsRegionState,
} from '../src/settings-region'
import {
  approvalsSource, describePayload, FakeDescribeTransport, readyPayload,
} from './settings-fixtures'
import { decodeApprovalPayload } from '../src/contract'
import { approvalPayload, settledPayload } from './settings-fixtures'

function host() {
  const lifetime = new OwnedResources()
  const scope = new OwnedResources()
  const model = createWorkbench(lifetime)
  return {
    scope,
    sections: () => model.sections.getSnapshot().map(s => s.id),
    host: model.composition.forScope(scope),
  }
}

describe('the region state is a describe round-trip through the injected transport', () => {
  it('no-provider answer ⇒ the section is never registered (no broken placeholder)', async () => {
    const { sections, host: h } = host()
    const region = await createPermissionsSettingsRegion({ host: h, transport: new FakeDescribeTransport([{ status: 'no-provider' }]) })
    expect(region.registered).toBe(false)
    expect(sections()).toEqual([])
  })

  it('provider error ⇒ local alert state, never the uninstalled branch', async () => {
    const { sections, host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h,
      transport: new FakeDescribeTransport([{ status: 'error', code: 'POLICY_SCOPE_UNVERIFIED', message: '策略读取未能确认来源' }]),
    })
    expect(region.registered).toBe(true)
    expect(sections()).toEqual([PERMISSIONS_SETTINGS_SECTION_ID])
    const state = region.getSnapshot().state
    expect(state.kind).toBe('provider-error')
    if (state.kind === 'provider-error') expect(state.code).toBe('POLICY_SCOPE_UNVERIFIED')
  })

  it('a transport that rejects is a provider error, not a crash and not an absence', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h,
      transport: { describe: () => Promise.reject(new Error('wire down')) },
    })
    expect(region.getSnapshot().state.kind).toBe('provider-error')
  })

  it('ok payload ⇒ ready facts decoded strictly from the closed describe shape', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h,
      transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
      approvalFacts: approvalsSource([approvalPayload('approval_a'), settledPayload('approval_b')]),
    })
    const state = region.getSnapshot().state
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw new Error('unreachable')
    expect(state.facts.ready).toBe(true)
    expect(state.facts.ceilings.map(c => c.policyId)).toEqual(['org-ceiling'])
    expect(state.facts.intents.map(i => i.intentId)).toEqual(['legacy-profile:p1'])
    expect(state.facts.approvals.map(v => v.approvalId)).toEqual(['approval_a', 'approval_b'])
  })

  it('a payload violating the closed shape fails to a local alert — partial facts are never rendered', async () => {
    const { host: h } = host()
    const forged = { ...describePayload(), grantsExecution: true }
    const region = await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: forged }]),
    })
    expect(region.getSnapshot().state.kind).toBe('provider-error')
    expect(JSON.stringify(region.getSnapshot().state)).not.toContain('grantsExecution')
  })

  it('the describe call carries the exact optional param names through the transport', async () => {
    const { host: h } = host()
    const transport = new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }])
    await createPermissionsSettingsRegion({ host: h, transport, describeParams: { principal: 'user:u1', scope: 'project' } })
    expect(transport.calls).toEqual([{ principal: 'user:u1', scope: 'project' }])
  })

  it('refresh() performs a fresh round-trip instead of trusting cached state', async () => {
    const { sections, host: h } = host()
    const transport = new FakeDescribeTransport([
      { status: 'ok', payload: readyPayload() },
      { status: 'no-provider' },
    ])
    const region = await createPermissionsSettingsRegion({ host: h, transport })
    expect(sections()).toEqual([PERMISSIONS_SETTINGS_SECTION_ID])
    await region.refresh()
    expect(transport.calls.length).toBe(2)
    expect(sections()).toEqual([])
    expect(region.getSnapshot().state.kind).toBe('absent')
  })

  it('ready:false from the backend renders an unproven state, never an installation claim', async () => {
    const state = await resolvePermissionsRegionState(
      new FakeDescribeTransport([{ status: 'ok', payload: describePayload({ ready: false }) }]),
    )
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw new Error('unreachable')
    expect(state.facts.ready).toBe(false)
  })
})

describe('describe-driven facts keep the T011 guarantees', () => {
  it('a widening attempt is refused with the stable code and no state changes', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
    })
    const before = JSON.stringify(region.getSnapshot().state)
    const outcome = region.attemptCeilingWidening({ policyId: 'org-ceiling', kind: 'entry' } as never)
    expect(outcome.status).toBe('refused')
    expect(outcome.code).toBe('POLICY_CEILING_VIOLATION')
    expect(JSON.stringify(region.getSnapshot().state)).toBe(before)
    expect(region.getSnapshot().lastCeilingOutcome).toBe(outcome)
  })

  it('an unverified-source ceiling is modelled as non-enforceable, never trusted', async () => {
    const state = await resolvePermissionsRegionState(new FakeDescribeTransport([{
      status: 'ok', payload: describePayload({ ceilings: [{
        policyId: 'org-ceiling', scope: 'admin', revision: 3, source: 'unverified', signed: false,
        maximumExposure: 'read', effectiveFrom: '2026-01-01T00:00:00+00:00',
        hardDenies: [], requireApproval: [],
      }] }),
    }]))
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw new Error('unreachable')
    expect(state.facts.untrustedCeilings).toBe(1)
  })

  it('needsReview items carry their reason into the facts and the region offers no path to allow them', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h,
      transport: new FakeDescribeTransport([{
        status: 'ok', payload: describePayload({ needsReview: [{ source: 'legacy-profile:p1', index: 2, reason: '旧规则语义无法核验' }] }),
      }]),
    })
    const state = region.getSnapshot().state
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw new Error('unreachable')
    expect(state.facts.needsReview).toEqual([{ source: 'legacy-profile:p1', index: 2, reason: '旧规则语义无法核验' }])
    // no method on the region could release a review item: the surface is read + refuse only
    const surface = Object.keys(region)
    expect(surface.filter(k => /allow|approve|resolve|clear|write|update|delete/i.test(k))).toEqual([])
    const before = JSON.stringify(state)
    region.attemptCeilingWidening({ policyId: 'org-ceiling' })
    expect(JSON.stringify(region.getSnapshot().state)).toBe(before)
  })

  it('rule sources are derived from the describe facts, not typed in', async () => {
    const state = await resolvePermissionsRegionState(
      new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
      approvalsSource([approvalPayload('approval_a')]),
    )
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw new Error('unreachable')
    const sources = permissionsRuleSources(state.facts)
    expect(sources.some(s => s.includes('org-ceiling@3'))).toBe(true)
    expect(sources.some(s => s.includes('legacy-profile:p1'))).toBe(true)
    expect(sources.some(s => s.includes('Profile 意图 + 组织上限'))).toBe(true)
  })

  it('approval-history rows still pass the whitelist decode: forged authority keys are stripped, malformed counted', async () => {
    const forged = {
      ...approvalPayload('a_forged'), grantsExecution: true, allowAll: true, apiKey: 'sk-live',
    }
    const malformed = { ...approvalPayload('a_bad'), version: 'one' }
    const state = await resolvePermissionsRegionState(
      new FakeDescribeTransport([{ status: 'ok', payload: describePayload({ ceilings: [], intents: [] }) }]),
      approvalsSource([forged, malformed, approvalPayload('a_real')]),
    )
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw new Error('unreachable')
    const ids = state.facts.approvals.map(v => v.approvalId)
    expect(ids).toContain('a_real')
    expect(ids).not.toContain('a_bad')
    expect(state.facts.undecodableApprovals).toBe(1)
    expect(JSON.stringify(state.facts)).not.toContain('sk-live')
    expect(JSON.stringify(state.facts)).not.toContain('grantsExecution')
    expect(decodeApprovalPayload(approvalPayload('x'))).not.toBeNull()
  })
})
