import { randomUUID } from 'node:crypto'

export const CONFIGURATION_QUERY = '_ordessa/session/configuration'

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
