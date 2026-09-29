/**
 * Profile selection state machine for the Chat composer (PV-10, PA01/PA03,
 * ux.md §3).
 *
 * Semantics locked here, and nowhere else:
 * - `select` only records the user's choice; the button label updates
 *   immediately and NO port/service call happens (apply/abort/restart stay 0).
 * - `applyOnSubmit` runs at the next user submit and applies the LAST
 *   selection only — B then C applies just C, once.
 * - A failed application keeps the selection and reports the reason at the
 *   send operation; the draft text belongs to Chat and is never touched here,
 *   and the send is NOT silently allowed through with the old configuration.
 * - Selecting the profile that is already current is a no-op selection, never
 *   an overlay clear (G07 lives in the backend, not in the selector).
 */
import type {
  AppliedReceiptDto,
  ProfileCatalogGroup,
  ProfileSelection,
  ProfileServiceClient,
} from '@ordessa/plugin-profile-api'

export interface SelectionCounters {
  selections: number
  applyAttempts: number
  applyConfirmed: number
  applyFailed: number
}

export type ApplyOutcome =
  | { readonly ok: true; readonly applied: ProfileSelection; readonly receipt?: AppliedReceiptDto }
  | { readonly ok: false; readonly reason: string; readonly selection: ProfileSelection }

export class ProfileSelectionStore {
  private readonly selections = new Map<string, ProfileSelection>()
  private readonly lastConfirmed = new Map<string, ProfileSelection>()
  private sequence = 0

  readonly counters: SelectionCounters = {
    selections: 0,
    applyAttempts: 0,
    applyConfirmed: 0,
    applyFailed: 0,
  }

  /** Register the user's pick for one draft/session key.  Pure bookkeeping:
   * no port call, no run interruption, no status label (PA01). */
  select(key: string, selection: ProfileSelection): void {
    this.counters.selections += 1
    this.selections.set(key, selection)
  }

  /** What the button shows right now: the user's selection, falling back to
   * the last confirmed profile of this session. */
  currentLabel(key: string, fallbackName?: string): string | null {
    return this.selections.get(key)?.displayName ?? fallbackName ?? null
  }

  peek(key: string): ProfileSelection | null {
    return this.selections.get(key) ?? null
  }

  /** Clear only what the UI subscription owns (scope teardown); stored
   * selections for live sessions are not business data and nothing here
   * aborts a run. */
  forget(key: string): void {
    this.selections.delete(key)
  }

  /**
   * Next-submit admission: apply the last selection through the Profile
   * service, then let the caller send.  Consecutive picks collapse here —
   * only the final one reaches the service.
   */
  async applyOnSubmit(
    key: string,
    sessionRef: { readonly realm: string; readonly harnessId: string; readonly nativeSessionKey: string; readonly sessionUid: string },
    profiles: Pick<ProfileServiceClient, 'beginTurnApplication'>,
  ): Promise<ApplyOutcome> {
    const selection = this.selections.get(key)
    if (!selection) {
      return { ok: true, applied: this.lastConfirmed.get(key) ?? { harnessId: sessionRef.harnessId, profileId: '', displayName: '' } }
    }
    this.counters.applyAttempts += 1
    try {
      const result = await profiles.beginTurnApplication(
        `profile-chat.apply:${sessionRef.sessionUid}:${selection.profileId}:${this.sequence += 1}`,
        sessionRef,
      )
      if (!result.appliedSwitch) {
        // Not a switch (same profile re-selected): nothing was applied and
        // nothing needed to be; the pick is simply consumed.
        this.selections.delete(key)
        this.lastConfirmed.set(key, selection)
        return { ok: true, applied: selection }
      }
      this.counters.applyConfirmed += 1
      this.selections.delete(key)
      this.lastConfirmed.set(key, selection)
      return { ok: true, applied: selection, receipt: result.receipt ?? undefined }
    } catch (error) {
      this.counters.applyFailed += 1
      // Keep the selection so the composer can offer retry/re-pick; never
      // report success and never fall back to the old configuration.
      const reason = error instanceof Error ? error.message : String(error)
      return { ok: false, reason, selection }
    }
  }
}

/**
 * Catalog projection for the two-level picker.  An unbound draft may choose
 * from every available Harness group; an existing session only ever sees its
 * current Harness group — the picker never becomes a cross-Harness switch
 * (PA07, ux.md §3).
 */
export type CatalogScope = {
  readonly kind: 'draft'
  readonly draftId?: string
} | {
  readonly kind: 'session'
  readonly sessionUid?: string
  readonly harnessId: string
}

export function catalogForLocation(
  groups: readonly ProfileCatalogGroup[],
  location: CatalogScope,
): readonly ProfileCatalogGroup[] {
  if (location.kind === 'draft') return groups
  const own = groups.filter((group) => group.harnessId === location.harnessId)
  return own
}
