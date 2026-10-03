/**
 * F5 edit sessions (R7/M14 `oe-f5/1`, T008-16) — the frozen EditSession/
 * SettingsContribution signatures.
 *
 * The platform provides the editing TOOL; values and business validation
 * stay with the editing owner (never a second DraftOwner). Commit captures
 * the field mask + base/edit revisions and success clears ONLY fields that
 * are still unchanged since that capture — the ABA case (a late success
 * after a new edit, even with identical text) never wipes the newer edit.
 * Conflicts keep local values for manual resolution; `unknown` outcomes
 * keep their query hint and are never auto-retried. Secret-typed fields
 * accept SecretRef shapes only — never plaintext in a generic form store.
 */
import type {
  EditOutcome,
  EditSession,
  ReleaseHandle,
  SettingsContribution,
} from '../../../contracts/foundation/src/open-environment/f5/types'
import { EditConflictError } from '../../../contracts/foundation/src/open-environment/f5/errors'

export interface SecretRefShape {
  ref: string
  revision: string
}

export interface EditSessionOptions<V> {
  editId: string
  baseRevision: string
  initial: V
  /** Field names whose values must be SecretRef shapes (F5 §5). */
  sensitiveFields?: ReadonlyArray<keyof V & string>
  /** Domain-owned conditional write: validates business rules and performs it. */
  commitHandler: (capture: {
    editId: string
    baseRevision: string
    editRevision: number
    fields: ReadonlyArray<keyof V & string>
    values: Readonly<Partial<V>>
  }) => Promise<EditOutcome>
}

export function createEditSession<V extends Record<string, unknown>>(
  options: EditSessionOptions<V>,
): EditSession<V> & { readonly current: Readonly<V> } {
  const sensitive = new Set<string>(options.sensitiveFields ?? [])
  let values: V = { ...options.initial }
  let editRevision = 0
  const dirty = new Set<keyof V & string>()
  // Per-field edit stamps: "unchanged since capture" means NO EDIT EVENT on
  // the field after the capture — a same-text re-edit is still an edit and
  // must survive a late success (ABA case, F5 §5).
  const editedAt = new Map<keyof V & string, number>()
  const conflictListeners = new Set<(info: { field: string; theirRevision: string }) => void>()
  let closed = false

  function assertSecretShape(field: keyof V & string, value: unknown): void {
    if (!sensitive.has(field)) return
    const shape = value as SecretRefShape | null
    if (shape === null || typeof shape !== 'object'
        || typeof shape.ref !== 'string' || typeof shape.revision !== 'string') {
      throw new EditConflictError(
        'sensitive fields accept SecretRef shapes only; plaintext is refused')
    }
  }

  return {
    editId: options.editId,
    baseRevision: options.baseRevision,

    get editRevision() { return editRevision },

    dirtyFields(): ReadonlySet<keyof V & string> {
      return new Set(dirty)
    },

    get current(): Readonly<V> {
      return values
    },

    setValue(field, value): void {
      if (closed) throw new EditConflictError('edit session is closed')
      assertSecretShape(field, value)
      values = { ...values, [field]: value }
      dirty.add(field)
      editRevision += 1
      editedAt.set(field, editRevision)
    },

    async commit(): Promise<EditOutcome> {
      if (closed) throw new EditConflictError('edit session is closed')
      const captureRevision = editRevision
      const fields = [...dirty]
      const capturedStamps = new Map(fields.map(f => [f, editedAt.get(f) ?? 0]))
      const outcome = await options.commitHandler({
        editId: options.editId,
        baseRevision: options.baseRevision,
        editRevision: captureRevision,
        fields,
        values: Object.fromEntries(fields.map(f => [f, values[f]])) as Partial<V>,
      })
      if (outcome.kind === 'saved') {
        // Clear ONLY fields unchanged since the capture: a late success can
        // never wipe an edit made after the capture (ABA safe, even when the
        // newer text equals the captured one).
        for (const field of fields) {
          const stamped = capturedStamps.get(field) ?? 0
          const now = editedAt.get(field) ?? 0
          if (now <= stamped) {
            // no edit event after the capture: safe to clear, text-identical
            // or not — value equality is NOT the criterion.
            dirty.delete(field)
            editedAt.delete(field)
          }
        }
      } else if (outcome.kind === 'conflict') {
        // Local values are KEPT for manual resolution (F5 §5).
        for (const listener of [...conflictListeners]) {
          listener({ field: outcome.field, theirRevision: outcome.theirRevision })
        }
      }
      // 'unknown' keeps the association via queryHint: no auto-retry here.
      return outcome
    },

    cancel(): void {
      // Drops THIS edit only; accepted saves are never withdrawn.
      closed = true
      dirty.clear()
    },

    onConflict(cb): ReleaseHandle {
      conflictListeners.add(cb)
      let released = false
      return {
        release: () => {
          if (released) return
          released = true
          conflictListeners.delete(cb)
        },
      }
    },
  }
}

/** SettingsContribution shape guard: secret contributions never accept plaintext. */
export function settingsContribution<V>(contribution: SettingsContribution): SettingsContribution {
  if (contribution.sensitive) {
    const validate = contribution.validate
    return {
      ...contribution,
      validate(value: unknown): string | null {
        const shape = value as SecretRefShape | null
        if (shape === null || typeof shape !== 'object'
            || typeof shape.ref !== 'string' || typeof shape.revision !== 'string') {
          return 'sensitive fields accept SecretRef shapes only'
        }
        return validate(value)
      },
    }
  }
  return contribution
}
