/**
 * Profile selection state machine for the Chat composer (PV-10, PA01/PA03,
 * ux.md §3; click-time registration per 021 appendix §6c F1.1).
 *
 * Semantics locked here, and nowhere else:
 * - `select` records the user's choice and updates the label immediately; it
 *   performs NO port call itself (apply/abort/restart stay 0). The backend
 *   REGISTRATION (`selectForSession`, which stamps the session's action_seq)
 *   happens at click time for bound sessions — via the glue's per-session
 *   serializer — and the store tracks that state per pick.
 * - `applyOnSubmit` only ever runs `beginTurnApplication`, and only for a pick
 *   the backend already holds (or one the caller explicitly vouches for via
 *   `continuation`). It NEVER registers a selection at submit time: a
 *   submit-time registration would stamp a later action_seq than an earlier
 *   click and let a stale profile win over the user's last pick (review F1).
 * - An UNREGISTERED pick is never applied behind the guard's back: the store
 *   refuses with a reason, keeping the pick for (re-)registration.
 * - A failed application/registration keeps the selection and reports the
 *   reason; the draft text belongs to Chat and is never touched here, and the
 *   send is NOT silently allowed through with the old configuration.
 * - Ordinary bound-session submissions apply the effective configuration
 *   without reselecting.
 */
import type {
  AppliedReceiptDto,
  ProfileCatalogGroup,
  ProfileSelection,
  ProfileServiceClient,
  SessionRef,
} from '@ordessa/plugin-profile-api'

export interface SelectionCounters {
  selections: number
  applyAttempts: number
  applyConfirmed: number
  applyFailed: number
}

export type ApplyOutcome =
  | { readonly ok: true; readonly applied: ProfileSelection; readonly receipt?: AppliedReceiptDto }
  | { readonly ok: false; readonly reason: string; readonly selection: ProfileSelection; readonly unknown?: boolean }

interface StoreEntry {
  selection: ProfileSelection
  /** Whether the backend currently holds THIS pick (click-time registration
   * acknowledged). A new click resets it: the newest pick is the intent. */
  registered: boolean
  registrationError?: string
}

export class ProfileSelectionStore {
  private readonly entries = new Map<string, StoreEntry>()
  private readonly lastConfirmed = new Map<string, ProfileSelection>()
  private sequence = 0
  private revision = 0
  private readonly listeners = new Set<() => void>()
  getSnapshot = () => this.revision
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private publish() { this.revision += 1; for (const listener of this.listeners) listener() }

  readonly counters: SelectionCounters = {
    selections: 0,
    applyAttempts: 0,
    applyConfirmed: 0,
    applyFailed: 0,
  }

  /** Record the user's pick for one draft/session key (PA01). Bookkeeping
   * only: no port call, no run interruption. The pick starts UNREGISTERED;
   * the glue registers it (at click for bound sessions, at submit otherwise)
   * and acknowledges with {@link markRegistered}. */
  select(key: string, selection: ProfileSelection): void {
    this.counters.selections += 1
    this.entries.set(key, { selection, registered: false })
    this.publish()
  }

  /** The click-time registration reached the backend: this exact pick is now
   * the session's pending intent (its action_seq is the click's). */
  markRegistered(key: string, selection: ProfileSelection): void {
    const entry = this.entries.get(key)
    if (!entry || entry.selection !== selection) return // a newer pick owns the key
    this.entries.set(key, { selection, registered: true })
    this.publish()
  }

  /** The click-time registration failed: the pick is kept UNREGISTERED and
   * the reason is surfaced in the picker (never a silent drop). */
  markRegistrationFailed(key: string, selection: ProfileSelection, reason: string): void {
    const entry = this.entries.get(key)
    if (!entry || entry.selection !== selection) return
    this.entries.set(key, { selection, registered: false, registrationError: reason })
    this.publish()
  }

  /** Whether the store's current pick for this key is the given one AND is
   * backend-registered. */
  isRegistered(key: string, selection: ProfileSelection): boolean {
    const entry = this.entries.get(key)
    return !!entry && entry.selection === selection && entry.registered
  }

  /** The registered pending pick (the only one `applyOnSubmit` may consume
   * without an explicit caller vouch), or null. */
  registeredPending(key: string): ProfileSelection | null {
    const entry = this.entries.get(key)
    return entry && entry.registered ? entry.selection : null
  }

  /** The last registration failure reason for the current pick, if any. */
  registrationError(key: string): string | null {
    return this.entries.get(key)?.registrationError ?? null
  }

  /** What the button shows right now: the user's selection, falling back to
   * the last confirmed profile of this session. */
  currentLabel(key: string, fallbackName?: string): string | null {
    return this.entries.get(key)?.selection.displayName ?? this.lastConfirmed.get(key)?.displayName ?? fallbackName ?? null
  }

  peek(key: string): ProfileSelection | null {
    return this.entries.get(key)?.selection ?? null
  }

  /** Clear only what the UI subscription owns (scope teardown); stored
   * selections for live sessions are not business data and nothing here
   * aborts a run. */
  forget(key: string): void {
    this.entries.delete(key)
    this.publish()
  }

  /** A reusable composer draft is not a native session. Once accepted or
   * discarded, its confirmed label must not leak into the next empty draft.
   * Pending user picks and bound-session confirmations remain untouched. */
  clearDraftConfirmations(): void {
    let changed = false
    for (const key of this.lastConfirmed.keys()) {
      if (key.startsWith('draft:')) { this.lastConfirmed.delete(key); changed = true }
    }
    if (changed) this.publish()
  }

  /**
   * Next-submit application: run `beginTurnApplication` for the REGISTERED
   * pending pick (or the caller-vouched `continuation`) and let the caller
   * send. Registration never happens here — a pick that is not registered is
   * refused fail-closed with its reason, never applied with a submit-time
   * action_seq (review F1).
   */
  async applyOnSubmit(
    key: string,
    sessionRef: SessionRef,
    profiles: Pick<ProfileServiceClient, 'beginTurnApplication'> & Partial<Pick<ProfileServiceClient, 'inspectSessionConfig'>>,
    continuation?: ProfileSelection,
  ): Promise<ApplyOutcome> {
    // A captured binding is not a new user pick. In particular, a pick made
    // while native preparation/application waits belongs to the next turn.
    const entry = this.entries.get(key)
    const selection = continuation ?? (entry && entry.registered ? entry.selection : null)
    if (!selection) {
      if (entry && !entry.registered) {
        // fail-closed: the user's newest pick was never registered — passing
        // this off as an "ordinary turn" would send on the OLD configuration
        // while the pick looks pending. Registration is the click's (bound
        // sessions) or the guard's (drafts) job; until then: no apply, no send.
        return { ok: false, reason: '所选预设尚未登记到会话，已阻止本次应用；请重新选择或重试。', selection: entry.selection }
      }
      return { ok: true, applied: this.lastConfirmed.get(key) ?? { harnessId: sessionRef.harnessId, profileId: '', displayName: '' } }
    }
    if (!continuation && !this.isRegistered(key, selection)) {
      // fail-closed: an unregistered pick must be registered first — applying
      // it here would stamp the backend action_seq at SUBMIT time and let an
      // earlier-registered intent (or a later model pick) misorder against the
      // user's clicks.
      return { ok: false, reason: '所选预设尚未登记到会话，已阻止本次应用；请重新选择或重试。', selection }
    }
    this.counters.applyAttempts += 1
    try {
      const operationKey = `profile-chat.apply:${sessionRef.sessionUid}:${selection.profileId}:${this.sequence += 1}`
      const result = await profiles.beginTurnApplication(
        operationKey,
        sessionRef,
      )
      if (!result.appliedSwitch) {
        if (typeof profiles.inspectSessionConfig !== 'function') {
          throw new Error('Profile current configuration verification is unavailable')
        }
        const config = await profiles.inspectSessionConfig(sessionRef)
        const receipt = config.evidence?.receipt
        if (!sameSession(config.sessionRef, sessionRef) || config.current?.profileId !== selection.profileId
          || config.switchState !== 'settled' || config.pending !== null
          || !receipt || receipt.profileId !== selection.profileId
          || receipt.profileRevision !== config.current.revision || !sameSession(receipt.sessionRef, sessionRef)
          || !receipt.operationId || !receipt.configDigest || !receipt.confirmedAt
          || !receipt.evidenceKind || receipt.evidenceKind === 'legacy-unverified'
          || config.evidence.evidenceKind !== receipt.evidenceKind
          || config.evidence.journal?.state !== 'confirmed'
          || config.evidence.journal.operationId !== receipt.operationId) {
          throw new Error('Profile current configuration is not confirmed for this selection')
        }
        if (this.entries.get(key)?.selection === selection) this.entries.delete(key)
        this.lastConfirmed.set(key, selection)
        this.publish()
        return { ok: true, applied: selection, receipt }
      }
      const receipt = result.receipt
      if (!receipt || receipt.profileId !== selection.profileId || !sameSession(receipt.sessionRef, sessionRef)
          || !receipt.operationId || !receipt.configDigest || !receipt.confirmedAt
          || !receipt.evidenceKind || receipt.evidenceKind === 'legacy-unverified') {
        throw Object.assign(new Error('Profile application receipt is unproven for this selection'), { kind: 'Unknown' })
      }
      this.counters.applyConfirmed += 1
      if (this.entries.get(key)?.selection === selection) this.entries.delete(key)
      this.lastConfirmed.set(key, selection)
      this.publish()
      return { ok: true, applied: selection, receipt }
    } catch (error) {
      this.counters.applyFailed += 1
      // Keep the selection so the composer can offer retry/re-pick; never
      // report success and never fall back to the old configuration.
      const reason = error instanceof Error ? error.message : String(error)
      return { ok: false, reason, selection,
        ...(error && typeof error === 'object' && 'kind' in error && error.kind === 'Unknown' ? { unknown: true } : {}) }
    }
  }
}

function sameSession(actual: SessionRef | undefined, expected: SessionRef): boolean {
  return !!actual && actual.realm === expected.realm && actual.harnessId === expected.harnessId
    && actual.nativeSessionKey === expected.nativeSessionKey && actual.sessionUid === expected.sessionUid
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
