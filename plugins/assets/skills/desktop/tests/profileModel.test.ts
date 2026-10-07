/**
 * Model-level FR07 tests for the Profile Skill section (second-round review,
 * MINOR-6): the approval-proof wall lives in `profileModel`, not only in the
 * button visibility of `profileSection`. A draft revision may only exist
 * when the target's approval state was PROVEN from the loaded
 * `skills.revisions` list — either it was already approved, or the explicit
 * act approved it first. With no proof (options unloaded, or the revision
 * absent from the list) the model refuses with the typed `switchRefusal`
 * state and produces no draft at all.
 */
import { describe, expect, it } from 'vitest'
import { createProfileSkillsModel } from '../src/profileModel'
import {
  fakeProfileHost, fakeProfileSkillsGateway, profileRelation, profileRevisionOption,
} from './profile-fakes'

function harness(gatewayOptions = {}, hostOptions = {}) {
  const built = fakeProfileSkillsGateway(gatewayOptions)
  const hostFake = fakeProfileHost(hostOptions)
  return {
    model: createProfileSkillsModel(built.gateway, hostFake.host),
    calls: built.calls,
    hostCalls: hostFake.calls,
  }
}
const pinned = { relations: [profileRelation('demo', { decision: 'enable', revision: 1 })] }

describe('FR07 at the model seam: no draft revision without an approved-version proof', () => {
  it('confirmSwitch while the version list is still loading (options === null) drafts NOTHING', async () => {
    const { model, calls, hostCalls } = harness(
      { revisions: [profileRevisionOption(1, true), profileRevisionOption(3, false)] }, pinned)
    await model.refresh()
    // Deliberately NOT awaiting openSwitcher: the switcher state exists with
    // `revisions === null` — the exact shape the section hides its button
    // from, but which any model caller (or a view regression) can reach.
    void model.openSwitcher('demo')
    expect(model.getSnapshot().switcher).toEqual({ assetId: 'demo', revisions: null })

    await model.confirmSwitch('demo', 3)

    const snap = model.getSnapshot()
    // No unapproved repoint draft, typed refusal instead, and no silent
    // approval was smuggled in either.
    expect(snap.draft['demo']).toBeUndefined()
    expect(snap.switchRefusal).not.toBeNull()
    expect(snap.switchRefusal?.code).toBe('SWITCH_APPROVAL_UNPROVEN')
    expect(snap.switchRefusal?.assetId).toBe('demo')
    expect(snap.switchRefusal?.toRevision).toBe(3)
    expect(calls.filter(call => call.method === 'approveRevision')).toHaveLength(0)
    // The stored binding is untouched and nothing was ever saved.
    expect(snap.profile?.relations).toEqual(pinned.relations)
    expect(hostCalls.filter(call => call.method === 'saveRelations')).toHaveLength(0)
  })

  it('confirmSwitch to a revision absent from the loaded list refuses; a proven target still repoints (control)', async () => {
    const { model, calls } = harness(
      { revisions: [profileRevisionOption(1, true), profileRevisionOption(3, false)] }, pinned)
    await model.refresh()
    await model.openSwitcher('demo')

    // r99 is not in the list at all: no approval fact exists for it.
    await model.confirmSwitch('demo', 99)
    expect(model.getSnapshot().draft['demo']).toBeUndefined()
    expect(model.getSnapshot().switchRefusal?.code).toBe('SWITCH_APPROVAL_UNPROVEN')
    expect(model.getSnapshot().switchRefusal?.toRevision).toBe(99)
    expect(calls.filter(call => call.method === 'approveRevision')).toHaveLength(0)

    // Control — the refusal is about the missing proof, not a dead path:
    // an approved target from the loaded list drafts normally.
    await model.confirmSwitch('demo', 1)
    expect(model.getSnapshot().draft['demo']).toEqual({ decision: 'enable', revision: 1 })
    expect(model.getSnapshot().switchRefusal).toBeNull()

    // And an unapproved-but-LOADED target keeps the explicit approve-first
    // sequence (the draft only appears after the approval call).
    await model.confirmSwitch('demo', 3)
    const approveCalls = calls.filter(call => call.method === 'approveRevision')
    expect(approveCalls).toHaveLength(1)
    expect(model.getSnapshot().draft['demo']).toEqual({ decision: 'enable', revision: 3 })
  })

  it('a switcher opened for another asset supplies no proof for this one', async () => {
    const { model } = harness({ revisions: [profileRevisionOption(2, true)] })
    await model.refresh()
    await model.openSwitcher('other')
    // confirmSwitch('demo', …) while the only loaded list belongs to 'other'
    // — options resolve to null, refusal, no draft.
    await model.confirmSwitch('demo', 2)
    expect(model.getSnapshot().draft['demo']).toBeUndefined()
    expect(model.getSnapshot().switchRefusal?.code).toBe('SWITCH_APPROVAL_UNPROVEN')
  })
})
