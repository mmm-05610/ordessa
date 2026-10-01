import { randomUUID } from 'node:crypto'
import { stableJSON } from '../pi-profile/configuration-query.mjs'
import { safeNativeRoute } from './routing.mjs'

// Only public ACP selector vocabulary leaves the adapter. In particular,
// arbitrary _meta, credentials and provider headers never become evidence.
function selectors(options) {
  if (!Array.isArray(options) || options.length > 64) throw new TypeError('Invalid native selectors')
  const projectOption = (item, depth = 0) => {
    if (!item || typeof item !== 'object' || depth > 2) throw new TypeError('Invalid native option')
    const result = {}
    for (const key of ['value', 'name', 'description']) {
      if (Object.hasOwn(item, key)) {
        if (typeof item[key] !== 'string' || item[key].length > 4096) throw new TypeError('Invalid option text')
        result[key] = item[key]
      }
    }
    if (Object.hasOwn(item, 'options')) {
      if (!Array.isArray(item.options) || item.options.length > 512) throw new TypeError('Invalid option group')
      result.options = item.options.map(child => projectOption(child, depth + 1))
    }
    return result
  }
  const seen = new Set()
  return options.map(item => {
    if (!item || typeof item.id !== 'string' || !item.id || item.id.length > 128
        || seen.has(item.id) || !['select', 'boolean'].includes(item.type))
      throw new TypeError('Invalid or duplicate native selector')
    seen.add(item.id)
    const result = { id: item.id, type: item.type, currentValue: item.currentValue }
    if (item.type === 'boolean' ? typeof item.currentValue !== 'boolean' : typeof item.currentValue !== 'string')
      throw new TypeError('Invalid native selector value')
    for (const key of ['name', 'description', 'category'])
      if (typeof item[key] === 'string') result[key] = item[key]
    if (item.type === 'select') {
      if (!Array.isArray(item.options) || item.options.length > 512) throw new TypeError('Invalid selector options')
      result.options = item.options.map(option => projectOption(option))
    }
    return result
  })
}

/** Strategies bind to the locked upstream live instance, not setter responses. */
export function nativeConfigurationReader({ agent, brand, invalidParams }) {
  if (!['codex', 'claude-code'].includes(brand)) throw new TypeError('Unsupported evidence strategy')
  const generations = new WeakMap()
  const read = ({ sessionId }) => {
    if (typeof sessionId !== 'string' || !sessionId || sessionId.length > 4096)
      throw invalidParams('Expected bounded sessionId')
    const session = brand === 'codex' ? agent.sessions.get(sessionId)
      : Object.hasOwn(agent.sessions, sessionId) ? agent.sessions[sessionId] : undefined
    if (!session || agent.disposed || session.disposed || session.queryClosed
        || session.closing || (brand === 'codex' && agent.sessionIsClosing(sessionId)))
      throw invalidParams('Session is not live')
    let generation = generations.get(session)
    if (!generation) { generation = randomUUID(); generations.set(session, generation) }
    const busy = brand === 'codex'
      ? agent.activePrompts.has(sessionId) || agent.pendingTurnStarts.has(sessionId)
      : !!agent.providerUpdate || !!session.activeTurn
        || (session.turnQueue ?? []).some(turn => !turn.settled)
    const configOptions = selectors(brand === 'codex'
      ? agent.createSessionConfigOptions(session) : session.configOptions)
    const captured = brand === 'codex'
      ? agent.codexAcpClient?.codexClient?.ordessaThreadRoutes?.get(sessionId)
      : { provider: 'main', api: session.ordessaProviderRoute?.apiType, baseUrl: session.ordessaProviderRoute?.baseUrl }
    const route = safeNativeRoute(captured)
    if (route && (brand !== 'codex' || session.authProvider === route.provider
        || route.authentication === 'managed-account' && session.authProvider == null)) {
      const attach = option => {
        if (typeof option.value === 'string') option._meta = { ordessaModel: { ...route, model: option.value } }
        for (const child of option.options ?? []) attach(child)
      }
      for (const selector of configOptions.filter(item => item.id === 'model'))
        for (const option of selector.options) attach(option)
    }
    const result = { sessionId, generation, busy, configOptions }
    if (Buffer.byteLength(stableJSON(result)) > 64 * 1024) throw invalidParams('Live configuration exceeds capacity')
    return result
  }
  return { read, assertIdle(sessionId) {
    if (read({ sessionId }).busy) throw invalidParams('Session operation busy')
  } }
}
