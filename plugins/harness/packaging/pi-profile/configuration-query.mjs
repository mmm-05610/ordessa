import { createHash, randomUUID } from 'node:crypto'

export const CONFIGURATION_QUERY = '_ordessa/session/configuration'

/** JSON-only canonical encoding: object keys sort, array order remains native. */
export function stableJSON(value) {
  const visit = (item, seen) => {
    if (item === null || typeof item === 'string' || typeof item === 'boolean') return JSON.stringify(item)
    if (typeof item === 'number' && Number.isFinite(item)) return JSON.stringify(item)
    if (typeof item !== 'object' || seen.has(item)) throw new TypeError('Expected finite acyclic JSON')
    seen.add(item)
    let encoded
    if (Array.isArray(item)) {
      if (Object.keys(item).length !== item.length) throw new TypeError('Expected dense JSON array')
      encoded = '[' + item.map(entry => visit(entry, seen)).join(',') + ']'
    } else {
      if (Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null)
        throw new TypeError('Expected plain JSON object')
      encoded = '{' + Object.keys(item).sort().map(key => JSON.stringify(key) + ':' + visit(item[key], seen)).join(',') + '}'
    }
    seen.delete(item)
    return encoded
  }
  return visit(value, new Set())
}

export function configurationDigest(observation) {
  return createHash('sha256').update(stableJSON(observation.configOptions)).digest('hex')
}

export function jsonDigest(value) {
  return createHash('sha256').update(stableJSON(value)).digest('hex')
}

function observedModelOptions(session) {
  const options = structuredClone(session.configOptions())
  const models = Array.isArray(session.availableModels) ? session.availableModels : []
  for (const selector of options) {
    if (selector.id !== 'model' || !Array.isArray(selector.options)) continue
    for (const option of selector.options) {
      // This namespace is evidence we produce now, never evidence carried over
      // from an option label or a previous catalog generation.
      if (option._meta && typeof option._meta === 'object') {
        delete option._meta.ordessaModel
        if (Object.keys(option._meta).length === 0) delete option._meta
      }
      const matching = models.filter(model => model && typeof model.provider === 'string'
        && typeof model.id === 'string' && option.value === model.provider + '/' + model.id)
      if (matching.length !== 1) continue
      const model = matching[0]
      if (![model.provider, model.id, model.api, model.baseUrl].every(value =>
        typeof value === 'string' && value.length > 0 && value.length <= 4096
        && value.trim() === value && !/[\u0000-\u001f\u007f]/u.test(value))
        || model.provider.includes('/')) continue
      let endpoint
      try { endpoint = new URL(model.baseUrl) } catch { continue }
      // Credentials must not escape through a URL disguise either.
      if (!['http:', 'https:'].includes(endpoint.protocol) || endpoint.username
        || endpoint.password || endpoint.search || endpoint.hash) continue
      option._meta = { ...option._meta, ordessaModel: {
        provider: model.provider, model: model.id, api: model.api, baseUrl: model.baseUrl,
      } }
    }
  }
  return options
}

/** Read the adapter's live session, never a request's desired configuration. */
export function configurationReader(agent, invalidParams) {
  const generations = new WeakMap()
  return ({ sessionId }) => {
    const session = agent.live.get(sessionId)
    if (!session || agent.disposed || session.disposed || session.closing)
      throw invalidParams('Session is not live')
    let generation = generations.get(session)
    if (!generation) { generation = randomUUID(); generations.set(session, generation) }
    // configOptions is upstream's view of Pi's actual model/thinking state.
    // Clone the public options so callers cannot mutate native state.
    return { sessionId, generation, busy: !!session.busy,
      configOptions: observedModelOptions(session) }
  }
}
