/**
 * T009-08 gates: the Workbench dialog capability reports choices only —
 * cancelled is zero-write, a revoked scope resolves revoked (late callbacks
 * are write-free no-ops), one dialog at a time (never covering window
 * controls), and absent availability is typed unavailable (never a fake
 * choice, never window.confirm).
 */
import { describe, expect, it } from 'vitest'

import { createDialogController, type DialogResult } from '../src/dialog'

describe('F4 dialog controller', () => {
  it('confirm reports the user choice; the dialog itself writes nothing', async () => {
    const controller = createDialogController()
    const pending = controller.confirm({
      operationId: 'op-1', title: '放弃未保存的预设配置？', text: '…', scope: 'profile',
    })
    const view = controller.current()
    expect(view?.operationId).toBe('op-1')
    view!.resolve({ kind: 'confirmed' })
    expect(await pending).toEqual({ kind: 'confirmed' })
    expect(controller.current()).toBeNull() // settled dialogs close
  })

  it('counterexample: cancelled is zero-write and distinct from confirmed', async () => {
    const controller = createDialogController()
    const pending = controller.confirm({ operationId: 'op-2', title: 't', text: 'x', scope: 's' })
    controller.current()!.resolve({ kind: 'cancelled' })
    expect(await pending).toEqual({ kind: 'cancelled' }) // never a bare boolean
  })

  it('counterexample: a revoked scope resolves revoked; late callbacks are no-ops', async () => {
    const controller = createDialogController()
    const pending = controller.confirm({ operationId: 'op-3', title: 't', text: 'x', scope: 'dying' })
    const view = controller.current()
    controller.revokeScope('dying')
    expect(await pending).toEqual({ kind: 'revoked' })
    // the late user click on the dead dialog resolves nothing
    view!.resolve({ kind: 'confirmed' })
    expect(controller.current()).toBeNull()
  })

  it('counterexample: a second dialog is unavailable, never stacked over window controls', async () => {
    const controller = createDialogController()
    void controller.confirm({ operationId: 'op-4', title: 't', text: 'x', scope: 's' })
    const second = await controller.quickPick({
      operationId: 'op-5', title: 'pick', items: [], scope: 's',
    })
    expect(second).toEqual({ kind: 'unavailable' })
  })

  it('absent availability is typed unavailable (no window.confirm fallback)', async () => {
    const controller = createDialogController({ available: false })
    expect(await controller.confirm({ operationId: 'op-6', title: 't', text: 'x', scope: 's' }))
      .toEqual({ kind: 'unavailable' })
    expect(controller.current()).toBeNull()
  })

  it('quickPick reports a picked value or cancelled', async () => {
    const controller = createDialogController()
    const pending = controller.quickPick({
      operationId: 'op-7', title: '选择目录', items: [{ id: 'a', label: 'A' }], scope: 's',
    })
    controller.current()!.resolve({ kind: 'picked', value: 'a' })
    expect(await pending).toEqual({ kind: 'picked', value: 'a' })
  })

  it('double resolve of one dialog settles exactly once', async () => {
    const controller = createDialogController()
    const results: DialogResult[] = []
    const pending = controller.confirm({ operationId: 'op-8', title: 't', text: 'x', scope: 's' })
    pending.then(r => results.push(r))
    const view = controller.current()
    view!.resolve({ kind: 'confirmed' })
    view!.resolve({ kind: 'cancelled' }) // late duplicate: write-free no-op
    await pending
    expect(results).toEqual([{ kind: 'confirmed' }])
  })
})
