/**
 * T010-05 gates: the native ConfigEvidence chain — known/unset/unknown with
 * snapshot/patch chains, a bounded out-of-order cache, same-revision conflicts
 * blocking capture, identical re-observations never unlocking a pending
 * unknown, and a complete new snapshot clearing the old cache.
 */
import { describe, expect, it } from 'vitest'

import { ConfigEvidenceChain } from '../src/config-evidence'
import { createLocalAgentOwnerPort } from '../src/owner-port'

describe('ConfigEvidence chain (T010-05)', () => {
  it('chains patches onto a snapshot, per-field known/unset/unknown', () => {
    const chain = new ConfigEvidenceChain()
    expect(chain.intake({ kind: 'snapshot', revision: 1, observed: 'native',
      fields: { model: 'known', temp: 'unknown', top: 'unset' } })).toEqual({ status: 'applied', revision: 1 })
    expect(chain.getFields()).toEqual({ model: 'known', temp: 'unknown', top: 'unset' })
    // a patch touches ONLY its listed fields
    expect(chain.intake({ kind: 'patch', revision: 2, fields: { temp: 'known' } }))
      .toEqual({ status: 'applied', revision: 2 })
    expect(chain.getFields()).toEqual({ model: 'known', temp: 'known', top: 'unset' })
    expect(chain.getObserved()).toBe('native')
    expect(chain.captureVerdictAt(1)).toBe('settled')
    expect(chain.captureVerdictAt(3)).toBe('unobserved')
  })

  it('buffers out-of-order frames in a bounded cache and applies them when the gap fills', () => {
    const chain = new ConfigEvidenceChain()
    chain.intake({ kind: 'snapshot', revision: 1, fields: { a: 'known' } })
    expect(chain.intake({ kind: 'patch', revision: 3, fields: { c: 'known' } }))
      .toEqual({ status: 'buffered', revision: 3, buffered: 1 })
    expect(chain.getFields()).toEqual({ a: 'known' }) // not applied yet
    expect(chain.intake({ kind: 'patch', revision: 2, fields: { b: 'known' } }))
      .toEqual({ status: 'applied', revision: 2 }) // gap filled: 2 then 3 drain in order
    expect(chain.getFields()).toEqual({ a: 'known', b: 'known', c: 'known' })
    expect(chain.revision).toBe(3)
  })

  it('counterexample: the out-of-order cache is bounded — overflow refuses the newcomer, never evicts', () => {
    const chain = new ConfigEvidenceChain({ maxBuffered: 2 })
    chain.intake({ kind: 'snapshot', revision: 1, fields: {} })
    expect(chain.intake({ kind: 'patch', revision: 3, fields: {} }).status).toBe('buffered')
    expect(chain.intake({ kind: 'patch', revision: 4, fields: {} }).status).toBe('buffered')
    expect(chain.intake({ kind: 'patch', revision: 5, fields: {} }))
      .toEqual({ status: 'rejected', reason: 'buffer-full' })
  })

  it('counterexample: a same-revision conflict blocks capture and touches no state', () => {
    const chain = new ConfigEvidenceChain()
    chain.intake({ kind: 'snapshot', revision: 1, fields: { a: 'known' } })
    chain.intake({ kind: 'patch', revision: 2, fields: { b: 'known' } })
    expect(chain.intake({ kind: 'patch', revision: 2, fields: { b: 'unset' } }))
      .toEqual({ status: 'conflict', revision: 2 })
    expect(chain.getFields()).toEqual({ a: 'known', b: 'known' }) // untouched
    expect(chain.captureVerdictAt(2)).toBe('conflicting') // capture blocked, fail-closed
    expect(chain.captureVerdictAt(1)).toBe('settled') // other revisions unaffected
  })

  it('counterexample: an identical re-observation is a no-op and never unlocks a pending unknown', () => {
    const chain = new ConfigEvidenceChain()
    chain.intake({ kind: 'snapshot', revision: 1, observed: 'unknown', fields: { model: 'unknown' } })
    expect(chain.intake({ kind: 'snapshot', revision: 1, observed: 'unknown', fields: { model: 'unknown' } }))
      .toEqual({ status: 'duplicate', revision: 1 })
    expect(chain.getFields().model).toBe('unknown') // still unknown: no unlock
    // only a NEW observation may change it
    chain.intake({ kind: 'snapshot', revision: 2, observed: 'native', fields: { model: 'known' } })
    expect(chain.getFields().model).toBe('known')
  })

  it('a complete new snapshot clears the out-of-order cache (buffered frames are obsolete)', () => {
    const chain = new ConfigEvidenceChain()
    chain.intake({ kind: 'snapshot', revision: 1, fields: { a: 'known' } })
    chain.intake({ kind: 'patch', revision: 4, fields: { d: 'known' } }) // buffered (gap)
    expect(chain.intake({ kind: 'snapshot', revision: 6, fields: { f: 'known' } }))
      .toEqual({ status: 'applied', revision: 6 }) // complete: jumps the gap
    expect(chain.getFields()).toEqual({ f: 'known' })
    // the buffered frame is obsolete; a re-send of it can never apply
    expect(chain.intake({ kind: 'patch', revision: 4, fields: { d: 'known' } }))
      .toEqual({ status: 'obsolete', revision: 4 })
  })

  it('rejects malformed frames without touching state', () => {
    const chain = new ConfigEvidenceChain()
    expect(chain.intake({ kind: 'snapshot', revision: 0 }).status).toBe('rejected')
    expect(chain.intake({ kind: 'patch', revision: 1.5 }).status).toBe('rejected')
    expect(chain.intake({ kind: 'snapshot', revision: 1, observed: 'maybe' as 'native' }).status).toBe('rejected')
    expect(chain.intake({ kind: 'snapshot', revision: 1, fields: { a: 'perhaps' as 'known' } }).status).toBe('rejected')
    expect(chain.revision).toBe(0)
  })

  it('owner port intake: only applied frames move the owner evidence fields', () => {
    const port = createLocalAgentOwnerPort({ ownerRegistry: new Set() })
    port.reportEvidenceFrame('chat', { kind: 'snapshot', revision: 1, observed: 'unknown', fields: { model: 'unknown' } })
    port.reportEvidenceFrame('chat', { kind: 'snapshot', revision: 1, observed: 'unknown', fields: { model: 'unknown' } })
    expect(port.readConfigSync('chat').fields.model).toBe('unknown') // duplicate: no unlock
    port.reportEvidenceFrame('chat', { kind: 'patch', revision: 3, fields: { model: 'known' } })
    expect(port.readConfigSync('chat').fields.model).toBe('unknown') // buffered: not applied
    port.reportEvidenceFrame('chat', { kind: 'patch', revision: 2, fields: {} })
    expect(port.readConfigSync('chat').fields.model).toBe('known') // gap filled: applied in order
    expect(port.readConfigSync('chat').observedEvidence).toBe('unknown')
  })
})
