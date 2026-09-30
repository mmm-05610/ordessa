import { randomUUID } from 'node:crypto'
import { configurationDigest, jsonDigest, stableJSON } from './ordessa-configuration-query.mjs'

export const CONFIGURATION_APPLY = '_ordessa/session/configuration/apply'
export const CONFIGURATION_OPERATION = '_ordessa/session/configuration/operation'
const INPUT_KEYS = ['sessionId', 'operationId', 'expectedGeneration', 'expectedConfigDigest', 'configId', 'value']
const MAX_STATE_BYTES = 64 * 1024
const MAX_OPERATIONS = 256
const MAX_LOCKS = 16

function record(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null)
}
function text(value, maximum) {
  return typeof value === 'string' && value.length > 0 && value.length <= maximum
    && value.trim() === value && !/[\u0000-\u001f\u007f]/u.test(value)
}
function exact(value, keys) {
  return record(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
}

/** Bounded native evidence only: authorization and C4 confirmation are external. */
export function configurationOperations({ agent, read, invalidParams,
  maxOperations = MAX_OPERATIONS, maxLocks = MAX_LOCKS,
  configIds = ['model', 'thinkingLevel'], evidencePrefix = 'pi-native-operation',
  assertIdle = sessionId => {
    const session = agent.live.get(sessionId)
    if (!session || agent.disposed || session.disposed || session.closing)
      throw invalidParams('Session is not live')
    if (session.busy) throw invalidParams('Session operation busy')
  },
  setOption = params => agent.setConfigOption({ params }) }) {
  if (!Array.isArray(configIds) || configIds.length < 1 || configIds.length > 16
      || configIds.some(id => !text(id, 128)) || new Set(configIds).size !== configIds.length
      || !/^[a-z][a-z0-9-]{0,63}$/u.test(evidencePrefix)
      || typeof assertIdle !== 'function' || typeof setOption !== 'function')
    throw new TypeError('Invalid native operation strategy')
  if (!Number.isInteger(maxOperations) || maxOperations < 1 || maxOperations > MAX_OPERATIONS
      || !Number.isInteger(maxLocks) || maxLocks < 1 || maxLocks > MAX_LOCKS)
    throw new TypeError('Invalid operation capacity')
  const operations = new Map()
  const locks = new Set()
  const fail = message => { throw invalidParams(message) }
  const snapshot = sessionId => {
    const observed = read({ sessionId })
    if (!text(observed.generation, 4096) || typeof observed.busy !== 'boolean' || !Array.isArray(observed.configOptions))
      fail('Malformed live configuration')
    const encoded = stableJSON(observed)
    if (Buffer.byteLength(encoded) > MAX_STATE_BYTES) fail('Live configuration exceeds capacity')
    return JSON.parse(encoded)
  }
  const validateManifest = (manifest, input) => {
    if (!exact(manifest, ['target', 'scope', 'actions']) || manifest.scope !== 'session'
        || !exact(manifest.target, ['server_id', 'session_id', 'channel_id', 'runtime_generation'])
        || !['server_id', 'session_id', 'channel_id'].every(key => text(manifest.target[key], 4096))
        || !Number.isSafeInteger(manifest.target.runtime_generation) || manifest.target.runtime_generation < 0
        || !Array.isArray(manifest.actions) || manifest.actions.length !== 1)
      fail('Expected bounded single session action manifest')
    const action = manifest.actions[0]
    if (!exact(action, ['publicationOwner', 'publicationToken', 'source', 'actionId',
      'schemaVersion', 'input', 'expectedObservation'])
        || !text(action.publicationOwner, 4096) || !text(action.publicationToken, 4096)
        || !exact(action.source, ['facet_id', 'item_id', 'contribution_version'])
        || !['facet_id', 'item_id', 'contribution_version'].every(key => text(action.source[key], 4096))
        || action.actionId !== 'acp.session.set-config-option' || action.schemaVersion !== '1'
        || !exact(action.input, ['configId', 'value'])
        || action.input.configId !== input.configId || action.input.value !== input.value
        || !text(action.expectedObservation, 4096))
      fail('Action manifest does not bind the exact configuration operation')
    // This preserves the caller's C4 target identity; it does not establish its
    // canonical UID provenance or confer any native/host submission authority.
    if (Buffer.byteLength(stableJSON(manifest)) > MAX_STATE_BYTES)
      fail('Action manifest exceeds capacity')
  }
  const parseApply = input => {
    if ((!exact(input, INPUT_KEYS) && !exact(input, [...INPUT_KEYS, 'actionManifest'])) || !text(input.sessionId, 4096)
        || !text(input.operationId, 128) || !text(input.expectedGeneration, 4096)
        || typeof input.expectedConfigDigest !== 'string' || !/^[0-9a-f]{64}$/u.test(input.expectedConfigDigest)
        || !configIds.includes(input.configId) || !text(input.value, 4096))
      fail('Expected bounded session model/thinking operation only')
    if (Object.hasOwn(input, 'actionManifest')) validateManifest(input.actionManifest, input)
    return structuredClone(input)
  }
  const parseQuery = input => {
    if (!exact(input, ['sessionId', 'operationId']) || !text(input.sessionId, 4096) || !text(input.operationId, 128))
      fail('Expected sessionId and operationId only')
    return structuredClone(input)
  }
  const withSession = async (sessionId, work) => {
    if (!text(sessionId, 4096)) fail('Expected bounded sessionId')
    if (locks.has(sessionId)) fail('Session operation busy')
    if (locks.size >= maxLocks) fail('Session operation capacity exhausted')
    assertIdle(sessionId)
    // Acquisition precedes every await; competing requests fail, never queue.
    locks.add(sessionId)
    try { return await work() } finally { locks.delete(sessionId) }
  }
  const apply = async input => {
    input = parseApply(input)
    const inputDigest = jsonDigest(input)
    const previous = operations.get(input.operationId)
    if (previous) {
      if (previous.inputDigest !== inputDigest) fail('OperationId is bound to different input')
      return structuredClone(previous)
    }
    return withSession(input.sessionId, async () => {
      if (operations.size >= maxOperations) fail('Operation record capacity exhausted')
      const before = snapshot(input.sessionId)
      const beforeDigest = configurationDigest(before)
      if (before.busy || before.generation !== input.expectedGeneration || beforeDigest !== input.expectedConfigDigest)
        fail('Live generation/configuration fence changed or busy')
      const matching = before.configOptions.filter(option => option.id === input.configId)
      if (matching.length !== 1 || matching[0].type !== 'select' || !Array.isArray(matching[0].options)
          || !matching[0].options.some(option => option.value === input.value))
        fail('Configuration value is not exposed by the live session')
      const operation = { operationId: input.operationId, sessionId: input.sessionId,
        generation: before.generation, inputDigest, beforeConfigDigest: beforeDigest,
        configId: input.configId, requestedValue: input.value, state: 'unknown', phase: 'executing',
        afterConfigDigest: null, observedValue: null, evidenceRef: null,
        before, after: null }
      if (input.actionManifest) {
        operation.actionManifest = structuredClone(input.actionManifest)
        operation.target = structuredClone(input.actionManifest.target)
        operation.manifestDigest = jsonDigest(input.actionManifest)
      }
      // Reserve before invoking upstream. Capacity is never reclaimed by eviction.
      operations.set(input.operationId, operation)
      let upstreamFailed = false
      try {
        await setOption({ sessionId: input.sessionId, configId: input.configId, value: input.value })
      } catch { upstreamFailed = true }
      try {
        const after = snapshot(input.sessionId)
        operation.after = after
        operation.afterConfigDigest = configurationDigest(after)
        const observed = after.configOptions.filter(option => option.id === input.configId)
        if (observed.length === 1) operation.observedValue = structuredClone(observed[0].currentValue)
        if (!upstreamFailed && !after.busy && after.generation === before.generation
            && observed.length === 1 && operation.observedValue === input.value) {
          operation.state = 'observed'
          operation.phase = 'read-back'
          operation.evidenceRef = `${evidencePrefix}:${randomUUID()}`
        } else operation.phase = upstreamFailed ? 'upstream-outcome-unknown' : 'read-back-mismatch'
      } catch { operation.phase = 'read-back-unavailable' }
      return structuredClone(operation)
    })
  }
  const query = input => {
    input = parseQuery(input)
    const operation = operations.get(input.operationId)
    if (!operation || operation.sessionId !== input.sessionId) fail('Operation is not known for this session')
    // Query reads the retained record, including unknown. It never invokes upstream.
    return structuredClone(operation)
  }
  return { apply, query, parseApply, parseQuery, withSession,
    isBusy: sessionId => locks.has(sessionId) }
}
