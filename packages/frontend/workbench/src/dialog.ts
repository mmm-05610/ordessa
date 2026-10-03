/**
 * F4 Workbench dialog capability (T009-08; platform-services.md §宿主交互).
 *
 * Plain dialogs reuse the Workbench's existing overlay/rendering surface —
 * no second modal system. Each request carries a stable operationId and a
 * scope; results are selected/confirmed/cancelled/revoked/unavailable/failed
 * (never a boolean that could be mistaken for an approval). Cancel is
 * zero-write by contract: the caller does the writing, the dialog only
 * reports the user's choice. A revoked scope resolves `revoked` and the
 * late callback writes nothing (the caller re-checks its scope).
 */

export type DialogResult =
  | { kind: 'confirmed' }
  | { kind: 'picked'; value: string }
  | { kind: 'cancelled' }
  | { kind: 'revoked' }
  | { kind: 'unavailable' }
  | { kind: 'failed'; reason: string }

export interface ConfirmRequest {
  operationId: string
  title: string
  text: string
  scope: string
}

export interface QuickPickRequest {
  operationId: string
  title: string
  items: ReadonlyArray<{ id: string; label: string }>
  scope: string
}

export interface DialogView {
  readonly operationId: string
  readonly title: string
  readonly text?: string
  readonly items?: ReadonlyArray<{ id: string; label: string }>
  resolve(result: DialogResult): void
}

export interface DialogController {
  /** Current visible dialog (one at a time — a second request queues as
   *  unavailable rather than stacking modals over the window controls). */
  current(): DialogView | null
  subscribe(listener: () => void): () => void
  confirm(request: ConfirmRequest): Promise<DialogResult>
  quickPick(request: QuickPickRequest): Promise<DialogResult>
  /** Scope exit: the pending dialog resolves `revoked`, late resolves no-op. */
  revokeScope(scope: string): void
}

export function createDialogController(options: { available?: boolean } = {}): DialogController {
  const available = options.available ?? true
  const listeners = new Set<() => void>()
  let current: (DialogView & { scope: string }) | null = null
  let seq = 0
  const notify = () => { for (const listener of [...listeners]) listener() }

  function open(
    scope: string,
    build: (resolve: (result: DialogResult) => void) => DialogView & { scope: string },
  ): Promise<DialogResult> {
    if (!available) return Promise.resolve({ kind: 'unavailable' })
    if (current !== null) {
      // one dialog at a time; the overlay must never cover the window controls
      return Promise.resolve({ kind: 'unavailable' })
    }
    return new Promise(resolve => {
      let settled = false
      const finish = (result: DialogResult) => {
        if (settled) return // late duplicate resolves are write-free no-ops
        settled = true
        if (current?.operationId === view.operationId) current = null
        notify()
        resolve(result)
      }
      const view = build(finish)
      current = { ...view, scope } as DialogView & { scope: string }
      notify()
    })
  }

  return {
    current: () => current,
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    confirm(request) {
      return open(request.scope, resolve => ({
        operationId: request.operationId ?? `dlg-${++seq}`,
        title: request.title,
        text: request.text,
        scope: request.scope,
        resolve,
      }))
    },
    quickPick(request) {
      return open(request.scope, resolve => ({
        operationId: request.operationId ?? `pick-${++seq}`,
        title: request.title,
        items: request.items,
        scope: request.scope,
        resolve,
      }))
    },
    revokeScope(scope) {
      if (current !== null && current.scope === scope) {
        const pending = current
        current = null
        notify()
        pending.resolve({ kind: 'revoked' })
      }
    },
  }
}
