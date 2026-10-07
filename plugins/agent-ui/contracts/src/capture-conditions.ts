/**
 * Synchronous, fail-closed capture of backend submission conditions.
 *
 * The backend descriptor is read during location prewarm. A capture is valid
 * only while it still belongs to the same location, wire scope and generation,
 * and while the live configuration projection has the exact owner/revision the
 * backend described. This cache contains no configuration values and performs
 * no wire calls or effects.
 */

export interface SubmissionConditionsLocation {
  readonly wireScope: string
  readonly generation: string | number
  readonly target: string
}

export interface SubmissionConditionsProjection extends SubmissionConditionsLocation {
  readonly ownerRef: string
  readonly revision: string | number
}

export interface SubmissionConditionsBinding extends Readonly<Record<string, string>> {
  readonly ownerRef: string
  readonly surfaceId: string
  readonly environment: string
  readonly environmentContextRevision: string
  readonly providerActivation: string
}

export interface SubmissionConditions {
  readonly binding: SubmissionConditionsBinding
  readonly baseRevision: string
  readonly sourceRevision: string
  readonly configOwnerRef: string
}

type ReadToken = object

interface ActiveRead {
  readonly token: ReadToken
  readonly location: SubmissionConditionsLocation
  conditions?: SubmissionConditions
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function dataField(record: Record<string, unknown>, key: string): unknown {
  const property = Object.getOwnPropertyDescriptor(record, key)
  if (!property || !('value' in property)) {
    throw new TypeError(`submission conditions ${key} is missing or an accessor`)
  }
  return property.value
}

function requiredText(value: unknown, name: string): string {
  if (typeof value !== 'string' || value.length === 0 || value.trim() !== value) {
    throw new TypeError(`submission conditions ${name} must be a non-empty string`)
  }
  return value
}

function validGeneration(value: unknown): value is string | number {
  if (typeof value === 'string') return value.length > 0 && value.trim() === value
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
}

function validateLocation(location: SubmissionConditionsLocation): SubmissionConditionsLocation {
  if (!location || typeof location !== 'object') throw new TypeError('submission conditions location is required')
  const wireScope = requiredText(location.wireScope, 'wire scope')
  const target = requiredText(location.target, 'target')
  if (!validGeneration(location.generation)) throw new TypeError('submission conditions generation is invalid')
  return Object.freeze({ wireScope, target, generation: location.generation })
}

function freezeDescriptor(raw: unknown): SubmissionConditions {
  if (!isPlainRecord(raw)) throw new TypeError('submission conditions descriptor must be a plain object')
  const rawBinding = dataField(raw, 'binding')
  if (!isPlainRecord(rawBinding)) throw new TypeError('submission conditions binding is unavailable')

  const binding: Record<string, string> = Object.create(null)
  for (const key of Reflect.ownKeys(rawBinding)) {
    if (typeof key !== 'string') throw new TypeError('submission conditions binding has an invalid key')
    const property = Object.getOwnPropertyDescriptor(rawBinding, key)
    if (!property || !('value' in property)) {
      throw new TypeError('submission conditions binding contains an accessor')
    }
    binding[key] = requiredText(property.value, `binding.${key}`)
  }

  for (const field of [
    'ownerRef', 'surfaceId', 'environment', 'environmentContextRevision', 'providerActivation',
  ]) {
    requiredText(binding[field], `binding.${field}`)
  }

  return Object.freeze({
    binding: Object.freeze(binding) as SubmissionConditionsBinding,
    baseRevision: requiredText(dataField(raw, 'baseRevision'), 'baseRevision'),
    sourceRevision: requiredText(dataField(raw, 'sourceRevision'), 'sourceRevision'),
    configOwnerRef: requiredText(dataField(raw, 'configOwnerRef'), 'configOwnerRef'),
  })
}

function sameLocation(left: SubmissionConditionsLocation, right: SubmissionConditionsLocation): boolean {
  return left.wireScope === right.wireScope
    && left.generation === right.generation
    && left.target === right.target
}

/**
 * Cache one read-only backend descriptor per location. Beginning a newer read
 * immediately invalidates that location's old descriptor; only the latest
 * opaque token can complete it.
 */
export function createSubmissionConditionsCache() {
  const active = new Map<string, ActiveRead>()
  const tokens = new WeakMap<object, string>()

  function begin(locationKey: string, input: SubmissionConditionsLocation): ReadToken {
    const key = requiredText(locationKey, 'location key')
    const location = validateLocation(input)
    const token = Object.freeze({})
    active.set(key, { token, location })
    tokens.set(token, key)
    return token
  }

  function complete(token: ReadToken, rawBackendDescriptor: unknown): boolean {
    if ((typeof token !== 'object' && typeof token !== 'function') || token === null) return false
    const key = tokens.get(token)
    if (key === undefined) return false
    const read = active.get(key)
    if (!read || read.token !== token) return false
    const conditions = freezeDescriptor(rawBackendDescriptor)
    // Descriptor validation is synchronous, but retain the latest-token check
    // next to the write so this remains correct if validation later gains hooks.
    if (active.get(key) !== read) return false
    read.conditions = conditions
    return true
  }

  function capture(locationKey: string, input: SubmissionConditionsProjection): SubmissionConditions {
    const key = requiredText(locationKey, 'location key')
    const read = active.get(key)
    if (!read?.conditions) throw new Error('submission conditions are unavailable')
    const current = validateLocation(input)
    if (!sameLocation(read.location, current)) {
      throw new Error('submission conditions location, transport or generation changed')
    }
    const ownerRef = requiredText(input.ownerRef, 'projection ownerRef')
    if (ownerRef !== read.conditions.configOwnerRef) {
      throw new Error('submission conditions configuration owner changed')
    }
    const revision = input.revision
    if ((typeof revision !== 'string' && typeof revision !== 'number')
        || String(revision) !== read.conditions.sourceRevision) {
      throw new Error('submission conditions source revision changed')
    }
    return read.conditions
  }

  function invalidate(locationKey?: string): void {
    if (locationKey === undefined) {
      active.clear()
      return
    }
    active.delete(requiredText(locationKey, 'location key'))
  }

  return Object.freeze({ begin, complete, capture, invalidate })
}
