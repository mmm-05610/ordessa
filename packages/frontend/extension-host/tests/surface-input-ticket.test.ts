// T009-06 (verification half) — surface input ticket binding: target/epoch/lease.
//
// Contract: specs/026-open-environment-migration/contracts/frontend.md §F1:
//   SurfaceAPI: registerSurface(spec)/attach(ref)/detach(handle)/write(inputTicket)/observe(cursor,credit)
//   spec declares source, execution domain, schema version, budget and
//   raw/reliable capability; unknown types degrade bounded; an unauthorized
//   read-only surface cannot answer control requests.
// orders/009.md T009-06: 编辑与 surface input ticket 绑定 target/epoch/lease；
// 旧 epoch ticket 被拒 StaleGenerationError 类语义.
//
// HONEST CURRENT STATE (recon 2026-10-03, this worktree):
//   - extension-host is a thin compatibility shell re-exporting
//     @ordessa/extension-runtime/host (its package description, T008-01).
//   - Neither the shell, the runtime host, workbench, connections,
//     native-bridge nor server-bridge exposes a surface API: no
//     registerSurface/attach/detach/write(inputTicket)/observe(cursor,credit).
//   - No input-ticket type carrying target/epoch/lease exists anywhere in the
//     frontend packages. The frozen F5 contract (T008-11) declares state,
//     selectors, projections, queries, tasks, editing, UI storage,
//     interactions and display only — no surface/input shape.
//   - Therefore structural assertions (three-element ticket binding, stale
//     epoch ticket refused on write) cannot be written against real code
//     without inventing a fake API.
//
// BLOCKED-on-T009-implementation: this file pins the ABSENCE as a tripwire.
// When the real SurfaceAPI lands, these assertions fail loudly and MUST be
// replaced by structural target/epoch/lease assertions — never weakened to
// stay green.
import { describe, expect, it } from 'vitest'
import { f5 } from '@extensions/ordessa.contracts/contract.js'
import * as host from '../src/index'

// Compile-time half of the tripwire: this annotation only typechecks while no
// surface entry exists. Landing registerSurface/attach/detach/write/observe
// makes SurfaceEntry non-never and this line a type error.
type SurfaceEntry = Extract<keyof typeof host, 'registerSurface' | 'attach' | 'detach' | 'write' | 'observe'>
const surfaceEntryAbsent: [SurfaceEntry] extends [never] ? true : false = true

describe('T009-06 surface input ticket — current state pin (BLOCKED-on-T009-implementation)', () => {
  it('the extension-host public entry is live but exposes no SurfaceAPI', () => {
    // Prove the import is the real carrier, so the absence checks are not vacuous.
    expect(typeof host.runtime).toBe('function')
    expect(typeof host.Contributions).toBe('function')
    expect(surfaceEntryAbsent).toBe(true)
    for (const name of ['registerSurface', 'attach', 'detach', 'write', 'observe']) {
      expect(Object.keys(host)).not.toContain(name)
    }
    expect(Object.keys(host).filter(name => /surface|ticket/i.test(name))).toEqual([])
  })

  it('no input-ticket target/epoch/lease module is reachable from the host entry', () => {
    expect(Object.keys(host).filter(name => /input|ticket|lease|epoch/i.test(name))).toEqual([])
  })

  it('the F5 stale-generation refusal vocabulary exists and is the class a stale-epoch ticket refusal must use', () => {
    const error = new f5.StaleGenerationError('stale ticket epoch', { ticket: 't-1', epoch: 1 })
    expect(error).toBeInstanceOf(Error)
    expect(error.code).toBe('F5_STALE_GENERATION')
    expect(error.details).toEqual({ ticket: 't-1', epoch: 1 })
  })
})
