// authored in this line (Z3 T05) — consumer-side next-turn client, E1.
// The submit permit gate itself is C0/Z2 production wiring (api-requests
// REQ-Z3-2/REQ-Z3-4); until it lands, this module is the contribution's
// honest consumer: it queues through the frozen ``modelProvider.*`` wire and
// applies ONLY results whose identity matches its own session and operation.
//
// 021 T04: the client also carries the frozen appendix §2 submit gate
// (``modelProvider.beginTurnApplication``) and the read-only reconcile the
// bound-mode UI sync uses. Semantics locked here:
// - ``submitTurn`` sends the queued intent for THIS exact target with a fresh
//   operation key per explicit attempt (§6b.2: a retry is a new key; the same
//   key only replays a recorded outcome);
// - ``ready`` consumes the local intent (the server consumed its own);
// - ``refused``/``unknown-outcome`` keep the intent (an explicit retry gets a
//   new key; an unknown keeps blocking until an observation settles it);
// - ``no-intent`` passes through: the Profile pipeline owns a bound session's
//   apply, and an empty queue needs none;
// - ``reconcile`` is observe-only (MP-07): it never applies or retries.
//
// 021 §6c F2 (codex review F2): every queue answer also carries the intent's
// handover ROUTE (``intentRoute``). The client records that fate —
// profile-overlay | independent | handover-failed, plus an UNDECIDED latch
// when the answer carries no valid route — and the send gate adjudicates it
// (``intentFate``); a bound fact alone is no longer a sufficient permit.
import type { ComposerLocation, QueuedChoice, ObservedModel } from './selector'

export const TRANSPORT_MISSING = 'MODEL_PROVIDER_CHAT_TRANSPORT_MISSING'
export const TARGET_UNAVAILABLE = 'CHAT_TARGET_UNAVAILABLE'

export type WireInvoke = (method: string, params: object) => Promise<unknown>

export type QueueOutcome =
  | { state: 'pending-next-turn'; sequence: number }
  | { state: 'refused'; code: string }
  | { state: 'unknown-outcome'; code: string }

/** The frozen appendix §2 submit-gate outcomes a client consumes. */
export type SubmitOutcome =
  | { state: 'ready'; sequence: number; application: TurnApplication }
  | { state: 'refused'; code: string }
  | { state: 'unknown-outcome'; code: string }
  | { state: 'no-intent' }

export interface TurnApplication {
  operationId: string
  nativeTarget: { owner: string; canonicalUid: string; generation: number }
  appliedRevision: string | null
  evidenceRef: string
}

export type ReconcileOutcome =
  | { state: 'confirmed'; turnFact: QueuedChoice }
  | { state: 'refused'; code: string }
  | { state: 'unknown-outcome'; code: string }

/** The handover route a queue/inspect answer reports (021 §6c F2.2). */
export type IntentRoute = 'profile-overlay' | 'independent' | 'handover-failed'

/** The newest intent's fate, as the send gate must see it (§6c F2.3):
 * - ``routed``: a bound Profile session's overlay owns it — the Profile
 *   pipeline applies it on the send; the gate passes only while the binding
 *   is still projected;
 * - ``independent``: the model queue owns it — an unbound send submits it;
 * - ``handover-failed``: the target WAS bound but the overlay handover failed
 *   or is unknown — the send is blocked (zero prompt, intent kept);
 * - ``undecided``: a queue answer without a valid route — blocked until an
 *   observation settles the queue (fail-closed, never read as independent);
 * - ``none``: nothing pending — the gate passes. */
export type IntentFate =
  | { kind: 'none' }
  | { kind: 'routed' }
  | { kind: 'independent' }
  | { kind: 'handover-failed'; code: string }
  | { kind: 'undecided'; code: string }

const INTENT_ROUTES: readonly IntentRoute[] = ['profile-overlay', 'independent', 'handover-failed']

function routeOf(answer: { intentRoute?: unknown; intentReason?: unknown }): IntentRoute | null {
  return typeof answer.intentRoute === 'string' && INTENT_ROUTES.includes(answer.intentRoute as IntentRoute)
    ? answer.intentRoute as IntentRoute : null
}

/** The frozen wire contract of the queue call (t00-freeze.md §8). */
export const CHOOSE_METHOD = 'modelProvider.chooseForSession'
export const QUERY_METHOD = 'modelProvider.queryChoice'
export const SUBMIT_METHOD = 'modelProvider.beginTurnApplication'
export const RECONCILE_METHOD = 'modelProvider.reconcileChoice'
export type ChoiceObservation =
  | { state: 'observed'; desired: QueuedChoice | null; lastConfirmed: QueuedChoice | null; current?: ObservedModel | null }
  | { state: 'unknown-outcome'; code: string }

function targetOf(location: ComposerLocation):
  | { ok: true; target: Record<string, string> }
  | { ok: false; code: string } {
  if (location.kind === 'session') {
    const { serverInstanceId, harnessId, acpSessionId } = location.session
    if (![serverInstanceId, harnessId, acpSessionId].every(value => typeof value === 'string' && value.trim()))
      return { ok: false, code: TARGET_UNAVAILABLE }
    return { ok: true, target: { serverInstanceId, harnessId, acpSessionId } }
  }
  // A draft is not yet a native session: there is nothing to queue a
  // next-turn intent against. The caller keeps its draft; nothing is sent.
  return { ok: false, code: TARGET_UNAVAILABLE }
}

export interface NextTurnClient {
  queue(choice: QueuedChoice): Promise<QueueOutcome>
  query(): Promise<ChoiceObservation>
  /** The appendix §2 submit gate for this session's queued intent. A fresh
   * operation key per call (§6b.2); the caller decides what a refusal or an
   * unknown means for the send — this client only reports and keeps its own
   * bookkeeping consistent (a ready consumes the local intent). */
  submitTurn(expectedSequence?: number): Promise<SubmitOutcome>
  /** Read-only observation of one queued operation (bound-mode UI sync). */
  reconcile(operationId?: number): Promise<ReconcileOutcome>
  /** A resolution arriving later: only the exact session/operation identity
   * is applied; anything else is rejected and leaves the state untouched
   * (MP-07: an unattributable outcome is never a success). */
  applyResolution(resolution: { session: Record<string, string>; sequence: number;
                                outcome: string; reason?: string }): QueueOutcome | { rejected: true }
  readonly pending: QueuedChoice | null
  /** The newest intent's handover fate (§6c F2.2/F2.3): the send gate's
   * verdict input. A bound fact alone is not a sufficient permit. */
  intentFate(): IntentFate
  /** Live bookkeeping changes (submit/reconcile outcomes) for the owner UI. */
  onUpdate(listener: () => void): () => void
}

export function createNextTurnClient(
  invoke: WireInvoke | undefined, location: ComposerLocation, isCurrent: () => boolean = () => true,
): NextTurnClient {
  if (invoke === undefined) {
    // No transport: a typed refusal, never a selector that silently no-ops
    // (same discipline as the settings side TRANSPORT_MISSING).
    return {
      get pending() { return null },
      queue: async () => ({ state: 'refused', code: TRANSPORT_MISSING }),
      query: async () => ({ state: 'unknown-outcome', code: TRANSPORT_MISSING }),
      submitTurn: async () => ({ state: 'refused', code: TRANSPORT_MISSING }),
      reconcile: async () => ({ state: 'unknown-outcome', code: TRANSPORT_MISSING }),
      applyResolution: () => ({ rejected: true }),
      intentFate: () => ({ kind: 'none' as const }),
      onUpdate: () => () => undefined,
    }
  }
  let pending: QueuedChoice | null = null
  let sequence = 0
  let attempts = 0
  // §6c F2.2: the newest intent's handover route + the undecided latch.
  let route: IntentRoute | null = null
  let handoverCode = 'HANDOVER_UNRESOLVED'
  let undecided: string | null = null
  const listeners = new Set<() => void>()
  const notify = () => { for (const listener of [...listeners]) listener() }
  const fate = (): IntentFate => {
    if (undecided !== null) return { kind: 'undecided', code: undecided }
    if (pending === null) return { kind: 'none' }
    if (route === 'handover-failed') return { kind: 'handover-failed', code: handoverCode }
    if (route === 'profile-overlay') return { kind: 'routed' }
    if (route === 'independent') return { kind: 'independent' }
    // a queued intent with no known route is an unsafe state, never "independent"
    return { kind: 'undecided', code: 'OPERATION_UNKNOWN' }
  }
  const target = targetOf(location)
  return {
    get pending() { return pending },
    intentFate: fate,
    onUpdate(listener: () => void) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    async query(): Promise<ChoiceObservation> {
      if (!target.ok || !isCurrent()) return { state: 'unknown-outcome', code: 'TARGET_STALE' }
      const capturedAttempts = attempts
      try {
        const answer = await invoke(QUERY_METHOD, { target: target.target }) as {
          current?: { modelId?: unknown; provider?: unknown } | null
          desired?: { providerConfigId?: string; modelId?: string } | null
          lastConfirmed?: { harnessId?: string; providerConfigId?: string; modelId?: string;
            providerConfigVersion?: number; evidence?: { applied?: string } } | null
          revision?: number | null
          intentRoute?: unknown
          intentReason?: unknown
        }
        if (!isCurrent()) return { state: 'unknown-outcome', code: 'TARGET_STALE' }
        if (attempts !== capturedAttempts) return { state: 'unknown-outcome', code: 'OBSERVATION_STALE' }
        if (!answer || !('desired' in answer) || !('lastConfirmed' in answer)
          || (answer.revision !== null && !Number.isSafeInteger(answer.revision)))
          return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
        const choiceOf = (value: { providerConfigId?: string; modelId?: string }) =>
          typeof value.providerConfigId === 'string' && !!value.providerConfigId.trim()
          && typeof value.modelId === 'string' && !!value.modelId.trim()
            ? { harnessId: target.target.harnessId, providerConfigId: value.providerConfigId, modelId: value.modelId } : undefined
        const desired = answer.desired === null ? null : answer.desired && choiceOf(answer.desired)
        if (desired === undefined || (desired && !Number.isSafeInteger(answer.revision)))
          return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
        if (desired) {
          // an observed pending intent must name its handover route (§6c F2.2)
          const observedRoute = routeOf(answer)
          if (observedRoute === null) return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
          route = observedRoute
          handoverCode = typeof answer.intentReason === 'string' && answer.intentReason
            ? answer.intentReason : 'HANDOVER_UNRESOLVED'
        } else {
          route = null
        }
        // an observation settles whatever the queue latch was holding
        undecided = null
        const fact = answer.lastConfirmed
        const lastConfirmed = fact && fact.harnessId === target.target.harnessId
          && Number.isSafeInteger(fact.providerConfigVersion)
          && ['read-back-verified', 'reconcile-verified'].includes(fact.evidence?.applied ?? '')
          ? choiceOf(fact) ?? null : null
        pending = desired
        if (typeof answer.revision === 'number') sequence = answer.revision
        notify()
        const current = answer.current && typeof answer.current.modelId === 'string' && answer.current.modelId.trim()
          && (answer.current.provider === null || typeof answer.current.provider === 'string')
          ? { modelId: answer.current.modelId, provider: answer.current.provider as string | null } : null
        return { state: 'observed', desired, lastConfirmed, ...(Object.hasOwn(answer, 'current') ? { current } : {}) }
      } catch (error) {
        return { state: 'unknown-outcome', code: !isCurrent() ? 'TARGET_STALE'
          : (error as { details?: { internalCode?: string } })?.details?.internalCode ?? 'OPERATION_UNKNOWN' }
      }
    },
    async queue(choice: QueuedChoice): Promise<QueueOutcome> {
      if (!isCurrent()) return { state: 'refused', code: 'TARGET_STALE' }
      if (!target.ok) return { state: 'refused', code: target.code }
      if (choice.harnessId !== target.target.harnessId) return { state: 'refused', code: 'TARGET_STALE' }
      attempts += 1
      try {
        const answer = await invoke(CHOOSE_METHOD, {
          target: target.target,
          choice: { providerConfigId: choice.providerConfigId, modelId: choice.modelId },
          operationKey: `chat-queue-${location.kind === 'session' ? location.session.acpSessionId : 'draft'}-${attempts}-${globalThis.crypto.randomUUID()}`,
        }) as { outcome?: string; sequence?: number; intentRoute?: unknown; intentReason?: unknown }
        if (!isCurrent()) return { state: 'refused', code: 'TARGET_STALE' }
        if (answer?.outcome !== 'pending-next-turn' || !Number.isSafeInteger(answer.sequence)) {
          undecided = undecided ?? 'OPERATION_UNKNOWN'
          return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
        }
        const ackSequence = answer.sequence as number
        // a late acknowledgement of an older click never overrides a newer
        // recorded sequence (exact-sequence fencing, M12)
        if (sequence > 0 && ackSequence < sequence) {
          return { state: 'unknown-outcome', code: 'OBSERVATION_STALE' }
        }
        const answerRoute = routeOf(answer)
        if (answerRoute === null) {
          // §6c F2.2: an answer that names no handover route is an unsafe
          // state — undecided, never "independent"
          undecided = 'OPERATION_UNKNOWN'
          return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
        }
        sequence = ackSequence
        route = answerRoute
        handoverCode = typeof answer.intentReason === 'string' && answer.intentReason
          ? answer.intentReason : 'HANDOVER_UNRESOLVED'
        undecided = null
        pending = choice
        notify()
        return { state: 'pending-next-turn', sequence }
      } catch (error) {
        if (!isCurrent()) return { state: 'refused', code: 'TARGET_STALE' }
        const fact = error as { outcome?: string; details?: { internalCode?: string } }
        const code = fact?.details?.internalCode
        // a definitive refusal did not change the server's queue
        if (fact.outcome === 'Refused' || (code && fact.outcome !== 'Unknown'))
          return { state: 'refused', code: code ?? 'SELECTION_REFUSED' }
        undecided = code ?? 'OPERATION_UNKNOWN'
        return { state: 'unknown-outcome', code: code ?? 'OPERATION_UNKNOWN' }
      }
    },
    async submitTurn(expectedSequence?: number): Promise<SubmitOutcome> {
      if (!target.ok) return { state: 'refused', code: target.code }
      if (!isCurrent()) return { state: 'refused', code: 'TARGET_STALE' }
      // §6b.2: one operation key per explicit attempt; the next attempt (an
      // explicit retry after refused/unknown) carries a NEW key, and the same
      // key only ever replays a recorded outcome.
      attempts += 1
      const operationKey = `chat-submit-${target.target.acpSessionId}-${attempts}-${globalThis.crypto.randomUUID()}`
      const frozen = Number.isSafeInteger(expectedSequence) ? expectedSequence
        : (Number.isSafeInteger(sequence) && sequence > 0 ? sequence : undefined)
      // only the intent this submit actually froze may be consumed by its
      // ready answer; a pick made while the submit was in flight belongs to
      // the NEXT turn (FR-04/M12)
      const tracked = pending
      try {
        const answer = await invoke(SUBMIT_METHOD, {
          target: target.target, operationKey,
          ...(frozen !== undefined ? { expectedSequence: frozen } : {}),
        }) as {
          outcome?: string; sequence?: number | null; reason?: string | null
          application?: TurnApplication | null
        }
        if (!isCurrent()) return { state: 'refused', code: 'TARGET_STALE' }
        const reason = typeof answer?.reason === 'string' && answer.reason
          ? answer.reason : 'OPERATION_UNKNOWN'
        if (answer?.outcome === 'no-intent') return { state: 'no-intent' }
        if (answer?.outcome === 'ready') {
          const application = answer.application
          if (!application || typeof application.operationId !== 'string'
            || !application.operationId
            || typeof application.evidenceRef !== 'string' || !application.evidenceRef
            || !application.nativeTarget
            || typeof application.nativeTarget.canonicalUid !== 'string'
            || !Number.isSafeInteger(application.nativeTarget.generation)) {
            // a ready answer without real evidence references is not ready
            return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
          }
          pending = tracked === null ? pending : null
          if (Number.isSafeInteger(answer.sequence)) sequence = answer.sequence!
          route = null
          undecided = null
          notify()
          return { state: 'ready', sequence: answer.sequence ?? frozen ?? 0, application }
        }
        if (answer?.outcome === 'refused') {
          notify()
          return { state: 'refused', code: reason }
        }
        notify()
        return { state: 'unknown-outcome', code: reason }
      } catch (error) {
        if (!isCurrent()) return { state: 'refused', code: 'TARGET_STALE' }
        const fact = error as { outcome?: string; details?: { internalCode?: string } }
        const code = fact?.details?.internalCode
        notify()
        return fact.outcome === 'Refused' || (code && fact.outcome !== 'Unknown')
          ? { state: 'refused', code: code ?? 'SELECTION_REFUSED' }
          : { state: 'unknown-outcome', code: code ?? 'OPERATION_UNKNOWN' }
      }
    },
    async reconcile(operationId?: number): Promise<ReconcileOutcome> {
      if (!target.ok) return { state: 'unknown-outcome', code: TARGET_UNAVAILABLE }
      if (!isCurrent()) return { state: 'unknown-outcome', code: 'TARGET_STALE' }
      const id: number = Number.isSafeInteger(operationId) ? operationId as number : sequence
      if (!Number.isSafeInteger(id) || id <= 0) {
        return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
      }
      try {
        const answer = await invoke(RECONCILE_METHOD, {
          target: target.target, operationId: id,
        }) as {
          outcome?: string; reason?: string
          turnFact?: { providerConfigId?: string; modelId?: string } | null
        }
        if (!isCurrent()) return { state: 'unknown-outcome', code: 'TARGET_STALE' }
        const fact = answer?.turnFact
        if (answer?.outcome === 'confirmed' && fact
          && typeof fact.providerConfigId === 'string' && typeof fact.modelId === 'string') {
          pending = null
          route = null
          undecided = null
          notify()
          return { state: 'confirmed', turnFact: {
            harnessId: target.target.harnessId,
            providerConfigId: fact.providerConfigId, modelId: fact.modelId } }
        }
        const code = typeof answer?.reason === 'string' && answer.reason
          ? answer.reason : 'OPERATION_UNKNOWN'
        notify()
        return answer?.outcome === 'refused'
          ? { state: 'refused', code } : { state: 'unknown-outcome', code }
      } catch (error) {
        if (!isCurrent()) return { state: 'unknown-outcome', code: 'TARGET_STALE' }
        const failure = error as { details?: { internalCode?: string } }
        return { state: 'unknown-outcome', code: failure?.details?.internalCode ?? 'OPERATION_UNKNOWN' }
      }
    },
    applyResolution(resolution): QueueOutcome | { rejected: true } {
      if (!isCurrent()) return { rejected: true }
      if (!target.ok || !pending) return { rejected: true }
      const sameSession = Object.entries(target.target)
        .every(([key, value]) => resolution.session[key] === value)
      if (!sameSession || resolution.sequence !== sequence) return { rejected: true }
      if (resolution.outcome === 'confirmed') {
        pending = null
        route = null
        undecided = null
        notify()
        return { state: 'pending-next-turn', sequence }  // applied; queue empty again
      }
      notify()
      return { state: resolution.outcome === 'refused' ? 'refused' : 'unknown-outcome',
               code: resolution.reason ?? 'OPERATION_UNKNOWN' }
    },
  }
}
