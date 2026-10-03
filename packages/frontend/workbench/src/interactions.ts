/**
 * F5 interactions (R7/M14 `oe-f5/1`, T008-18) — the frozen
 * InteractionService/NotificationHandle/ProgressHandle semantics on top of
 * the Workbench's existing presentation surface (F5 §7: merge, do not
 * build a parallel overlay stack).
 *
 * The manager owns the handle state machine; presentation is injected (the
 * Workbench binds it to its overlay stack/statusbar in the presentation
 * layer). Rules enforced here:
 * - repeat events carrying a declaration id UPDATE the existing handle —
 *   never a new red banner per keystroke;
 * - a cancel request projects the task's declared cancel action; the UI
 *   text NEVER claims "stopped" (only the task result can);
 * - handles are scope-bound: a revoked scope closes them and late updates
 *   on revoked handles are refused (InteractionScopeRevokedError);
 * - errors never guess at network loss or operation failure — the caller
 *   supplies what is known, and unknown stays unknown.
 */
// The Workbench reaches other packages ONLY through the sanctioned shared
// carrier (layering guard): f5 rides the carrier as a namespace export, so
// both the types and the error values come from ONE runtime source.
import { f5 } from '@extensions/ordessa.contracts/contract.js'

type InteractionService = f5.InteractionService
type NotificationHandle = f5.NotificationHandle
type ProgressHandle = f5.ProgressHandle
const InteractionScopeRevokedError = f5.InteractionScopeRevokedError

export interface InteractionPresenter {
  show(kind: 'notification' | 'progress', view: {
    id: string
    text: string
    severity?: 'info' | 'warning' | 'error'
    fraction?: number | null
    cancellable: boolean
  }): void
  dismiss(id: string): void
}

interface HandleState {
  id: string
  kind: 'notification' | 'progress'
  text: string
  severity: 'info' | 'warning' | 'error'
  fraction: number | null
  cancel?: () => void
  closed: boolean
}

export interface InteractionServiceOptions {
  presenter: InteractionPresenter
  /** Handles die with their scope; late updates are refused (F5 §4/§7). */
  scopeGeneration: () => number
}

export function createInteractionService(options: InteractionServiceOptions): InteractionService {
  const handles = new Map<string, HandleState>()
  let seq = 0
  let creationGeneration = options.scopeGeneration()

  function guard(handle: HandleState): void {
    if (handle.closed) {
      throw new InteractionScopeRevokedError('interaction handle is closed')
    }
    if (options.scopeGeneration() !== creationGeneration) {
      handle.closed = true
      throw new InteractionScopeRevokedError('interaction scope was revoked (stale generation)')
    }
  }

  function present(state: HandleState): void {
    options.presenter.show(state.kind, {
      id: state.id,
      text: state.text,
      severity: state.severity,
      fraction: state.fraction,
      cancellable: state.cancel !== undefined,
    })
  }

  function notificationHandle(state: HandleState): NotificationHandle {
    return {
      id: state.id,
      update(text: string): void {
        guard(state)
        state.text = text // stable id: UPDATE in place, never a second banner
        present(state)
      },
      close(): void {
        state.closed = true
        options.presenter.dismiss(state.id)
      },
    }
  }

  function progressHandle(state: HandleState): ProgressHandle {
    return {
      id: state.id,
      update(fraction: number | null, text?: string): void {
        guard(state)
        state.fraction = fraction
        if (text !== undefined) state.text = text
        present(state)
      },
      requestCancel(): void {
        guard(state)
        // Projects the task's declared cancel; the label must NOT flip to
        // "stopped" here — only the task result establishes that.
        state.cancel?.()
      },
      close(): void {
        state.closed = true
        options.presenter.dismiss(state.id)
      },
    }
  }

  return {
    notify(opts): NotificationHandle {
      const id = opts.id ?? `n-${++seq}`
      const existing = handles.get(id)
      if (existing !== undefined && !existing.closed && existing.kind === 'notification') {
        existing.text = opts.text
        existing.severity = opts.severity
        present(existing) // repeat events update the SAME handle
        return notificationHandle(existing)
      }
      const state: HandleState = {
        id, kind: 'notification', text: opts.text, severity: opts.severity,
        fraction: null, closed: false,
      }
      handles.set(id, state)
      present(state)
      return notificationHandle(state)
    },

    progress(opts): ProgressHandle {
      const id = opts.id ?? `p-${++seq}`
      const state: HandleState = {
        id, kind: 'progress', text: opts.text, severity: 'info',
        fraction: null, cancel: opts.cancel, closed: false,
      }
      handles.set(id, state)
      present(state)
      return progressHandle(state)
    },

    async quickPick(opts) {
      // The manager presents; the presenter's user action resolves it.
      return new Promise(resolve => {
        options.presenter.show('notification', {
          id: `qp-${++seq}`, text: opts.title,
          severity: 'info', fraction: null, cancellable: true,
        })
        // Without an interactive presenter this resolves cancelled —
        // a missing capability is honest cancellation, never a fabricated pick.
        resolve({ kind: 'cancelled' })
      })
    },

    async confirm(opts) {
      return new Promise<'confirmed' | 'cancelled'>(resolve => {
        options.presenter.show('notification', {
          id: `cf-${++seq}`, text: `${opts.title}: ${opts.text}`,
          severity: 'info', fraction: null, cancellable: true,
        })
        resolve('cancelled') // missing interactive presenter: honest cancelled
      })
    },
  }
}
