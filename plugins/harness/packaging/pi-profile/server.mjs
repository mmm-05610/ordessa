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
import { piCreation } from './ordessa-creation.mjs'
import { piProviderRegistration, PROVIDER_REGISTER } from './ordessa-provider-registration.mjs'

export async function runAcp(options = {}) {
  const impl = new PiAcpAgent(await resolveDeps(options.deps))
  const read = configurationReader(impl, message => RequestError.invalidParams(undefined, message))
  let creation, registration
  const operation = configurationOperations({ agent: impl, read,
    assertIdle(sessionId) {
      const session = impl.live.get(sessionId)
      if (creation?.isBusy() || registration?.isBusy() || !session || impl.disposed || session.disposed || session.closing || session.busy)
        throw RequestError.invalidParams(undefined, 'Session/provider operation busy or unavailable')
    },
    invalidParams: message => RequestError.invalidParams(undefined, message) })
  creation = piCreation({ agent: impl, read,
    invalidParams: message => RequestError.invalidParams(undefined, message) })
  registration = piProviderRegistration({ agent: impl, read, creation,
    invalidParams: message => RequestError.invalidParams(undefined, message) })
  const lifecycle = work => {
    if (registration.isBusy() || [...impl.live.keys()].some(id => operation.isBusy(id)))
      throw RequestError.invalidParams(undefined, 'Session/provider operation busy or unknown')
    return creation.lifecycle(work)
  }
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
    .onRequest(methods.agent.session.new, c => creation.create(c.params, () => impl.newSession(c)))
    .onRequest(methods.agent.session.load, c => lifecycle(() => impl.loadSession(c)))
    .onRequest(methods.agent.session.resume, c => lifecycle(() => impl.resumeSession(c)))
    .onRequest(methods.agent.session.fork, c => lifecycle(() => impl.forkSession(c)))
    .onRequest(methods.agent.session.list, c => impl.listSessions(c))
    .onRequest(methods.agent.session.close, c => lifecycle(() => impl.closeSession(c)))
    .onRequest(methods.agent.session.setConfigOption, c => operation.withSession(c.params.sessionId, () => impl.setConfigOption(c)))
    .onRequest(methods.agent.session.prompt, c => operation.withSession(c.params.sessionId, () => impl.prompt(c)))
    .onRequest(SESSION_STEERING_METHOD, steeringRequestParser, c => {
      if (registration.isBusy()) throw RequestError.invalidParams(undefined, 'Provider registration pending')
      return impl.steer(c)
    })
    .onRequest(LOADED_TURN_QUERY_METHOD, loadedTurnQueryParser, c => impl.loadedTurnQuery(c))
    .onRequest('_ordessa/channel/configuration/prepare', { parse: creation.parse }, c => creation.prepare(c.params))
    .onRequest('_ordessa/channel/configuration/operation', { parse: creation.parseQuery }, c => creation.query(c.params))
    .onRequest(CONFIGURATION_QUERY, parser, c => {
      const observed = read(c.params)
      return { ...observed, busy: observed.busy || operation.isBusy(c.params.sessionId) || creation.isBusy() || registration.isBusy() }
    })
    .onRequest(PROVIDER_REGISTER, { parse: registration.parse }, c =>
      operation.withSession(c.params.sessionId, () => registration.apply(c.params)))
    .onRequest('_ordessa/session/configuration/provider-capability', parser, c => {
      read(c.params)
      return { supported: impl.live.size === 1, strategy: 'live-registration', version: 1 }
    })
    .onRequest(CONFIGURATION_APPLY, { parse: operation.parseApply }, c => operation.apply(c.params))
    .onRequest(CONFIGURATION_OPERATION, { parse: operation.parseQuery }, c =>
      c.params.operationId.startsWith('provider:') ? registration.query(c.params) : operation.query(c.params))
    .onNotification(methods.agent.session.cancel, c => impl.cancel(c))
  const stream = options.stream ?? ndJsonStream(Writable.toWeb(process.stdout), Readable.toWeb(process.stdin))
  return { connection: app.connect(stream), agent: impl }
}
