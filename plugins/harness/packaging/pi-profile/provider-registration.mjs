import { configurationDigest, jsonDigest, stableJSON } from './ordessa-configuration-query.mjs'

export const PROVIDER_REGISTER = '_ordessa/session/configuration/provider-register'

const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
  && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
const text = (value, limit = 4096) => typeof value === 'string' && value.length > 0
  && value.length <= limit && value === value.trim() && !/[\u0000-\u001f\u007f]/u.test(value)

/** Admission only: no session creation, model selection, resume or disk writes. */
export function piProviderRegistration({ agent, read, creation, invalidParams }) {
  const records = new Map()
  const admittedProviders = new Map()
  let busy = false
  const fail = message => { throw invalidParams(message) }
  const parse = input => {
    if (!exact(input, ['operationId', 'sessionId', 'expectedGeneration', 'expectedConfigDigest', 'target', 'model', 'models', 'provider'])
        || !text(input.operationId, 128) || !input.operationId.startsWith('provider:')
        || !text(input.sessionId) || !text(input.expectedGeneration)
        || !/^[a-f0-9]{64}$/u.test(input.expectedConfigDigest)
        || !exact(input.target, ['server_id', 'session_id', 'channel_id', 'runtime_generation'])
        || !['server_id', 'session_id', 'channel_id'].every(key => text(input.target[key]))
        || !Number.isSafeInteger(input.target.runtime_generation) || input.target.runtime_generation < 0)
      fail('Expected exact provider registration fence')
    // Reuse the pinned Pi dialect validator, never the creation effect.
    creation.parse({ operationId: 'create:registration-validation',
      model: input.model, models: input.models, provider: input.provider })
    if (Buffer.byteLength(stableJSON(input)) > 65536) fail('Provider registration exceeds bounds')
    return structuredClone(input)
  }
  const parseQuery = input => {
    if (!exact(input, ['sessionId', 'operationId']) || !text(input.sessionId)
        || !text(input.operationId, 128) || !input.operationId.startsWith('provider:'))
      fail('Expected exact provider registration query')
    return structuredClone(input)
  }
  const query = input => {
    input = parseQuery(input)
    const record = records.get(input.operationId)
    if (!record || record.sessionId !== input.sessionId) fail('Unknown provider registration')
    return structuredClone(record)
  }
  const apply = async input => {
    input = parse(input)
    const digest = jsonDigest(input)
    const prior = records.get(input.operationId)
    if (prior) {
      if (prior.inputDigest !== digest) fail('Provider operation bound to different input')
      return structuredClone(prior)
    }
    if (busy || [...records.values()].some(record => record.state === 'unknown'))
      fail('Provider registration pending; query only')
    if (records.size >= 256 || agent.disposed || agent.live.size !== 1)
      fail('Dedicated live Pi instance required')
    const session = agent.live.get(input.sessionId)
    const before = read({ sessionId: input.sessionId })
    if (!session || session.disposed || session.closing || before.busy
        || before.generation !== input.expectedGeneration
        || configurationDigest(before) !== input.expectedConfigDigest)
      fail('Provider registration live fence changed or busy')
    // Replacing an existing provider could silently drop models or reroute the
    // current selection. Admission adds a new identity; C4 selects it later.
    const admitted = admittedProviders.get(input.provider.providerId)
    const providerDigest = jsonDigest(input.provider)
    if (before.configOptions.some(item => item.id === 'model' && item.options?.some(option =>
      option._meta?.ordessaModel?.provider === input.provider.providerId))
        && (!admitted || admitted.digest !== providerDigest))
      fail('Provider identity already exists in the live catalogue')
    const models = [...new Set([...(admitted?.models ?? []), ...input.models])]
    if (models.length > 256) fail('Provider catalogue exceeds bounds')
    const runtime = agent.deps.modelRuntime
    if (['registerProvider', 'setRuntimeApiKey', 'refresh', 'getAvailable'].some(key => typeof runtime?.[key] !== 'function')
        || typeof session.publishAvailableModels !== 'function') fail('Pinned Pi live registration unavailable')
    const record = { sessionId: input.sessionId, operationId: input.operationId,
      kind: 'provider-registration', state: 'unknown', phase: 'registering', inputDigest: digest,
      target: structuredClone(input.target), before, after: null }
    records.set(input.operationId, record)
    busy = true
    try {
      runtime.registerProvider(input.provider.providerId, { api: input.provider.apiType,
        baseUrl: input.provider.baseUrl, models: models.map(id => ({ id, name: id,
          reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 128000, maxTokens: 16384 })) })
      if (Object.hasOwn(input.provider, 'apiKey'))
        await runtime.setRuntimeApiKey(input.provider.providerId, input.provider.apiKey)
      await runtime.refresh({ allowNetwork: false })
      if (agent.live.get(input.sessionId) !== session || session.disposed || session.closing)
        fail('Provider owner changed during registration')
      session.publishAvailableModels(await runtime.getAvailable())
      const after = read({ sessionId: input.sessionId })
      record.after = after
      const selectors = after.configOptions.filter(item => item.id === 'model')
      const option = selectors.length === 1 ? selectors[0].options.filter(item =>
        item.value === input.provider.providerId + '/' + input.model) : []
      const route = option.length === 1 ? option[0]._meta?.ordessaModel : null
      if (after.busy || after.generation !== before.generation
          || selectors[0]?.currentValue !== before.configOptions.find(item => item.id === 'model')?.currentValue
          || !route || route.provider !== input.provider.providerId || route.model !== input.model
          || route.api !== input.provider.apiType || route.baseUrl !== input.provider.baseUrl)
        fail('Registered provider catalogue readback differs')
      record.state = 'observed'; record.phase = 'provider-registered'
      admittedProviders.set(input.provider.providerId, { digest: providerDigest, models })
    } catch { record.phase = 'registration-outcome-unknown' }
    finally { busy = false }
    return structuredClone(record)
  }
  return { parse, parseQuery, apply, query,
    isBusy: () => busy || [...records.values()].some(record => record.state === 'unknown') }
}
