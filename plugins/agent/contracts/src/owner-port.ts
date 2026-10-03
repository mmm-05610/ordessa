/**
 * A1 owner client port (T010-02/12): the PUBLIC read/subscribe/dispatch face
 * consumers use instead of holding write state. Frontend glue (Profile
 * selection, model next-turn, Chat drafts) becomes a thin operation source:
 * it dispatches operations and renders frozen projections — the owner holds
 * the only write face (one writer per canonical target).
 *
 * The wire-backed implementation talks the `agent.*` methods of the Agent
 * domain plugin; absent wiring yields typed `unavailable` answers — never a
 * silent local store standing in for the owner.
 */

export type OwnerAnswer<T> =
  | { kind: 'ok'; value: T }
  | { kind: 'unknown'; queryHint: string }
  | { kind: 'unavailable'; reason: string }

export interface ConfigSnapshotView {
  ownerRef: string
  revision: number
  observedEvidence: 'native' | 'unset' | 'unknown'
  fields: Readonly<Record<string, 'known' | 'unset' | 'unknown'>>
  resolved: Readonly<Record<string, unknown>>
}

export interface OperationReceipt {
  operationId: string
  patchKinds: ReadonlyArray<'present' | 'unset'>
  state: 'pending' | 'applied' | 'unknown' | 'conflict'
}

export interface SubmissionOutcome {
  submissionId: string
  outcome: 'accepted' | 'known-rejected' | 'unknown'
  consumedDraftRevision?: number
  queryRequestKey?: string
  resend?: false
}

/** The dispatch face every consumer uses; no setState exists here. */
export interface AgentOwnerPort {
  readConfig(target: string): Promise<OwnerAnswer<ConfigSnapshotView>>
  submitConfigOperation(
    target: string,
    patch: Readonly<Record<string, unknown>>,
    options?: { unset?: ReadonlyArray<string>; sourceRef?: string },
  ): Promise<OwnerAnswer<OperationReceipt>>
  submitInput(
    target: string,
    draftRevision: number,
    capture: Readonly<Record<string, unknown>>,
  ): Promise<OwnerAnswer<SubmissionOutcome>>
  listSessions(target: string): Promise<OwnerAnswer<ReadonlyArray<Record<string, unknown>>>>
  queryRun(target: string, runId: string): Promise<OwnerAnswer<Record<string, unknown>>>
}

export interface WireCall {
  (method: string, params: Readonly<Record<string, unknown>>): Promise<
    { kind: 'Accepted'; result: Record<string, unknown> }
    | { kind: 'Refused'; reason: string }
    | { kind: 'Unknown'; reason: string }
  >
}

/**
 * The wire-backed port. `call` is the shared WirePort adapter; the port maps
 * the three wire states onto OwnerAnswer without inventing verdicts.
 */
export function createAgentOwnerPort(call: WireCall): AgentOwnerPort {
  async function ask<T>(
    method: string,
    params: Record<string, unknown>,
    project: (result: Record<string, unknown>) => T,
  ): Promise<OwnerAnswer<T>> {
    const answer = await call(method, params)
    if (answer.kind === 'Accepted') return { kind: 'ok', value: project(answer.result) }
    if (answer.kind === 'Unknown') return { kind: 'unknown', queryHint: `wire:${method}` }
    return { kind: 'unavailable', reason: answer.reason }
  }
  return {
    readConfig: target => ask('agent.config.read', { target }, r => r as unknown as ConfigSnapshotView),
    submitConfigOperation: (target, patch, options) =>
      ask('agent.config.submitOperation', {
        target, patch, unset: [...(options?.unset ?? [])], sourceRef: options?.sourceRef,
      }, r => r as unknown as OperationReceipt),
    submitInput: (target, draftRevision, capture) =>
      ask('agent.submitInput', { target, draftRevision, capture },
        r => r as unknown as SubmissionOutcome),
    listSessions: target => ask('agent.session.list', { target },
      r => (r.items as Array<Record<string, unknown>>) ?? []),
    queryRun: (target, runId) => ask('agent.run.query', { target, runId },
      r => (r.run as Record<string, unknown>) ?? r),
  }
}

/** Absent wiring: typed unavailable everywhere, never a silent local store. */
export function createAbsentAgentOwnerPort(): AgentOwnerPort {
  const unavailable = () => Promise.resolve({
    kind: 'unavailable' as const,
    reason: 'no Agent owner wiring is composed; consumers dispatch typed-unavailable, never a local store',
  })
  return {
    readConfig: unavailable,
    submitConfigOperation: unavailable,
    submitInput: unavailable,
    listSessions: unavailable,
    queryRun: unavailable,
  }
}
