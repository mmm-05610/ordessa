// authored in this line (Z3 T05) — consumer-side next-turn client, E1.
// The submit permit gate itself is C0/Z2 production wiring (api-requests
// REQ-Z3-2/REQ-Z3-4); until it lands, this module is the contribution's
// honest consumer: it queues through the frozen ``modelProvider.*`` wire and
// applies ONLY results whose identity matches its own session and operation.
import type { ComposerLocation } from './stub-chat-contract'
import type { QueuedChoice } from './selector'

export const TRANSPORT_MISSING = 'MODEL_PROVIDER_CHAT_TRANSPORT_MISSING'
export const TARGET_UNAVAILABLE = 'CHAT_TARGET_UNAVAILABLE'

export type WireInvoke = (method: string, params: object) => Promise<unknown>

export type QueueOutcome =
  | { state: 'pending-next-turn'; sequence: number }
  | { state: 'refused'; code: string }
  | { state: 'unknown-outcome'; code: string }

/** The frozen wire contract of the queue call (t00-freeze.md §8). */
export const CHOOSE_METHOD = 'modelProvider.chooseForSession'

function targetOf(location: ComposerLocation):
  | { ok: true; target: Record<string, string> }
  | { ok: false; code: string } {
  if (location.kind === 'session') {
    const { serverInstanceId, harnessId, acpSessionId } = location.session
    return { ok: true, target: { serverInstanceId, harnessId, acpSessionId } }
  }
  // A draft is not yet a native session: there is nothing to queue a
  // next-turn intent against. The caller keeps its draft; nothing is sent.
  return { ok: false, code: TARGET_UNAVAILABLE }
}

export interface NextTurnClient {
  queue(choice: QueuedChoice): Promise<QueueOutcome>
  /** A resolution arriving later: only the exact session/operation identity
   * is applied; anything else is rejected and leaves the state untouched
   * (MP-07: an unattributable outcome is never a success). */
  applyResolution(resolution: { session: Record<string, string>; sequence: number;
                                outcome: string; reason?: string }): QueueOutcome | { rejected: true }
  readonly pending: QueuedChoice | null
}

export function createNextTurnClient(
  invoke: WireInvoke | undefined, location: ComposerLocation,
): NextTurnClient {
  if (invoke === undefined) {
    // No transport: a typed refusal, never a selector that silently no-ops
    // (same discipline as the settings side TRANSPORT_MISSING).
    return {
      get pending() { return null },
      queue: async () => ({ state: 'refused', code: TRANSPORT_MISSING }),
      applyResolution: () => ({ rejected: true }),
    }
  }
  let pending: QueuedChoice | null = null
  let sequence = 0
  let attempts = 0
  const target = targetOf(location)
  return {
    get pending() { return pending },
    async queue(choice: QueuedChoice): Promise<QueueOutcome> {
      if (!target.ok) return { state: 'refused', code: target.code }
      attempts += 1
      try {
        const answer = await invoke(CHOOSE_METHOD, {
          target: target.target,
          choice: { providerConfigId: choice.providerConfigId, modelId: choice.modelId },
          operationKey: `chat-queue-${location.kind === 'session' ? location.session.acpSessionId : 'draft'}-${attempts}`,
        }) as { outcome?: string; sequence?: number }
        if (answer?.outcome !== 'pending-next-turn' || typeof answer.sequence !== 'number') {
          return { state: 'unknown-outcome', code: 'OPERATION_UNKNOWN' }
        }
        sequence = answer.sequence
        pending = choice
        return { state: 'pending-next-turn', sequence }
      } catch (error) {
        const code = (error as { details?: { internalCode?: string } })?.details?.internalCode
        return { state: 'refused', code: code ?? 'SELECTION_REFUSED' }
      }
    },
    applyResolution(resolution): QueueOutcome | { rejected: true } {
      if (!target.ok || !pending) return { rejected: true }
      const sameSession = Object.entries(target.target)
        .every(([key, value]) => resolution.session[key] === value)
      if (!sameSession || resolution.sequence !== sequence) return { rejected: true }
      if (resolution.outcome === 'confirmed') {
        pending = null
        return { state: 'pending-next-turn', sequence }  // applied; queue empty again
      }
      return { state: resolution.outcome === 'refused' ? 'refused' : 'unknown-outcome',
               code: resolution.reason ?? 'OPERATION_UNKNOWN' }
    },
  }
}
