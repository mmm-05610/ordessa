import { randomUUID } from 'node:crypto'
import { configurationDigest, jsonDigest, stableJSON } from './ordessa-configuration-query.mjs'

const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
const text = (value, limit = 4096) => typeof value === 'string' && value.length > 0
  && value.length <= limit && value === value.trim() && !/[\u0000-\u001f\u007f]/u.test(value)

/** Effect once, retain Unknown on failure, and never resume from a query. */
export function restorationOperations({ read, withProvider, restore, invalidParams, preflight = () => {} }) {
  const records = new Map()
  const fail = message => { throw invalidParams(message) }
  const parse = input => {
    if (!exact(input, ['sessionId', 'operationId', 'expectedGeneration', 'expectedConfigDigest', 'target', 'provider', 'model'])
        || !text(input.sessionId) || !text(input.operationId, 128) || !input.operationId.startsWith('restore:')
        || !text(input.expectedGeneration) || typeof input.expectedConfigDigest !== 'string'
        || !/^[a-f0-9]{64}$/u.test(input.expectedConfigDigest)
        || !text(input.model) || !exact(input.target, ['server_id', 'session_id', 'channel_id', 'runtime_generation'])
        || !['server_id', 'session_id', 'channel_id'].every(key => text(input.target[key]))
        || !Number.isSafeInteger(input.target.runtime_generation) || input.target.runtime_generation < 0
        || (!exact(input.provider, ['providerId', 'apiType', 'baseUrl'])
          && !exact(input.provider, ['providerId', 'apiType', 'baseUrl', 'headers']))
        || !['providerId', 'apiType', 'baseUrl'].every(key => text(input.provider[key])))
      fail('Expected bounded exact provider restoration')
    let url
    try { url = new URL(input.provider.baseUrl) } catch { fail('Invalid provider endpoint') }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
      fail('Unsafe provider endpoint')
    const headers = input.provider.headers
    if (headers !== undefined && (!headers || typeof headers !== 'object' || Array.isArray(headers)
        || Object.keys(headers).length > 32 || Object.entries(headers).some(([key, value]) =>
          !/^[a-zA-Z0-9-]{1,128}$/u.test(key) || !text(value, 8192)))) fail('Invalid bounded provider headers')
    if (Buffer.byteLength(stableJSON(input)) > 65536) fail('Restoration input exceeds capacity')
    return structuredClone(input)
  }
  const apply = async input => {
    input = parse(input)
    const inputDigest = jsonDigest(input)
    const prior = records.get(input.operationId)
    if (prior) {
      if (prior.inputDigest !== inputDigest) fail('Restoration operation bound to different input')
      return structuredClone(prior)
    }
    return withProvider(async () => {
      if (records.size >= 256) fail('Restoration record capacity exhausted')
      const before = read({ sessionId: input.sessionId })
      if (before.busy || before.generation !== input.expectedGeneration
          || configurationDigest(before) !== input.expectedConfigDigest)
        fail('Restoration generation/configuration fence changed or busy')
      preflight(input)
      const record = { operationId: input.operationId, sessionId: input.sessionId,
        kind: 'provider-resume', state: 'unknown', phase: 'restoring', inputDigest,
        target: structuredClone(input.target), before, after: null, evidenceRef: null }
      // Store only a digest of submitted credentials, never headers themselves.
      records.set(input.operationId, record)
      try {
        const proof = await restore(input)
        const after = read({ sessionId: input.sessionId })
        record.after = after
        const model = after.configOptions.filter(option => option.id === 'model')
        if (proof?.sessionId !== input.sessionId || proof?.apiType !== input.provider.apiType
            || proof?.baseUrl !== input.provider.baseUrl || after.busy
            || after.generation === before.generation || model.length !== 1
            || model[0].currentValue !== input.model) {
          record.phase = 'restored-readback-mismatch'
        } else {
          record.state = 'observed'; record.phase = 'restored-readback'
          record.evidenceRef = 'native-restoration:' + randomUUID()
        }
      } catch (error) {
        record.phase = 'restoration-outcome-unknown'
        // Closed vocabulary only: upstream error text can contain credentials.
        if (['provider', 'close', 'resume', 'preferences', 'model'].includes(error?.restorationPhase))
          record.failureStep = error.restorationPhase
        if (['native-history-unavailable', 'native-authentication-rejected', 'native-model-rejected', 'native-request-rejected'].includes(error?.restorationReason))
          record.failureReason = error.restorationReason
      }
      return structuredClone(record)
    })
  }
  const query = input => {
    if (!exact(input, ['sessionId', 'operationId']) || !text(input.sessionId) || !text(input.operationId, 128))
      fail('Expected exact restoration query')
    const record = records.get(input.operationId)
    if (!record || record.sessionId !== input.sessionId) fail('Restoration is not known for this session')
    return structuredClone(record)
  }
  return { parse, apply, query }
}
