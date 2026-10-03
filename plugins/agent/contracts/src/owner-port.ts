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
    // The server reports a missing/undecided run as an unknown-outcome record
    // (`{outcome:'unknown', queryHint, resend:false}`); that is the OwnerAnswer
    // unknown arm, not an ok value — normalized here so wire and local ports
    // are swap-in identical (T010-12 parity).
    queryRun: async (target, runId) => {
      const answer = await call('agent.run.query', { target, runId })
      if (answer.kind === 'Unknown') return { kind: 'unknown', queryHint: `wire:agent.run.query` }
      if (answer.kind === 'Refused') return { kind: 'unavailable', reason: answer.reason }
      const record = (answer.result.run as Record<string, unknown>) ?? answer.result
      if (record.outcome === 'unknown' && typeof record.queryHint === 'string') {
        return { kind: 'unknown', queryHint: record.queryHint }
      }
      return { kind: 'ok', value: record }
    },
  }
}

// re-export the evidence chain with the owner face (T010-05)
export * from './config-evidence'

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

import { ConfigEvidenceChain, type EvidenceFrame, type EvidenceIntake } from './config-evidence'

/**
 * Local in-memory owner port (T010-02): the frontend's own UI-local state
 * (F5 §1 allows local state for independent UI targets) served through the
 * SAME dispatch face — writes go through operations, reads are frozen
 * projections, unknown outcomes keep query hints and never re-dispatch.
 * Mirrors the Python owner semantics (ordessa_agent.owners) exactly; the
 * wire-backed port swaps in when the Agent plugin is composed (T010-12):
 * same receipts, same queryHint strings, same `resend: false` markers.
 */
export interface LocalOwnerOptions {
  /**
   * Cross-port single-writer registry (one owner per canonical target).
   * Defaults to a process-wide set, matching the Python owner registry;
   * tests inject a fresh Set for isolation.
   */
  ownerRegistry?: Set<string>
}

export interface LocalAgentOwnerPort extends AgentOwnerPort {
  /** Trusted Harness evidence reporting (the evidence channel, not a competing writer). */
  reportEvidence(target: string, observed: 'native' | 'unset' | 'unknown',
                 fields?: Record<string, 'known' | 'unset' | 'unknown'>): void
  /** Native ConfigEvidence intake (T010-05): ordered snapshot/patch frames via
   * the ConfigEvidenceChain; only APPLIED frames change the owner's fields. */
  reportEvidenceFrame(target: string, frame: EvidenceFrame): EvidenceIntake
  /** SessionOwner upsert: merge fields per session id, freeze each record. */
  reportSessions(target: string, entries: Record<string, Record<string, unknown>>): void
  /** SessionOwner removal face for UI-scope teardown (drops ALL records of one target). */
  dropSessions(target: string): void
  /** RunOwner report: the ONLY writer of run states for one target. */
  reportRun(target: string, runId: string, state: 'running' | 'completed' | 'cancelled' | 'failed' | 'unknown', reason?: string): void
  /** How many times one submission was dispatched (Python dispatch_count parity: exactly one, ever). */
  dispatchCount(target: string, submissionId: string): number
  /**
   * Synchronous in-process face (Python owner parity: `submit_operation` is
   * synchronous there too). Frontend stores read project/dispatch through
   * these; the async AgentOwnerPort methods wrap the same core for wire
   * parity. Both faces share ONE state — there is never a second writer.
   */
  readConfigSync(target: string): ConfigSnapshotView
  listSessionsSync(target: string): ReadonlyArray<Record<string, unknown>>
  submitConfigOperationSync(
    target: string,
    patch: Readonly<Record<string, unknown>>,
    options?: { unset?: ReadonlyArray<string>; sourceRef?: string },
  ): OperationReceipt
}

const processOwnerRegistry = new Set<string>()

export function createLocalAgentOwnerPort(options: LocalOwnerOptions = {}): LocalAgentOwnerPort {
  const registry = options.ownerRegistry ?? processOwnerRegistry
  const targets = new Map<string, {
    fields: Map<string, 'known' | 'unset' | 'unknown'>
    resolved: Map<string, unknown>
    revision: number
    observed: 'native' | 'unset' | 'unknown'
    operations: Array<{ operationId: string; patchKinds: Array<'present' | 'unset'>; sourceRef?: string }>
    submissions: Map<string, SubmissionOutcome>
    dispatchCounts: Map<string, number>
    evidence: ConfigEvidenceChain
    sessions: Map<string, Record<string, unknown>>
    runs: Map<string, Record<string, unknown>>
  }>()
  let seq = 0

  function targetState(target: string) {
    let state = targets.get(target)
    if (state !== undefined) return state
    if (registry.has(target)) {
      throw new Error(`AUTHORITY_CONFLICT: target ${target} already has a registered owner`)
    }
    registry.add(target) // first touch registers the single writer
    state = {
      fields: new Map(), resolved: new Map(), revision: 0, observed: 'unset' as const,
      operations: [], submissions: new Map(), dispatchCounts: new Map(), evidence: new ConfigEvidenceChain(),
      sessions: new Map(), runs: new Map(),
    }
    targets.set(target, state)
    return state
  }

  const snapshotOf = (target: string): ConfigSnapshotView => {
    const state = targetState(target)
    return {
      ownerRef: `agent-config:${target}`,
      revision: state.revision,
      observedEvidence: state.observed,
      fields: Object.freeze(Object.fromEntries(state.fields)),
      resolved: Object.freeze(Object.fromEntries(state.resolved)),
    }
  }

  function submitConfigOperationNow(
    target: string,
    patch: Readonly<Record<string, unknown>>,
    opts?: { unset?: ReadonlyArray<string>; sourceRef?: string },
  ): OperationReceipt {
    const state = targetState(target)
    seq += 1
    const operationId = `op-${target}-${seq}`
    const patchKinds: Array<'present' | 'unset'> = []
    for (const [name, value] of Object.entries(patch)) {
      state.fields.set(name, 'known')
      state.resolved.set(name, value)
      patchKinds.push('present')
    }
    for (const name of opts?.unset ?? []) {
      state.fields.set(name, 'unset')
      state.resolved.delete(name)
      patchKinds.push('unset')
    }
    state.operations.push({ operationId, patchKinds, sourceRef: opts?.sourceRef })
    state.revision += 1 // a same-value re-select is still a NEW operation
    return { operationId, patchKinds, state: 'pending' }
  }

  return {
    readConfig: async target => {
      try {
        return { kind: 'ok', value: snapshotOf(target) }
      } catch (error) {
        return { kind: 'unavailable', reason: String(error) }
      }
    },

    submitConfigOperation: async (target, patch, opts) => {
      try {
        return { kind: 'ok', value: submitConfigOperationNow(target, patch, opts) }
      } catch (error) {
        return { kind: 'unavailable', reason: String(error) }
      }
    },

    readConfigSync: snapshotOf,
    listSessionsSync: target => [...targetState(target).sessions.values()],
    submitConfigOperationSync: submitConfigOperationNow,

    submitInput: async (target, draftRevision, capture) => {
      try {
        const state = targetState(target)
        seq += 1
        const submissionId = `sub-${target}-${seq}`
        const queryRequestKey = `req-${submissionId}`
        state.dispatchCounts.set(queryRequestKey,
          (state.dispatchCounts.get(queryRequestKey) ?? 0) + 1) // exactly one dispatch, ever
        const outcome = String(capture?.outcome ?? 'accepted') as SubmissionOutcome['outcome']
        const receipt: SubmissionOutcome = outcome === 'unknown'
          ? { submissionId, outcome: 'unknown', queryRequestKey, resend: false }
          : { submissionId, outcome, consumedDraftRevision: draftRevision }
        state.submissions.set(submissionId, receipt)
        return { kind: 'ok', value: receipt }
      } catch (error) {
        return { kind: 'unavailable', reason: String(error) }
      }
    },

    listSessions: async target => {
      try {
        return { kind: 'ok', value: [...targetState(target).sessions.values()] }
      } catch (error) {
        return { kind: 'unavailable', reason: String(error) }
      }
    },

    queryRun: async (target, runId) => {
      try {
        const run = targetState(target).runs.get(runId)
        // parity with the wire face: an undecided run is the unknown arm with
        // the same queryHint string the Agent plugin emits
        return run === undefined
          ? { kind: 'unknown', queryHint: `run:${runId}` }
          : { kind: 'ok', value: run }
      } catch (error) {
        return { kind: 'unavailable', reason: String(error) }
      }
    },

    reportEvidenceFrame(target, frame) {
      const state = targetState(target)
      const intake = state.evidence.intake(frame)
      if (intake.status === 'applied') {
        // only a settled frame moves the owner's evidence fields
        const settled = state.evidence.getFields()
        for (const [name, value] of Object.entries(settled)) state.fields.set(name, value)
        state.observed = state.evidence.getObserved()
      }
      return intake
    },

    reportEvidence(target, observed, fields) {
      const state = targetState(target)
      if (!['native', 'unset', 'unknown'].includes(observed)) {
        throw new Error(`bad observed evidence ${String(observed)}`)
      }
      state.observed = observed
      for (const [name, value] of Object.entries(fields ?? {})) {
        if (!['known', 'unset', 'unknown'].includes(value)) {
          throw new Error(`bad field state ${String(value)}`)
        }
        state.fields.set(name, value)
      }
      // no revision bump: evidence is an observation, not an operation
    },

    reportSessions(target, entries) {
      const state = targetState(target)
      for (const [sessionId, fields] of Object.entries(entries)) {
        const record = { ...(state.sessions.get(sessionId) ?? {}), ...fields }
        state.sessions.set(sessionId, Object.freeze(record))
      }
    },

    dropSessions(target) {
      targetState(target).sessions.clear()
    },

    dispatchCount(target, submissionId) {
      return targetState(target).dispatchCounts.get(`req-${submissionId}`) ?? 0
    },

    reportRun(target, runId, runState, reason) {
      if (!['running', 'completed', 'cancelled', 'failed', 'unknown'].includes(runState)) {
        throw new Error(`bad run state ${String(runState)}`)
      }
      targetState(target).runs.set(runId, Object.freeze({ state: runState, reason: reason ?? null }))
    },
  }
}
