/**
 * T008-08 gates: one admission fence freezes dispatch, required-borrow and
 * batch-publish together; refusal/timeout restores admission exactly; the
 * cross-await barrier refuses late required relations (F2 §前端停用原子门).
 */
import { describe, expect, it } from 'vitest'

import { PreflightGate } from '../src/preflight'
import { StaleGenerationError } from '@extensions/ordessa.contracts/contract.js'

describe('F2 preflight gate', () => {
  it('freeze cuts ALL THREE admission kinds on one fence', () => {
    const gate = new PreflightGate()
    gate.admit('owner', 'dispatch') // live before freeze
    gate.releaseAdmission('owner', 'dispatch')
    const handle = gate.freeze('owner', 'dep-rev-1', ['work-1'])
    for (const kind of ['dispatch', 'required-borrow', 'batch-publish'] as const) {
      expect(() => gate.admit('owner', kind)).toThrow(StaleGenerationError)
    }
    expect(gate.isFrozen('owner')).toBe(true)
    expect(handle.record.committedWork).toEqual(['work-1'])
    handle.drain()
  })

  it('refusal restores admission exactly (no half-disabled UI)', () => {
    const gate = new PreflightGate()
    const handle = gate.freeze('owner', 'dep-rev-1', [])
    const outcome = handle.restore('preflight refused: pending work')
    expect(outcome).toEqual({ kind: 'refused', reason: 'preflight refused: pending work', restored: true })
    // admission is back: new dispatch passes again
    expect(() => gate.admit('owner', 'dispatch')).not.toThrow()
    gate.releaseAdmission('owner', 'dispatch')
  })

  it('timeout restores like refusal and is typed separately', () => {
    const gate = new PreflightGate()
    const handle = gate.freeze('owner', 'dep-rev-1', [])
    expect(handle.restore('timeout')).toEqual({ kind: 'timeout', restored: true })
    expect(gate.isFrozen('owner')).toBe(false)
  })

  it('counterexample: a late required relation after the no-pending judgement is refused', () => {
    const gate = new PreflightGate()
    const handle = gate.freeze('owner', 'dep-rev-1', [])
    // the no-pending judgement passes at barrier B; a cross-await race then
    // tries to add a required relation — the barrier refuses it
    expect(() => gate.requireRelation('owner', handle.barrier, 'late-required'))
      .not.toThrow() // still inside the SAME freeze window: allowed
    handle.drain()
    expect(() => gate.requireRelation('owner', handle.barrier, 'late-required'))
      .toThrow(StaleGenerationError) // after drain: the freeze cannot reopen
  })

  it('counterexample: a stale barrier token never reopens a freeze', () => {
    const gate = new PreflightGate()
    const first = gate.freeze('owner', 'dep-rev-1', [])
    first.drain()
    const second = gate.freeze('owner', 'dep-rev-2', [])
    expect(() => gate.requireRelation('owner', first.barrier, 'stale'))
      .toThrow(StaleGenerationError) // old barrier ≠ current freeze
    second.drain()
  })

  it('double freeze of one owner is refused', () => {
    const gate = new PreflightGate()
    const handle = gate.freeze('owner', 'dep-rev-1', [])
    expect(() => gate.freeze('owner', 'dep-rev-2', [])).toThrow(StaleGenerationError)
    handle.drain()
  })
})
