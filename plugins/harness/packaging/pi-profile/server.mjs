// Registration follows @automatalabs/pi-acp 0.5.0 dist/server.js (Apache-2.0).
// Standard implementations are delegated; Ordessa adds bounded owner evidence.
import { Readable, Writable } from 'node:stream'
import { agent as acpAgent, methods, ndJsonStream, RequestError } from '@agentclientprotocol/sdk'
import { PiAcpAgent } from './agent.js'
import { resolveDeps } from './deps.js'
import { SESSION_STEERING_METHOD, steeringRequestParser } from './steering.js'
import { LOADED_TURN_QUERY_METHOD, loadedTurnQueryParser } from './loaded-turn.js'
import { CONFIGURATION_QUERY, configurationReader } from './ordessa-configuration-query.mjs'
import { CONFIGURATION_APPLY, CONFIGURATION_OPERATION, configurationOperations } from './ordessa-configuration-operation.mjs'

export async function runAcp(options = {}) {
  const impl = new PiAcpAgent(await resolveDeps(options.deps))
  const read = configurationReader(impl, message => RequestError.invalidParams(undefined, message))
  const operation = configurationOperations({ agent: impl, read,
    invalidParams: message => RequestError.invalidParams(undefined, message) })
  const parser = { parse(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).length !== 1 || typeof value.sessionId !== 'string'
      || !value.sessionId.length || value.sessionId.length > 4096)
      throw RequestError.invalidParams(undefined, 'Expected sessionId only')
    return value
  } }
  const app = acpAgent({ name: '@automatalabs/pi-acp' })
    .onRequest(methods.agent.initialize, context => {
      const result = impl.initialize(context)
      return { ...result, _meta: { ...result._meta, ordessaConfiguration: { supported: true, version: 1 } } }
    })
    .onRequest(methods.agent.authenticate, c => impl.authenticate(c))
    .onRequest(methods.agent.session.new, c => impl.newSession(c))
    .onRequest(methods.agent.session.load, c => impl.loadSession(c))
    .onRequest(methods.agent.session.resume, c => impl.resumeSession(c))
    .onRequest(methods.agent.session.fork, c => impl.forkSession(c))
    .onRequest(methods.agent.session.list, c => impl.listSessions(c))
    .onRequest(methods.agent.session.close, c => impl.closeSession(c))
    .onRequest(methods.agent.session.setConfigOption, c => operation.withSession(c.params.sessionId, () => impl.setConfigOption(c)))
    .onRequest(methods.agent.session.prompt, c => operation.withSession(c.params.sessionId, () => impl.prompt(c)))
    .onRequest(SESSION_STEERING_METHOD, steeringRequestParser, c => impl.steer(c))
    .onRequest(LOADED_TURN_QUERY_METHOD, loadedTurnQueryParser, c => impl.loadedTurnQuery(c))
    .onRequest(CONFIGURATION_QUERY, parser, c => {
      const observed = read(c.params)
      return { ...observed, busy: observed.busy || operation.isBusy(c.params.sessionId) }
    })
    .onRequest(CONFIGURATION_APPLY, { parse: operation.parseApply }, c => operation.apply(c.params))
    .onRequest(CONFIGURATION_OPERATION, { parse: operation.parseQuery }, c => operation.query(c.params))
    .onNotification(methods.agent.session.cancel, c => impl.cancel(c))
  const stream = options.stream ?? ndJsonStream(Writable.toWeb(process.stdout), Readable.toWeb(process.stdin))
  return { connection: app.connect(stream), agent: impl }
}
