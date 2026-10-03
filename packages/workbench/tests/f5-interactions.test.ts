/**
 * T008-18/19 gates: interaction handles are stable-id updating (no banner
 * per keystroke), cancellation never claims "stopped", revoked scopes
 * refuse late updates, and context keys never carry secrets or grant
 * execution rights (F5 §7).
 */
import { describe, expect, it, vi } from 'vitest'

import { createInteractionService, type InteractionPresenter } from '../src/interactions'
import { ContextKeyRegistry } from '../src/context'

function recordingPresenter() {
  const shown: Array<{ kind: string; view: Record<string, unknown> }> = []
  const dismissed: string[] = []
  const presenter: InteractionPresenter = {
    show(kind, view) { shown.push({ kind, view: { ...view } }) },
    dismiss(id) { dismissed.push(id) },
  }
  return { presenter, shown, dismissed }
}

describe('F5 interactions', () => {
  it('repeat events with a declaration id UPDATE the same handle', () => {
    const { presenter, shown } = recordingPresenter()
    let generation = 1
    const service = createInteractionService({
      presenter, scopeGeneration: () => generation,
    })
    const first = service.notify({ id: 'save', severity: 'info', text: 'saving…' })
    first.update('still saving…')
    const second = service.notify({ id: 'save', severity: 'info', text: 'saving more…' })
    expect(second.id).toBe('save')
    // three presentations, ONE handle id: no banner-per-event
    expect(shown.filter(s => s.view.id === 'save')).toHaveLength(3)
    expect(new Set(shown.map(s => s.view.id)).size).toBe(1)
  })

  it('counterexample: cancel requests project the task cancel and never claim stopped', () => {
    const { presenter, shown } = recordingPresenter()
    const cancel = vi.fn()
    const service = createInteractionService({ presenter, scopeGeneration: () => 1 })
    const handle = service.progress({ id: 'task', text: 'building', cancel })
    handle.requestCancel()
    expect(cancel).toHaveBeenCalledTimes(1) // projection only
    // the visible text never says stopped
    for (const s of shown) {
      expect(String(s.view.text)).not.toMatch(/stopped|已停止|已取消/)
    }
  })

  it('counterexample: a revoked scope refuses late updates', () => {
    const { presenter } = recordingPresenter()
    let generation = 1
    const service = createInteractionService({ presenter, scopeGeneration: () => generation })
    const handle = service.notify({ id: 'late', severity: 'info', text: 'x' })
    generation = 2 // scope revoked
    expect(() => handle.update('too late')).toThrow(/revoked/)
  })

  it('unknown results stay unknown: error texts carry no guesses', () => {
    const { presenter, shown } = recordingPresenter()
    const service = createInteractionService({ presenter, scopeGeneration: () => 1 })
    // callers pass what is known; the service never fabricates a cause
    service.notify({ id: 'err', severity: 'error', text: 'outcome unknown; query before retry' })
    expect(shown.at(-1)!.view.text).not.toMatch(/network|offline|failed because/)
  })

  it('closing a handle dismisses its presentation idempotently', () => {
    const { presenter, dismissed } = recordingPresenter()
    const service = createInteractionService({ presenter, scopeGeneration: () => 1 })
    const handle = service.notify({ severity: 'info', text: 'x' })
    handle.close()
    expect(dismissed).toEqual([handle.id])
    expect(() => handle.update('after close')).toThrow()
  })
})

describe('F5 context keys', () => {
  it('when expressions evaluate availability only and secrets are refused', () => {
    const keys = new ContextKeyRegistry('menu')
    keys.set('view', 'chat')
    keys.set('busy', false)
    expect(keys.evaluate('view == chat')).toBe(true)
    expect(keys.evaluate('view == chat && !busy')).toBe(true)
    expect(keys.evaluate('view == docs || busy')).toBe(false)
    // counterexample: a secret-shaped key is refused outright
    expect(() => keys.set('apiKey', 'sk-x')).toThrow(/secret/)
  })

  it('keys are scope-bound and die with their scope', () => {
    const menu = new ContextKeyRegistry('menu')
    const toolbar = new ContextKeyRegistry('toolbar')
    menu.set('view', 'chat')
    toolbar.set('view', 'docs')
    expect(menu.get('view')).toBe('chat') // no cross-scope leakage
    menu.releaseScope()
    expect(menu.get('view')).toBeNull()
    expect(toolbar.get('view')).toBe('docs') // other scopes untouched
  })
})
