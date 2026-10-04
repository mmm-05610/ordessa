import {
  type FrontendSubmissionCapture,
  type FrontendSubmissionJournal,
  type FrontendSubmissionKey,
  type FrontendSubmissionRecord,
  type FrontendSubmissionResultObservation,
  type FrontendSubmissionStorageScope,
} from './frontend-submission-journal'
import {
  createWireSubmissionClient,
  type SubmissionDispatchAnswer,
  type WireSubmissionQuery,
} from './wire-submission'
import type { SubmissionOutcome, WireCall } from './owner-port'

export type DurableSubmissionAnswer = SubmissionDispatchAnswer
  | { readonly status: 'unavailable'; readonly reason: string }

export interface DurableSubmissionClient {
  /** Capture, durably spend, and dispatch one reliable request at most once. */
  submit(capture: FrontendSubmissionCapture): Promise<DurableSubmissionAnswer>
  /** Query only the original durable request identity; never dispatches. */
  reconcile(key: FrontendSubmissionKey): Promise<DurableSubmissionAnswer>
  /** Read records only from the requested durable principal scope. */
  list(scope: FrontendSubmissionStorageScope): Promise<readonly FrontendSubmissionRecord[]>
}

const queryHint = (requestId: string) => `submission:${requestId}`

function refusal(reason: string): DurableSubmissionAnswer {
  return { status: 'refused', reason }
}

function unknown(requestId: string, receipt?: SubmissionOutcome): DurableSubmissionAnswer {
  const hint = queryHint(requestId)
  return receipt !== undefined && receipt !== null
    ? { status: 'unknown', queryHint: hint, receipt }
    : { status: 'unknown', queryHint: hint }
}

function plainRecord(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function dataField(record: Record<string, unknown>, key: string): unknown {
  const property = Object.getOwnPropertyDescriptor(record, key)
  if (!property || !('value' in property)) {
    throw new TypeError(`Reliable submission ${key} is missing or an accessor`)
  }
  return property.value
}

function requiredText(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim() || value.trim() !== value) {
    throw new TypeError(`Reliable submission ${field} is missing or invalid`)
  }
  return value
}

function validGeneration(value: unknown): value is string | number {
  if (typeof value === 'string') return value.length > 0 && value.trim() === value
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function validateExpectedConditions(value: unknown): Readonly<Record<string, unknown>> {
  if (!plainRecord(value)) throw new TypeError('Reliable submission expected conditions are missing')
  const bindingValue = dataField(value, 'binding')
  if (!plainRecord(bindingValue)) throw new TypeError('Reliable submission native binding conditions are missing')
  for (const field of [
    'ownerRef', 'surfaceId', 'environment', 'environmentContextRevision', 'providerActivation',
  ]) {
    requiredText(dataField(bindingValue, field), `binding.${field}`)
  }
  requiredText(dataField(value, 'baseRevision'), 'baseRevision')
  requiredText(dataField(value, 'sourceRevision'), 'sourceRevision')
  requiredText(dataField(value, 'configOwnerRef'), 'configOwnerRef')
  return value
}

function requireProductionCapture(input: FrontendSubmissionCapture): void {
  if (!input || input.guarantee !== 'reliable') throw new TypeError('Reliable submission capture is required')
  requiredText(input.target, 'target')
  requiredText(input.key?.namespace, 'namespace')
  requiredText(input.key?.principalScope, 'principal scope')
  requiredText(input.key?.requestId, 'request ID')
  if (!validGeneration(input.generation)) throw new TypeError('Reliable submission generation is missing or invalid')
  if (typeof input.inputSchema !== 'string' || !input.inputSchema.trim() || input.inputSchema.trim() !== input.inputSchema) {
    throw new TypeError('Reliable submission input schema is missing')
  }
  if (input.submissionMode !== 'existing' && input.submissionMode !== 'createWithConfig') {
    throw new TypeError('Reliable submission mode is missing or unsupported')
  }
  if (!Array.isArray(input.draft?.attachmentIds) || !Array.isArray(input.draft?.attachmentRefs)
      || input.draft.attachmentIds.length !== input.draft.attachmentRefs.length) {
    throw new TypeError('Reliable submission requires captured attachment IDs and immutable references')
  }
  if (!plainRecord(input.binding)) throw new TypeError('Reliable submission native binding conditions are missing')
  if (dataField(input.binding, 'target') !== input.target
      || dataField(input.binding, 'generation') !== input.generation) {
    throw new TypeError('Reliable submission binding target or generation changed')
  }
  const conditions = validateExpectedConditions(dataField(input.binding, 'expectedConditions'))
  const nativeBinding = dataField(conditions, 'binding') as Record<string, unknown>
  if (dataField(nativeBinding, 'environment') !== input.key.namespace) {
    throw new TypeError('Reliable submission binding environment differs from its durable namespace')
  }
}

function requestFromRecord(record: FrontendSubmissionRecord) {
  const schema = record.inputSchema
  const mode = record.submissionMode
  const attachmentIds = record.draft.attachmentIds
  if (typeof schema !== 'string' || !schema.trim() || schema.trim() !== schema
      || (mode !== 'existing' && mode !== 'createWithConfig')
      || !Array.isArray(attachmentIds) || !Array.isArray(record.draft.attachmentRefs)
      || attachmentIds.length !== record.draft.attachmentRefs.length) {
    throw new TypeError('Durable submission record lacks required production capture fields')
  }
  if (!plainRecord(record.binding)
      || dataField(record.binding, 'target') !== record.target
      || dataField(record.binding, 'generation') !== record.generation) {
    throw new TypeError('Durable submission record lacks its matching captured binding')
  }
  const expectedConditions = validateExpectedConditions(dataField(record.binding, 'expectedConditions'))
  const nativeBinding = dataField(expectedConditions, 'binding') as Record<string, unknown>
  if (dataField(nativeBinding, 'environment') !== record.key.namespace) {
    throw new TypeError('Durable submission record conditions differ from their namespace')
  }
  return {
    target: record.target,
    snapshot: {
      submissionId: record.key.requestId,
      draftId: record.draft.draftId,
      draftRevision: record.draft.draftRevision,
      text: record.draft.text,
      attachmentIds: [...attachmentIds],
      attachmentRefs: [...record.draft.attachmentRefs],
    },
    configOperationIds: [...record.configOperationIds],
    schema,
    mode,
    expectedConditions,
  }
}

function queryFacts(value: WireSubmissionQuery): FrontendSubmissionResultObservation {
  return { outcome: value.outcome, facts: value }
}

export function createDurableSubmissionClient(options: {
  wire: WireCall
  journal: FrontendSubmissionJournal
}): DurableSubmissionClient {
  const wire = createWireSubmissionClient(options.wire)

  async function persistResult(
    key: FrontendSubmissionKey,
    result: FrontendSubmissionResultObservation,
  ): Promise<boolean> {
    try { return (await options.journal.recordResult(key, result)).status === 'recorded' }
    catch { return false }
  }

  async function reconcile(key: FrontendSubmissionKey): Promise<DurableSubmissionAnswer> {
    let record: FrontendSubmissionRecord | undefined
    try { record = await options.journal.get(key) }
    catch (error) { return { status: 'unavailable', reason: `Submission journal unavailable: ${String(error)}` } }
    if (!record) return { status: 'unavailable', reason: 'Original durable submission key is missing' }

    let answer
    try { answer = await wire.query(record.target, record.key.requestId) }
    catch { return unknown(record.key.requestId) }
    if (answer.kind === 'unavailable') return { status: 'unavailable', reason: answer.reason }
    if (answer.kind === 'unknown') {
      const facts = answer.observed === undefined ? undefined : answer.observed
      await persistResult(record.key, {
        outcome: 'unknown', ...(facts === undefined ? {} : { facts }),
      })
      return unknown(record.key.requestId)
    }

    const facts = answer.value
    const saved = await persistResult(record.key, queryFacts(facts))
    if (!saved) return unknown(record.key.requestId)
    if (facts.outcome === 'accepted') {
      return { status: 'accepted', receipt: {
        submissionId: record.key.requestId, outcome: 'accepted',
      } }
    }
    if (facts.outcome === 'known-rejected') {
      return { status: 'refused', reason: 'Agent confirmed the original submission was rejected', receipt: {
        submissionId: record.key.requestId, outcome: 'known-rejected',
      } }
    }
    return unknown(record.key.requestId)
  }

  async function submit(input: FrontendSubmissionCapture): Promise<DurableSubmissionAnswer> {
    try { requireProductionCapture(input) }
    catch (error) { return refusal(String(error)) }

    // `capture` freezes synchronously before its first storage await. All later work
    // uses its committed immutable record, never the caller's mutable object.
    let captured
    try { captured = await options.journal.capture(input) }
    catch (error) { return refusal(`Submission mapping could not be committed: ${String(error)}`) }
    if (captured.status === 'conflict') return refusal('Submission key conflicts with an existing captured request')
    if (captured.status === 'existing') return reconcile(captured.record.key)

    const record = captured.record
    let claim
    try { claim = await options.journal.markPossiblySubmitted(record.key) }
    catch {
      return unknown(record.key.requestId)
    }
    if (claim.status !== 'dispatch-authorized') {
      if (claim.status === 'missing') return { status: 'unavailable', reason: 'Captured submission disappeared before dispatch claim' }
      return reconcile(claim.record?.key ?? record.key)
    }

    // The durable possibly-submitted marker has committed. From this point forward
    // every branch is query-only unless this exact claim authorized its one call.
    let dispatch: SubmissionDispatchAnswer
    try { dispatch = await wire.submit(requestFromRecord(claim.record)) }
    catch { return unknown(record.key.requestId) }

    let result: FrontendSubmissionResultObservation
    let answer: DurableSubmissionAnswer
    if (dispatch.status === 'accepted') {
      result = { outcome: 'accepted', facts: dispatch.receipt }
      answer = dispatch
    } else if (dispatch.status === 'refused' && dispatch.receipt?.outcome === 'known-rejected'
        && dispatch.receipt.submissionId === record.key.requestId) {
      result = { outcome: 'known-rejected', facts: dispatch.receipt }
      answer = dispatch
    } else {
      const facts = dispatch.status === 'refused'
        ? { wireStatus: 'refused', reason: dispatch.reason }
        : dispatch.receipt === undefined ? undefined : dispatch.receipt
      result = { outcome: 'unknown', ...(facts === undefined ? {} : { facts }) }
      answer = unknown(record.key.requestId, dispatch.status === 'unknown' ? dispatch.receipt : undefined)
    }
    if (!await persistResult(record.key, result)) return unknown(record.key.requestId)
    return answer
  }

  async function list(scope: FrontendSubmissionStorageScope): Promise<readonly FrontendSubmissionRecord[]> {
    return options.journal.list(scope)
  }

  return Object.freeze({ submit, reconcile, list })
}
