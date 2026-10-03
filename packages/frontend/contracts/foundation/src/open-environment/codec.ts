/**
 * Canonical wire codec — TypeScript mirror of
 * `ordessa_environment_api.codec` (spec 026 order 002 freeze).
 *
 * Byte-identity rules (see the Python docstring for the authoritative text):
 *  1. keys sorted by UTF-16 code unit — `Object.keys(v).sort()`;
 *  2. no whitespace: `JSON.stringify` with a canonicalizer that inserts no
 *     spaces and never uses non-ASCII escapes for the BMP ids used here;
 *  3. unknown envelope keys / unknown contract versions are decode errors;
 *  4. construction order never leaks into the wire form.
 *
 * `JSON.stringify` alone is NOT canonical (insertion order leaks); we build
 * sorted objects recursively before serializing.
 */

export const CONTRACT_VERSION = 'oe-contract/1'

export class CodecError extends Error {
  readonly code = 'CODEC_ERROR'
}

type Plain = null | boolean | number | string | Plain[] | { [k: string]: Plain }

function isPlainArray(v: unknown): v is Plain[] {
  return Array.isArray(v) && (v as unknown[]).every(isPlainValue)
}

function isPlainObject(v: unknown): v is { [k: string]: Plain } {
  return (
    typeof v === 'object' && v !== null && !Array.isArray(v) &&
    Object.values(v).every(isPlainValue)
  )
}

function isPlainValue(v: unknown): v is Plain {
  return v === null || ['boolean', 'number', 'string'].includes(typeof v) ||
    isPlainArray(v) || isPlainObject(v)
}

function canonicalize(value: Plain): Plain {
  if (Array.isArray(value)) return value.map(canonicalize)
  if (value !== null && typeof value === 'object') {
    const out: { [k: string]: Plain } = {}
    for (const key of Object.keys(value).sort()) {
      out[key] = canonicalize((value as { [k: string]: Plain })[key])
    }
    return out
  }
  return value
}

/** Deterministic encoding — equal values produce identical bytes. */
export function canonicalJson(value: Plain): string {
  if (!isPlainValue(value)) throw new CodecError('value is not canonically encodable')
  return JSON.stringify(canonicalize(value))
}

export interface Envelope {
  contractVersion: string
  kind: string
  payload: Plain
}

export function encodeEnvelope(kind: string, payload: Plain): string {
  if (typeof kind !== 'string' || kind.length === 0) throw new CodecError('envelope kind is required')
  if (!isPlainValue(payload)) throw new CodecError('payload is not canonically encodable')
  return canonicalJson({ contractVersion: CONTRACT_VERSION, kind, payload } as unknown as Plain)
}

export function decodeEnvelope(text: string, expectedKind?: string): Envelope {
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (error) {
    throw new CodecError(`not JSON: ${String(error)}`)
  }
  if (!isPlainObject(parsed)) throw new CodecError('envelope must be an object')
  const keys = Object.keys(parsed).sort()
  if (keys.join(',') !== 'contractVersion,kind,payload') {
    throw new CodecError(`envelope keys must be exactly the frozen set, got ${keys.join(',')}`)
  }
  const value = parsed as unknown as { contractVersion: Plain; kind: Plain; payload: Plain }
  if (value.contractVersion !== CONTRACT_VERSION) {
    throw new CodecError(`contract version ${String(value.contractVersion)} != expected ${CONTRACT_VERSION}`)
  }
  if (typeof value.kind !== 'string' || value.kind.length === 0) {
    throw new CodecError('envelope kind must be a non-empty string')
  }
  if (expectedKind !== undefined && value.kind !== expectedKind) {
    throw new CodecError(`kind ${value.kind} != expected ${expectedKind}`)
  }
  return { contractVersion: CONTRACT_VERSION, kind: value.kind, payload: value.payload }
}
