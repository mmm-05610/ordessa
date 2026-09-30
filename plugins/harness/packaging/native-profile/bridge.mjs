import { nativeConfigurationReader } from './ordessa-native-configuration-query.mjs'
import { configurationOperations } from './ordessa-configuration-operation.mjs'

export function nativeProfileBridge(agent, brand, invalidParams) {
  const { read, assertIdle } = nativeConfigurationReader({ agent, brand, invalidParams })
  let providerBusy = false
  let lifecycleBusy = 0
  const operation = configurationOperations({ agent, read, invalidParams,
    configIds: brand === 'codex' ? ['model', 'reasoning_effort'] : ['model', 'effort'],
    evidencePrefix: brand + '-native-operation',
    assertIdle(sessionId) {
      if (providerBusy) throw invalidParams('Provider operation busy')
      assertIdle(sessionId)
    }, setOption: input => agent.setSessionConfigOption(input) })
  const parser = { parse(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input)
        || Object.keys(input).length !== 1 || !Object.hasOwn(input, 'sessionId')
        || typeof input.sessionId !== 'string' || !input.sessionId || input.sessionId.length > 4096)
      throw invalidParams('Expected sessionId only')
    return input
  } }
  return { operation, parser, read(input) {
    const observed = read(input)
    return { ...observed, busy: observed.busy || providerBusy || operation.isBusy(input.sessionId) }
  }, async withLifecycle(work) {
    if (providerBusy) throw invalidParams('Provider operation busy')
    lifecycleBusy++
    try { return await work() } finally { lifecycleBusy-- }
  }, async withProvider(work) {
    if (providerBusy || lifecycleBusy) throw invalidParams('Provider/lifecycle operation busy')
    const ids = brand === 'codex' ? [...agent.sessions.keys()] : Object.keys(agent.sessions)
    for (const sessionId of ids) {
      assertIdle(sessionId)
      if (operation.isBusy(sessionId)) throw invalidParams('Session operation busy')
    }
    providerBusy = true
    try { return await work() } finally { providerBusy = false }
  } }
}
