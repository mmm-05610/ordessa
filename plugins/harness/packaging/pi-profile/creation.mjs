import { jsonDigest, stableJSON } from './ordessa-configuration-query.mjs'

const exact = (v, keys) => v && typeof v === 'object' && !Array.isArray(v)
  && Object.keys(v).length === keys.length && keys.every(k => Object.hasOwn(v, k))
const text = (v, limit = 4096) => typeof v === 'string' && v.length > 0 && v.length <= limit
  && v === v.trim() && !/[\u0000-\u001f\u007f]/u.test(v)

/** One dedicated Pi instance, in-memory provider registration; no auth/config files. */
export function piCreation({ agent, read, invalidParams }) {
  let initial = null
  let busy = false
  let lifecycle = 0
  const fail = message => { throw invalidParams(message) }
  const parse = input => {
    if (!exact(input, ['operationId', 'model', 'models', 'provider'])
        || !text(input.operationId, 128) || !input.operationId.startsWith('create:')
        || input.operationId.length <= 7 || !text(input.model)
        || !Array.isArray(input.models) || !input.models.length || input.models.length > 256
        || input.models.some(m => !text(m)) || new Set(input.models).size !== input.models.length
        || !input.models.includes(input.model)
        || (!exact(input.provider, ['providerId', 'apiType', 'baseUrl'])
          && !exact(input.provider, ['providerId', 'apiType', 'baseUrl', 'apiKey']))
        || !text(input.provider.providerId) || input.provider.providerId.includes('/')
        || input.provider.apiType !== 'openai-completions' || !text(input.provider.baseUrl)
        || (Object.hasOwn(input.provider, 'apiKey') && !text(input.provider.apiKey, 8000)))
      fail('Expected bounded initial Pi provider/model configuration')
    let url
    try { url = new URL(input.provider.baseUrl) } catch { fail('Invalid initial endpoint') }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
      fail('Unsafe initial endpoint')
    if (Buffer.byteLength(stableJSON(input)) > 65536) fail('Initial configuration exceeds bounds')
    return structuredClone(input)
  }
  const prepare = async input => {
    input = parse(input)
    if (busy || lifecycle) fail('Provider/lifecycle operation busy')
    const digest = jsonDigest(input)
    if (initial) {
      if (initial.record.operationId !== input.operationId || initial.record.inputDigest !== digest)
        fail('Initial configuration already reserved')
      return structuredClone(initial.record)
    }
    if (agent.disposed || agent.live.size) fail('Initial configuration requires dedicated empty adapter')
    const runtime = agent.deps.modelRuntime
    if (!runtime || ['registerProvider', 'setRuntimeApiKey', 'refresh', 'getAvailable'].some(k => typeof runtime[k] !== 'function'))
      fail('Pinned model runtime unavailable')
    busy = true
    // Only the digest binds the key. Retained route/model evidence never stores it.
    initial = { model: input.model, route: { provider: input.provider.providerId,
      api: input.provider.apiType, baseUrl: input.provider.baseUrl }, attempted: false,
      record: { operationId: input.operationId, inputDigest: digest, state: 'unknown',
        phase: 'preparing', after: null } }
    try {
      runtime.registerProvider(input.provider.providerId, { api: input.provider.apiType,
        // Extension registration (unlike models.json) does not fill these in
        // Pi 0.84.2. Use its generic text-model defaults, not claimed vendor
        // pricing/vision/reasoning capabilities, until catalog metadata exists.
        baseUrl: input.provider.baseUrl, models: input.models.map(id => ({ id, name: id,
          reasoning: false, input: ['text'],
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
          contextWindow: 128000, maxTokens: 16384 })) })
      // Unlike provider config.apiKey, this API treats bytes as opaque, never as
      // a command/env configuration expression. It does not persist auth.json.
      if (Object.hasOwn(input.provider, 'apiKey'))
        await runtime.setRuntimeApiKey(input.provider.providerId, input.provider.apiKey)
      await runtime.refresh({ allowNetwork: false })
      const available = await runtime.getAvailable()
      const matches = available.filter(m => m.provider === initial.route.provider && m.id === initial.model
        && m.api === initial.route.api && m.baseUrl === initial.route.baseUrl)
      if (matches.length !== 1) fail('Initial registered model unavailable')
      initial.record.state = 'prepared'; initial.record.phase = 'awaiting-native-creation'
    } catch { initial.record.phase = 'preparation-outcome-unknown' }
    finally { busy = false }
    return structuredClone(initial.record)
  }
  const parseQuery = input => {
    if (!exact(input, ['operationId']) || !text(input.operationId, 128)
        || !input.operationId.startsWith('create:')) fail('Expected exact initial operation query')
    return structuredClone(input)
  }
  const query = input => {
    input = parseQuery(input)
    if (!initial || input.operationId !== initial.record.operationId) fail('Unknown initial operation')
    return structuredClone(initial.record)
  }
  const withLifecycle = async work => {
    if (busy) fail('Provider operation busy')
    if (initial && initial.record.state !== 'observed') fail('Initial configuration requires fresh creation')
    lifecycle++
    try { return await work() } finally { lifecycle-- }
  }
  const create = async (params, work) => {
    if (!initial) return withLifecycle(work)
    if (busy || lifecycle) fail('Provider/lifecycle operation busy')
    if (initial.attempted) fail('Initial creation already attempted')
    if (initial.record.state !== 'prepared' || params.sessionId || agent.live.size || agent.disposed)
      fail('Initial configuration not prepared for fresh dedicated creation')
    initial.attempted = true; initial.record.state = 'unknown'; initial.record.phase = 'creating'
    busy = true
    try {
      const result = await work()
      const sessionId = result.sessionId
      initial.record.after = read({ sessionId })
      await agent.setConfigOption({ params: { sessionId, configId: 'model',
        value: initial.route.provider + '/' + initial.model } })
      const after = read({ sessionId })
      initial.record.after = after
      const selectors = after.configOptions.filter(s => s.id === 'model')
      const value = initial.route.provider + '/' + initial.model
      const choices = selectors.length === 1 && Array.isArray(selectors[0].options)
        ? selectors[0].options.filter(o => o.value === value) : []
      const facts = choices.length === 1 ? choices[0]._meta?.ordessaModel : null
      if (after.busy || selectors.length !== 1 || selectors[0].currentValue !== value
          || !facts || facts.model !== initial.model || facts.provider !== initial.route.provider
          || facts.api !== initial.route.api || facts.baseUrl !== initial.route.baseUrl)
        fail('Initial native readback differs')
      initial.record.state = 'observed'; initial.record.phase = 'initial-model-readback'
      return result
    } finally { busy = false }
  }
  return { prepare, query, parse, parseQuery, create, lifecycle: withLifecycle, isBusy: () => busy }
}
