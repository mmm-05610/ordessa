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
      configOptions: structuredClone(session.configOptions()) }
  }
}
