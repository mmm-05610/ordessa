import { createAgentOwnerPort, type WireCall } from './owner-port'
import type { SubmissionOutcome } from './owner-port'

/** Structural subset of ChatSubmissionSnapshot used by the Agent boundary.
 * Kept structural to preserve the dependency direction: Chat consumes Agent. */
export interface ChatSubmissionCaptureDto {
  readonly submissionId: string
  readonly draftId: string
  readonly draftRevision: number
  readonly text: string
  readonly attachmentIds: readonly string[]
  readonly attachmentRefs?: readonly string[]
}

export type AgentSubmissionMode = 'existing' | 'createWithConfig'

export interface WireSubmissionRequest {
  /** Backend-issued canonical Agent target; this helper never derives it from ChatLocation. */
  readonly target: string
  readonly snapshot: ChatSubmissionCaptureDto
  /** Exact pending operation IDs from the Agent configuration projection. */
  readonly configOperationIds: readonly string[]
  /** Declared input schema supplied by the composing product. */
  readonly schema: string
  readonly mode: AgentSubmissionMode
  /** Read-only trusted conditions captured earlier, used solely for server-side comparison. */
  readonly expectedConditions?: Readonly<Record<string, unknown>>
}

export type WireSubmissionQuery = Readonly<Record<string, unknown>> & {
  readonly submissionId: string
  readonly outcome: 'accepted' | 'known-rejected' | 'unknown'
  readonly resend?: false
}

export type SubmissionQueryAnswer =
  | { readonly kind: 'ok'; readonly value: WireSubmissionQuery }
  | { readonly kind: 'unknown'; readonly queryHint: string; readonly observed?: Readonly<Record<string, unknown>> }
  | { readonly kind: 'unavailable'; readonly reason: string }

export type SubmissionDispatchAnswer =
  | { readonly status: 'accepted'; readonly receipt: SubmissionOutcome }
  | { readonly status: 'refused'; readonly reason: string; readonly receipt?: SubmissionOutcome }
  | { readonly status: 'unknown'; readonly queryHint: string; readonly receipt?: SubmissionOutcome }

export interface WireSubmissionClient {
  /** One reliable submitInput call. An unknown result is returned as unknown; callers query it. */
  submit(request: WireSubmissionRequest): Promise<SubmissionDispatchAnswer>
  /** Read the exact original submission identity. This method never submits or mints an ID. */
  query(target: string, submissionId: string): Promise<SubmissionQueryAnswer>
}

function refusal(reason: string) {
  return { status: 'refused' as const, reason }
}

function copyCapture(request: WireSubmissionRequest): {
  readonly submissionId: string
  readonly draft: Readonly<Record<string, unknown>>
  readonly configOperationIds: readonly string[]
  readonly schema: string
  readonly mode: AgentSubmissionMode
  readonly expectedConditions?: Readonly<Record<string, unknown>>
} | { readonly error: string } {
  const snapshot = request.snapshot
  if (!request.target || !snapshot?.submissionId || snapshot.submissionId.trim() !== snapshot.submissionId
    || request.target.trim() !== request.target
    || !snapshot.draftId || snapshot.draftId.trim() !== snapshot.draftId
    || !Number.isSafeInteger(snapshot.draftRevision) || snapshot.draftRevision < 0
    || typeof snapshot.text !== 'string' || typeof request.schema !== 'string'
    || !request.schema.trim() || request.schema.trim() !== request.schema) {
    return { error: 'Submission capture is incomplete' }
  }
  if (request.mode !== 'existing' && request.mode !== 'createWithConfig') {
    return { error: 'Reliable submission mode is unsupported' }
  }
  if (!Array.isArray(snapshot.attachmentIds) || !Array.isArray(request.configOperationIds)
    || !snapshot.attachmentIds.every(id => typeof id === 'string' && id.length > 0)
    || new Set(snapshot.attachmentIds).size !== snapshot.attachmentIds.length
    || !request.configOperationIds.every(id => typeof id === 'string' && id.length > 0)
    || new Set(request.configOperationIds).size !== request.configOperationIds.length) {
    return { error: 'Submission capture identifiers are malformed' }
  }
  const attachmentRefs = snapshot.attachmentRefs
  if (attachmentRefs !== undefined && (!Array.isArray(attachmentRefs)
    || attachmentRefs.some(reference => typeof reference !== 'string' || !reference))) {
    return { error: 'Prepared attachment references are malformed' }
  }
  if ((snapshot.attachmentIds.length > 0 || (attachmentRefs?.length ?? 0) > 0)
    && (!attachmentRefs || attachmentRefs.length !== snapshot.attachmentIds.length)) {
    return { error: 'Reliable attachment submission requires one immutable reference per captured item' }
  }
  const immutableAttachmentIds = Object.freeze([...(attachmentRefs ?? [])])
  let expectedConditions: Readonly<Record<string, unknown>> | undefined
  if (request.expectedConditions !== undefined) {
    const copied = freezeWireValue(request.expectedConditions)
    if (copied === INVALID_WIRE_VALUE || copied === null || typeof copied !== 'object' || Array.isArray(copied)) {
      return { error: 'Submission expected conditions are malformed' }
    }
    expectedConditions = copied as Readonly<Record<string, unknown>>
  }
  const draft = Object.freeze({
    draftId: snapshot.draftId,
    draftRevision: snapshot.draftRevision,
    text: snapshot.text,
    // The backend resolves these immutable service references to bytes. Chat item IDs
    // remain local bookkeeping and are never sent as content locators.
    attachmentIds: immutableAttachmentIds,
  })
  return Object.freeze({
    submissionId: snapshot.submissionId,
    draft,
    configOperationIds: Object.freeze([...request.configOperationIds]),
    schema: request.schema,
    mode: request.mode,
    ...(expectedConditions === undefined ? {} : { expectedConditions }),
  })
}

function freezeReceipt(value: SubmissionOutcome): SubmissionOutcome {
  return Object.freeze({ ...value })
}

const INVALID_WIRE_VALUE = Symbol('invalid-wire-value')

function freezeWireValue(value: unknown, ancestors = new WeakSet<object>()): unknown | typeof INVALID_WIRE_VALUE {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return value
  if (typeof value === 'number') return Number.isFinite(value) ? value : INVALID_WIRE_VALUE
  if (typeof value !== 'object') return INVALID_WIRE_VALUE
  if (ancestors.has(value)) return INVALID_WIRE_VALUE
  ancestors.add(value)
  try {
    if (Array.isArray(value)) {
      const items: unknown[] = []
      for (const item of value) {
        const copied = freezeWireValue(item, ancestors)
        if (copied === INVALID_WIRE_VALUE) return INVALID_WIRE_VALUE
        items.push(copied)
      }
      return Object.freeze(items)
    }
    const prototype = Object.getPrototypeOf(value)
    if (prototype !== Object.prototype && prototype !== null) return INVALID_WIRE_VALUE
    if (Object.getOwnPropertySymbols(value).length !== 0) return INVALID_WIRE_VALUE
    const copied: Record<string, unknown> = {}
    for (const key of Object.keys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key)
      if (!descriptor || !('value' in descriptor)) return INVALID_WIRE_VALUE
      const nested = freezeWireValue(descriptor.value, ancestors)
      if (nested === INVALID_WIRE_VALUE) return INVALID_WIRE_VALUE
      copied[key] = nested
    }
    return Object.freeze(copied)
  } finally {
    ancestors.delete(value)
  }
}

/** Wire consumer for the real Agent SubmissionOwner. No local owner, request ledger,
 * generated target, alternate key, or raw-send fallback is provided. */
export function createWireSubmissionClient(wire: WireCall): WireSubmissionClient {
  const owner = createAgentOwnerPort(wire)

  async function submit(request: WireSubmissionRequest) {
    let capture: ReturnType<typeof copyCapture>
    try { capture = copyCapture(request) }
    catch { return refusal('Submission capture is malformed') }
    if ('error' in capture) return refusal(capture.error)
    try {
      const answer = await owner.submitInput(request.target, capture.draft.draftRevision as number, capture)
      const queryHint = `submission:${capture.submissionId}`
      if (answer.kind === 'unknown') return { status: 'unknown' as const, queryHint }
      if (answer.kind === 'unavailable') return refusal(answer.reason)
      const raw = answer.value as SubmissionOutcome
      const receipt = raw && typeof raw === 'object' && typeof raw.submissionId === 'string'
        && (raw.outcome === 'accepted' || raw.outcome === 'known-rejected' || raw.outcome === 'unknown')
        && (raw.resend === undefined || raw.resend === false) ? freezeReceipt(raw) : undefined
      if (!receipt) return { status: 'unknown' as const, queryHint }
      if (receipt.submissionId !== capture.submissionId) {
        return { status: 'unknown' as const, queryHint, receipt }
      }
      if (receipt.outcome === 'accepted') return { status: 'accepted' as const, receipt }
      if (receipt.outcome === 'known-rejected') return { ...refusal('Agent confirmed the submission was rejected'), receipt }
      if (receipt.outcome === 'unknown') return { status: 'unknown' as const, queryHint, receipt }
      return { status: 'unknown' as const, queryHint, receipt }
    } catch {
      // A rejected transport promise may follow an external effect. Only the owner
      // can prove refusal; preserve uncertainty and require query by the same ID.
      return { status: 'unknown' as const, queryHint: `submission:${capture.submissionId}` }
    }
  }

  async function query(target: string, submissionId: string): Promise<SubmissionQueryAnswer> {
    if (!target || target.trim() !== target || !submissionId || submissionId.trim() !== submissionId) {
      return { kind: 'unavailable', reason: 'Target and original submission ID are required' }
    }
    let answer: Awaited<ReturnType<WireCall>>
    try {
      answer = await wire('agent.submission.query', { target, submissionId })
    } catch {
      return { kind: 'unknown', queryHint: `submission:${submissionId}` }
    }
    if (answer.kind === 'Unknown') return { kind: 'unknown', queryHint: `submission:${submissionId}` }
    if (answer.kind === 'Refused') return { kind: 'unavailable', reason: answer.reason }
    let frozen: unknown | typeof INVALID_WIRE_VALUE
    try { frozen = freezeWireValue(answer.result) }
    catch { return { kind: 'unknown', queryHint: `submission:${submissionId}` } }
    if (frozen === INVALID_WIRE_VALUE || frozen === null || typeof frozen !== 'object' || Array.isArray(frozen)) {
      return { kind: 'unknown', queryHint: `submission:${submissionId}` }
    }
    const record = frozen as Readonly<Record<string, unknown>>
    if (record.submissionId !== submissionId
      || (record.outcome !== 'accepted' && record.outcome !== 'known-rejected' && record.outcome !== 'unknown')
      || (record.resend !== undefined && record.resend !== false)) {
      return { kind: 'unknown', queryHint: `submission:${submissionId}`, observed: record }
    }
    if (record.outcome === 'unknown') {
      return { kind: 'unknown', queryHint: `submission:${submissionId}`, observed: record }
    }
    return { kind: 'ok', value: record as WireSubmissionQuery }
  }

  return Object.freeze({ submit, query })
}
