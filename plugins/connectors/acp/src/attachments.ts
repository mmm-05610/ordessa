/** Connector-local content preparation seam. The channel owner supplies the port;
 * no renderer path or metadata object is proof that bytes were prepared. */
export interface AcpAttachmentTarget {
  readonly serverInstanceId: string
  readonly connectionId: string
  readonly projectId: string
  readonly nativeSessionId: string
}

export interface AcpPreparedAttachment {
  /** Opaque owner-issued identity. The Server ACP DTO currently does not carry it. */
  readonly preparedId: string
  readonly name: string
  readonly uri: string
  readonly mimeType: string
  readonly sha256: string
  readonly byteLength: number
}

export type AcpAttachmentCapabilities =
  | { readonly kind: 'available'; readonly mimeTypes: readonly string[]; readonly uriSchemes: readonly string[];
      readonly maxBytes: number; readonly maxCount: number }
  | { readonly kind: 'absent' | 'unknown'; readonly reason: string }

export type AcpAttachmentPreparation =
  | { readonly kind: 'prepared'; readonly reference: AcpPreparedAttachment }
  | { readonly kind: 'refused'; readonly reason: string }
  | { readonly kind: 'unknown'; readonly operationId: string }

export type AcpAttachmentVerification =
  | { readonly kind: 'verified'; readonly reference: AcpPreparedAttachment }
  | { readonly kind: 'refused'; readonly reason: string }
  | { readonly kind: 'unknown'; readonly operationId: string }

export interface AcpAttachmentPreparePort {
  capabilities(target: AcpAttachmentTarget): Promise<AcpAttachmentCapabilities>
  /** sourceId names content already owned by this port, never a renderer filesystem path. */
  prepare(target: AcpAttachmentTarget, sourceId: string, idempotencyKey: string): Promise<AcpAttachmentPreparation>
  verify(target: AcpAttachmentTarget, reference: AcpPreparedAttachment): Promise<AcpAttachmentVerification>
  release(target: AcpAttachmentTarget, preparedId: string): Promise<void>
}

export function validPreparedReference(value: unknown): value is AcpPreparedAttachment {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const ref = value as Record<string, unknown>
  return typeof ref.preparedId === 'string' && !!ref.preparedId
    && typeof ref.name === 'string' && !!ref.name
    && typeof ref.uri === 'string' && /^[a-z][a-z0-9+.-]*:/i.test(ref.uri) && !/^file:/i.test(ref.uri)
    && typeof ref.mimeType === 'string' && !!ref.mimeType
    && typeof ref.sha256 === 'string' && /^[0-9a-f]{64}$/.test(ref.sha256)
    && typeof ref.byteLength === 'number' && Number.isSafeInteger(ref.byteLength) && ref.byteLength > 0
}

export function referenceScheme(uri: string): string | undefined {
  return /^[a-z][a-z0-9+.-]*:/i.exec(uri)?.[0].toLowerCase()
}

export function samePreparedReference(a: AcpPreparedAttachment, b: AcpPreparedAttachment): boolean {
  return a.preparedId === b.preparedId && a.name === b.name && a.uri === b.uri
    && a.mimeType === b.mimeType && a.sha256 === b.sha256 && a.byteLength === b.byteLength
}
