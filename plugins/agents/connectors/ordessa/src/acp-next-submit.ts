/** Native-side request coordinator for the Server's ACP admission method.
 *
 * No renderer frame is routed here. The missing producer is a backend owner
 * that can observe the live ACP channel, native session, generation, Q5
 * authority and Chat API publication. Until that producer exists, `state`
 * must return undefined and every request refuses before HTTP. This client
 * neither creates a permit nor authorizes a frontend claim.
 */
import { WireError } from './wire'

export interface AcpAttachmentReference {
  readonly name: string
  readonly uri: string
  readonly sha256: string
  readonly mimeType?: string
}

export interface AcpNextSubmission {
  readonly submissionId: string
  readonly nativeSessionId: string
  readonly text: string
  readonly attachments: readonly AcpAttachmentReference[]
  readonly configurationDigest: string
  /** Catalog ID only; a leading slash in text is always literal text. */
  readonly commandId?: string
}

export type AcpAdmissionOutcome =
  | { readonly kind: 'accepted'; readonly submissionId: string }
  | { readonly kind: 'refused'; readonly code: string; readonly reason: string }
  | { readonly kind: 'unknown'; readonly operationId: string; readonly reason: string }

/** Only a backend owner may supply these observed facts. They are never a renderer request. */
export interface BackendAdmissionState {
  readonly connectionId: string
  readonly nativeSessionId: string
  readonly runtimeGeneration: number
  readonly admissionSupported: boolean
  readonly q5Ready: boolean
  readonly chatApiReady: boolean
  readonly outputInProgress: boolean
}

export interface AcpAdmissionWire {
  call<Result>(method: string, params: Record<string, unknown>): Promise<Result>
}

const sha256 = (value: unknown): value is string => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value)
const nonempty = (value: unknown): value is string => typeof value === 'string' && value.length > 0
const refused = (code: string, reason: string): AcpAdmissionOutcome => ({ kind: 'refused', code, reason })

function frozenSubmission(value: AcpNextSubmission): AcpNextSubmission {
  if (!nonempty(value.submissionId) || !nonempty(value.nativeSessionId) || typeof value.text !== 'string'
    || !sha256(value.configurationDigest) || !Array.isArray(value.attachments)
    || (value.commandId !== undefined && !nonempty(value.commandId))) {
    throw new Error('ACP submission snapshot is invalid')
  }
  const attachments = value.attachments.map(item => {
    if (!nonempty(item.name) || !nonempty(item.uri) || !sha256(item.sha256)
      || (item.mimeType !== undefined && !nonempty(item.mimeType))) {
      throw new Error('ACP attachment reference is invalid')
    }
    return Object.freeze({ name: item.name, uri: item.uri, sha256: item.sha256,
      ...(item.mimeType === undefined ? {} : { mimeType: item.mimeType }) })
  })
  return Object.freeze({ submissionId: value.submissionId, nativeSessionId: value.nativeSessionId,
    text: value.text, attachments: Object.freeze(attachments), configurationDigest: value.configurationDigest,
    ...(value.commandId === undefined ? {} : { commandId: value.commandId }) })
}

function admissionResult(value: unknown): AcpAdmissionOutcome | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const result = value as Record<string, unknown>
  const hasOnly = (...keys: string[]) => {
    const actual = Object.keys(result)
    return actual.length === keys.length && actual.every(key => keys.includes(key))
  }
  if (result.kind === 'accepted' && hasOnly('kind', 'submissionId') && nonempty(result.submissionId)) {
    return { kind: 'accepted', submissionId: result.submissionId }
  }
  if (result.kind === 'refused' && hasOnly('kind', 'code', 'reason')
    && nonempty(result.code) && nonempty(result.reason)) {
    return { kind: 'refused', code: result.code, reason: result.reason }
  }
  if (result.kind === 'unknown' && hasOnly('kind', 'operationId', 'reason')
    && nonempty(result.operationId) && nonempty(result.reason)) {
    return { kind: 'unknown', operationId: result.operationId, reason: result.reason }
  }
  return undefined
}

export class AcpNextSubmitCoordinator {
  private readonly attempted = new Set<string>()

  constructor(private readonly wire: AcpAdmissionWire,
    private readonly state: () => BackendAdmissionState | undefined) {}

  /** Within this coordinator instance, never resend after a lost answer,
   * reconnect or duplicate ID. Cross-process replay needs a future durable
   * backend journal; this instance-local Set makes no such claim. */
  async submit(input: AcpNextSubmission): Promise<AcpAdmissionOutcome> {
    let submission: AcpNextSubmission
    try { submission = frozenSubmission(input) }
    catch { return refused('INVALID_REQUEST', 'ACP submission snapshot is invalid') }
    if (this.attempted.has(submission.submissionId)) {
      return { kind: 'unknown', operationId: submission.submissionId,
        reason: 'prior ACP admission requires backend reconciliation' }
    }
    let observed: BackendAdmissionState | undefined
    try { observed = this.state() }
    catch { return refused('CAPABILITY_UNSUPPORTED', 'ACP backend admission state is unavailable') }
    if (!observed || !observed.admissionSupported || !observed.q5Ready || !observed.chatApiReady) {
      return refused('CAPABILITY_UNSUPPORTED', 'ACP backend admission dependencies are unavailable')
    }
    if (!nonempty(observed.connectionId) || !nonempty(observed.nativeSessionId)
      || !Number.isSafeInteger(observed.runtimeGeneration) || observed.runtimeGeneration < 0
      || observed.nativeSessionId !== submission.nativeSessionId) {
      return refused('AUTHORIZATION_REFUSED', 'ACP backend channel evidence is missing or changed')
    }
    if (observed.outputInProgress) return refused('BUSY', 'ACP output is still in progress')
    // Reserve before the external call. A lost response is Unknown, never an invitation to resend.
    this.attempted.add(submission.submissionId)
    try {
      const result = admissionResult(await this.wire.call<unknown>('acp.submission.authorize', {
        connectionId: observed.connectionId, submission,
      }))
      if (result?.kind === 'accepted' && result.submissionId !== submission.submissionId) {
        return { kind: 'unknown', operationId: submission.submissionId,
          reason: 'ACP admission returned a different submission identity' }
      }
      return result ?? { kind: 'unknown', operationId: submission.submissionId,
        reason: 'ACP admission returned an unrecognized result' }
    } catch (error) {
      if (error instanceof WireError && !['UNAVAILABLE', 'WORKER_UNREACHABLE', 'OUTCOME_UNKNOWN'].includes(error.code)) {
        return refused(error.code, 'ACP admission was refused by the Server')
      }
      return { kind: 'unknown', operationId: submission.submissionId,
        reason: 'ACP admission outcome requires backend reconciliation' }
    }
  }
}
