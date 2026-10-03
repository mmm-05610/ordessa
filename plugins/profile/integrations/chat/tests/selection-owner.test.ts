/**
 * T010-02 ownership gates: the selection store holds NO business write state —
 * picks, registration facts and confirmations are owner operations (A1
 * single-writer), and the store is a projector over owner answers. These
 * tests reach BEHIND the store (store.owner) to prove where the state lives.
 */
import { describe, expect, it } from 'vitest'

import { createLocalAgentOwnerPort } from '@ordessa/agent-contracts'
import { ProfileSelectionStore } from '../src/selection'
import type { ProfileSelection } from '@ordessa/plugin-profile-api'

const A: ProfileSelection = { harnessId: 'h1', profileId: 'a', displayName: 'A' }
const B: ProfileSelection = { harnessId: 'h1', profileId: 'b', displayName: 'B' }

describe('selection store ownership (T010-02)', () => {
  it('keeps picks in the owner, not in the store: owner fields change under the same projection', () => {
    const store = new ProfileSelectionStore()
    store.select('session:S1', A)
    // the state lives in the owner...
    const ownerView = store.owner.readConfigSync('session:S1')
    expect(ownerView.resolved.selection).toBe(A)
    expect(ownerView.fields.selection).toBe('known')
    // ...and the store projects it: a write made straight through the owner
    // face shows up in the store's reads (the store cannot hold a divergent copy)
    store.owner.submitConfigOperationSync('session:S1', { selection: B })
    expect(store.peek('session:S1')).toBe(B)
  })

  it('counts a same-pick re-select as a NEW owner operation (T010-04)', () => {
    const store = new ProfileSelectionStore()
    store.select('draft:1', A)
    expect(store.owner.readConfigSync('draft:1').revision).toBe(1)
    store.select('draft:1', A) // the very same pick again
    expect(store.owner.readConfigSync('draft:1').revision).toBe(2)
  })

  it('records registration facts as owner fields and drops stale acknowledgements', () => {
    const store = new ProfileSelectionStore()
    store.select('session:S1', A)
    store.select('session:S1', B) // a newer pick owns the key
    store.markRegistered('session:S1', A) // stale ack for the old pick
    expect(store.isRegistered('session:S1', A)).toBe(false)
    expect(store.owner.readConfigSync('session:S1').resolved.registered).not.toBe(true)
    store.markRegistered('session:S1', B)
    expect(store.isRegistered('session:S1', B)).toBe(true)
    expect(store.owner.readConfigSync('session:S1').resolved.registered).toBe(true)
  })

  it('counterexample: confirmations live in the owner and survive forget; only draft confirmations clear', () => {
    const owner = createLocalAgentOwnerPort({ ownerRegistry: new Set() })
    const store = new ProfileSelectionStore({ owner })
    store.select('draft:1', A)
    store.select('session:S1', A)
    // record confirmations the way applyOnSubmit does (owner operations)
    owner.submitConfigOperationSync('draft:1', { lastConfirmed: A })
    owner.submitConfigOperationSync('session:S1', { lastConfirmed: A })
    store.forget('draft:1') // UI teardown drops the pick only
    expect(owner.readConfigSync('draft:1').resolved.lastConfirmed).toBe(A)
    expect(store.peek('draft:1')).toBeNull()
    store.clearDraftConfirmations()
    expect(owner.readConfigSync('draft:1').resolved.lastConfirmed).toBeUndefined()
    expect(owner.readConfigSync('session:S1').resolved.lastConfirmed).toBe(A) // untouched
    expect(store.currentLabel('session:S1')).toBe('A') // projects the confirmation
  })

  it('counterexample: the store cannot silently fork state — a second store on one owner sees one truth', () => {
    const owner = createLocalAgentOwnerPort({ ownerRegistry: new Set() })
    const storeA = new ProfileSelectionStore({ owner })
    const storeB = new ProfileSelectionStore({ owner })
    storeA.select('session:S1', A)
    expect(storeB.peek('session:S1')).toBe(A) // one writer, two projections
    storeB.markRegistered('session:S1', A)
    expect(storeA.isRegistered('session:S1', A)).toBe(true)
  })
})
