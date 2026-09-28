// T011 + T015: the Permissions Settings region registers through the REAL
// Workbench composition seam
// (packages/workbench/src/model.ts:124 -> composition.forScope(scope).addSettingsSection),
// asserted against the actual registry snapshot rather than a stand-in, and
// every policy fact now arrives through a `permissions.policy.describe`
// round-trip on the injected fake transport (no network, no stubbed backend).
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createWorkbench } from '../../../../packages/workbench/src/model'
import {
  PERMISSIONS_SETTINGS_SECTION_ID, PERMISSIONS_SETTINGS_SECTION_TITLE,
  createPermissionsSettingsRegion, filterApprovalHistory,
  resolvePermissionsRegionState,
} from '../src/settings-region'
import {
  approvalsSource, approvalPayload, ceilingAbsentPayload, describePayload, errorTransport,
  FakeDescribeTransport, noProviderTransport, readyPayload, settledPayload,
} from './settings-fixtures'
import { decodeApprovalPayload } from '../src/contract'

function host() {
  const lifetime = new OwnedResources()
  const scope = new OwnedResources()
  const model = createWorkbench(lifetime)
  return {
    scope,
    sections: () => model.sections.getSnapshot().map(s => s.id),
    sectionRecords: () => model.sections.getSnapshot(),
    host: model.composition.forScope(scope),
  }
}

describe('the region registers through the real addSettingsSection seam (FR-08)', () => {
  it('absent provider ⇒ the section is never registered — no broken placeholder', async () => {
    const { sections, host: h } = host()
    const region = await createPermissionsSettingsRegion({ host: h, transport: noProviderTransport() })
    expect(region.registered).toBe(false)
    expect(sections()).toEqual([])
  })

  it('present-but-failing provider ⇒ a local error registration, never an absence', async () => {
    const { sections, host: h } = host()
    const region = await createPermissionsSettingsRegion({ host: h, transport: errorTransport() })
    expect(region.registered).toBe(true)
    expect(sections()).toEqual([PERMISSIONS_SETTINGS_SECTION_ID])
    expect(region.getSnapshot().state.kind).toBe('provider-error')
  })

  it('ready facts ⇒ the 「权限与审批」 section is in the real registry snapshot', async () => {
    const { sections, sectionRecords, host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
    })
    expect(sections()).toEqual([PERMISSIONS_SETTINGS_SECTION_ID])
    const record = sectionRecords()[0]
    expect(record.title).toBe(PERMISSIONS_SETTINGS_SECTION_TITLE)
    expect(PERMISSIONS_SETTINGS_SECTION_TITLE).toBe('权限与审批')
    expect(typeof record.component).toBe('function')
    expect(region.getSnapshot().state.kind).toBe('ready')
  })

  it('closing the owning scope withdraws the contribution (registry-owned lifecycle)', async () => {
    const { sections, scope, host: h } = host()
    await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
    })
    expect(sections()).toEqual([PERMISSIONS_SETTINGS_SECTION_ID])
    scope.dispose()
    expect(sections()).toEqual([])
  })

  it('hide drops the contribution; show re-reads the transport instead of trusting cached state', async () => {
    const transport = new FakeDescribeTransport([
      { status: 'ok', payload: readyPayload() },
      { status: 'no-provider' },
      { status: 'ok', payload: readyPayload() },
    ])
    const { sections, host: h } = host()
    const region = await createPermissionsSettingsRegion({ host: h, transport })
    region.hide()
    expect(sections()).toEqual([])
    await region.show()
    expect(sections()).toEqual([])
    await region.show()
    expect(sections()).toEqual([PERMISSIONS_SETTINGS_SECTION_ID])
    expect(transport.calls.length).toBe(3)
  })
})

describe('the organization ceiling is read-only (ux.md §Settings, FR-08)', () => {
  it('a widening attempt is refused with the stable code, whatever the region state', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
    })
    const before = JSON.stringify(region.getSnapshot().state)
    const outcome = region.attemptCeilingWidening({ policyId: 'org-ceiling', kind: 'entry' } as never)
    expect(outcome.status).toBe('refused')
    expect(outcome.code).toBe('POLICY_CEILING_VIOLATION')
    expect(outcome.message).toContain('POLICY_CEILING_VIOLATION')
    // never a silent write: the rendered facts are byte-identical after the attempt
    expect(JSON.stringify(region.getSnapshot().state)).toBe(before)
    // and the refusal is surfaced as the last outcome, not swallowed
    expect(region.getSnapshot().lastCeilingOutcome).toBe(outcome)
  })

  it('the region exposes no ceiling-write path at all', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
    })
    const surface = Object.keys(region)
    expect(surface.filter(k => /write|store|update|delete/i.test(k))).toEqual([])
  })

  it('an untrusted ceiling record is never summarized as a bound, and absence stays modelled', async () => {
    const state = await resolvePermissionsRegionState(new FakeDescribeTransport([{
      status: 'ok', payload: describePayload({
        ceilings: [{
          policyId: 'org-ceiling', scope: 'admin', revision: 3, source: 'unverified', signed: false,
          maximumExposure: 'read', effectiveFrom: '2026-01-01T00:00:00+00:00',
          hardDenies: [], requireApproval: [],
        }],
      }),
    }]))
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw Error('unreachable')
    expect(state.facts.untrustedCeilings).toBe(1)
    const empty = await resolvePermissionsRegionState(
      new FakeDescribeTransport([{ status: 'ok', payload: ceilingAbsentPayload() }]),
    )
    expect(empty.kind === 'ready' && empty.facts.untrustedCeilings).toBe(0)
    expect(empty.kind === 'ready' && empty.facts.ceilingCount).toBe(0)
  })
})

describe('approval history filters backend facts only (FR-08/FR-09)', () => {
  const views = [
    decodeApprovalPayload(approvalPayload('a_open_s1'))!,
    decodeApprovalPayload(settledPayload('a_deny_s2', 'deny'))!,
    decodeApprovalPayload(settledPayload('a_allow_s2', 'allow'))!,
  ]

  it('filters by status, decision and session without inventing rows', () => {
    expect(filterApprovalHistory(views, {}).map(v => v.approvalId))
      .toEqual(['a_open_s1', 'a_deny_s2', 'a_allow_s2'])
    expect(filterApprovalHistory(views, { status: 'settled' }).map(v => v.approvalId))
      .toEqual(['a_deny_s2', 'a_allow_s2'])
    expect(filterApprovalHistory(views, { decision: 'deny' }).map(v => v.approvalId)).toEqual(['a_deny_s2'])
    expect(filterApprovalHistory(views, { sessionId: 's2' }).map(v => v.approvalId)).toEqual(['a_deny_s2', 'a_allow_s2'])
    // a filter naming an unknown session returns nothing — filtering never fabricates
    expect(filterApprovalHistory(views, { sessionId: 's-nope' })).toEqual([])
  })

  it('a malformed or forged history payload is dropped or stripped before the region can render it', async () => {
    const forged = {
      ...approvalPayload('a_forged'),
      grantsExecution: true, allowAll: true,
      toolArguments: '{"cmd":"rm -rf /"}', apiKey: 'sk-live',
    }
    const malformed = { ...approvalPayload('a_bad'), version: 'one' }
    const state = await resolvePermissionsRegionState(
      new FakeDescribeTransport([{ status: 'ok', payload: describePayload({ ceilings: [], intents: [] }) }]),
      approvalsSource([forged, malformed, approvalPayload('a_real')]),
    )
    expect(state.kind).toBe('ready')
    if (state.kind !== 'ready') throw Error('unreachable')
    // only whitelist-shaped payloads survive; the malformed one is counted, not shown
    const ids = state.facts.approvals.map(v => v.approvalId)
    expect(ids).toContain('a_real')
    expect(ids).not.toContain('a_bad')
    expect(state.facts.undecodableApprovals).toBe(1)
    // a forged extra key is stripped by the whitelist decode and never rendered
    expect(ids).toContain('a_forged')
    expect(state.facts.approvals.find(v => v.approvalId === 'a_forged')!.status).toBe('open')
    expect(JSON.stringify(state.facts)).not.toContain('sk-live')
    expect(JSON.stringify(state.facts)).not.toContain('rm -rf')
    expect(JSON.stringify(state.facts)).not.toContain('grantsExecution')
  })

  it('a local UI state write cannot make the region claim an authority it was not given', async () => {
    const { host: h } = host()
    const region = await createPermissionsSettingsRegion({
      host: h, transport: new FakeDescribeTransport([{ status: 'ok', payload: readyPayload() }]),
      approvalFacts: approvalsSource([approvalPayload('approval_a'), settledPayload('approval_b')]),
    })
    const before = JSON.stringify(region.getSnapshot().state)
    // the ONLY writable local state is the display filter; a forged object with
    // extra authority fields selects nothing and adds nothing
    region.setHistoryFilter({ status: 'settled', decision: 'allow', sessionId: 'ghost', grantsExecution: true } as never)
    expect(region.getSnapshot().history).toEqual([])
    region.setHistoryFilter({ sessionId: 's1' })
    expect(region.getSnapshot().history.map(v => v.approvalId)).toEqual(['approval_a'])
    // backend facts untouched by any local write; no transport call was made for filtering
    expect(JSON.stringify(region.getSnapshot().state)).toBe(before)
    expect(region.getSnapshot().state.kind).toBe('ready')
    // and the widening refusal is unconditional after local state manipulation
    expect(region.attemptCeilingWidening({ policyId: 'org-ceiling', kind: 'exposure' } as never).code)
      .toBe('POLICY_CEILING_VIOLATION')
  })
})
