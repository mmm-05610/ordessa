/** Public connector-side shape for a backend-owned next-submit admission.
 *
 * The backend authenticates the principal and owns the one-use permit and
 * channel/generation fence. This DTO carries no permit or secret to the renderer.
 */
export interface AcpAttachmentReference {
  readonly name: string
  readonly uri: string
  readonly mimeType?: string
  readonly sha256: string
}

export interface AcpControlledSubmission {
  readonly submissionId: string
  readonly nativeSessionId: string
  readonly text: string
  readonly attachments: readonly AcpPreparedAttachment[]
  readonly configurationDigest: string
  /** Catalog identity only. A leading slash in text remains literal user input. */
  readonly commandId?: string
}

export type AcpSubmissionAdmission =
  | { readonly kind: 'accepted'; readonly submissionId: string }
  | { readonly kind: 'refused'; readonly code: string; readonly reason: string }
  | { readonly kind: 'unknown'; readonly operationId: string; readonly reason: string }

export interface AcpPermissionDecision {
  readonly nativeSessionId: string
  readonly interactionId: string
  readonly runId: string
  readonly optionId: string
}

export function validateControlledSubmission(value: AcpControlledSubmission): void {
  if (!value.submissionId || !value.nativeSessionId || !value.configurationDigest || typeof value.text !== 'string'
    || !Array.isArray(value.attachments) || value.attachments.some(item =>
      !item.name || !item.uri || !/^[0-9a-f]{64}$/.test(item.sha256)
      || (item.mimeType !== undefined && !item.mimeType))) {
    throw new Error('ACP controlled submission is incomplete')
  }
  if (value.commandId !== undefined && !value.commandId) throw new Error('ACP command identity is empty')
}
import type { AcpPreparedAttachment } from './attachments'
