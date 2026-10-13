import { nativeConfigurationReader } from "./reader.mjs"
import { configurationOperations } from "./operation.mjs"
import { restorationOperations } from "./restoration.mjs"
import { stableJSON, jsonDigest } from "./digest.mjs"

export function nativeProfileBridge(agent, strategy, invalidParams) {
  const { read, assertIdle } = nativeConfigurationReader({ agent, strategy, invalidParams })
  let providerBusy = false
  let lifecycleBusy = 0
  const creations = new Map()
  let initial = null
  const creationParser = { parse(input) {
    const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
      && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
    const text = (value, max = 4096) => typeof value === 'string' && value.length > 0
      && value.length <= max && value === value.trim() && !/[\u0000-\u001f\u007f]/u.test(value)
    if (strategy.supportsManagedAccount && exact(input, ['operationId', 'provider', 'model'])
        && text(input.operationId, 128) && input.operationId.startsWith('create:') && text(input.model)
        && exact(input.provider, ['providerId', 'authentication'])
        && input.provider.providerId === strategy.managedProviderId && input.provider.authentication === 'managed-account')
      return structuredClone(input)
    const keys = ['operationId', 'provider', 'model']
    if (strategy.supportsModelCapabilities && Object.hasOwn(input ?? {}, 'modelCapabilities')) keys.push('modelCapabilities')
    if (!exact(input, keys) || !text(input.operationId, 128)
        || !input.operationId.startsWith('create:') || !text(input.model)
        || (!exact(input.provider, ['providerId', 'apiType', 'baseUrl'])
          && !exact(input.provider, ['providerId', 'apiType', 'baseUrl', 'headers']))
        || !['providerId', 'apiType', 'baseUrl'].every(key => text(input.provider[key])))
      throw invalidParams('Expected exact initial provider/model configuration')
    let url
    try { url = new URL(input.provider.baseUrl) } catch { throw invalidParams('Invalid initial endpoint') }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash)
      throw invalidParams('Unsafe initial endpoint')
    const headers = input.provider.headers
    if (headers !== undefined && (!headers || typeof headers !== 'object' || Array.isArray(headers)
        || Object.keys(headers).length > 32 || Object.entries(headers).some(([key, value]) =>
          !/^[a-zA-Z0-9-]{1,128}$/u.test(key) || !text(value, 8192))))
      throw invalidParams('Invalid initial headers')
    if (Buffer.byteLength(stableJSON(input)) > 65536) throw invalidParams('Initial configuration exceeds bounds')
    if (input.provider.providerId !== strategy.providerId
        || input.provider.apiType !== strategy.apiType)
      throw invalidParams('Unsupported initial provider protocol')
    return structuredClone(input)
  } }
  const creationQueryParser = { parse(input) {
    if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).length !== 1
        || typeof input.operationId !== 'string' || !input.operationId.startsWith('create:')
        || input.operationId.length > 128 || /[\u0000-\u001f\u007f]/u.test(input.operationId))
      throw invalidParams('Expected exact initial operation query')
    return input
  } }
  const operation = configurationOperations({ agent, read, invalidParams,
    configIds: strategy.configIds,
    evidencePrefix: strategy.ownerId + '-native-operation',
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
  const withLifecycle = async work => {
    if (providerBusy) throw invalidParams('Provider operation busy')
    lifecycleBusy++
    try { return await work() } finally { lifecycleBusy-- }
  }
  const withProvider = async work => {
    if (providerBusy || lifecycleBusy) throw invalidParams('Provider/lifecycle operation busy')
    const ids = strategy.ids(agent)
    for (const sessionId of ids) {
      assertIdle(sessionId)
      if (operation.isBusy(sessionId)) throw invalidParams('Session operation busy')
    }
    providerBusy = true
    try { return await work() } finally { providerBusy = false }
  }
  const restoration = restorationOperations({ read, withProvider, invalidParams, strategy,
    preflight(input) {
      const ids = strategy.ids(agent)
      if (ids.length !== 1 || ids[0] !== input.sessionId)
        throw invalidParams('Provider restoration requires one dedicated live session')
      strategy.preflightRestoration({input,agent,creations,invalidParams})
    }, async restore(input) {
      const stepFailure = (phase, detail) => {
        const failure = new Error('Native restoration step failed')
        failure.restorationPhase = phase
        // Classify locally; never retain upstream text or headers.
        failure.restorationReason = /rollout|not found|no saved|not persisted/iu.test(detail)
          ? 'native-history-unavailable' : /auth|credential/iu.test(detail)
            ? 'native-authentication-rejected' : /model/iu.test(detail)
              ? 'native-model-rejected' : 'native-request-rejected'
        return failure
      }
      const step = async (phase, work) => {
        try { return await work() } catch (error) {
          throw stepFailure(phase, String(error?.message ?? ''))
        }
      }
      return strategy.restore({agent,input,read,creations,step,stepFailure})
    } })
  return { operation, restoration, parser, creationParser, creationQueryParser,
    async prepareCreation(input) {
      input = creationParser.parse(input)
      const digest = jsonDigest(input)
      if (initial) {
        if (initial.record.operationId !== input.operationId || initial.record.inputDigest !== digest)
          throw invalidParams('Initial configuration already reserved')
        return structuredClone(initial.record)
      }
      return withProvider(async () => {
        const count = strategy.count(agent)
        if (count !== 0) throw invalidParams('Initial configuration requires a dedicated empty adapter')
        const record = { operationId: input.operationId, inputDigest: digest, state: 'unknown',
          kind: 'initial-provider-model', phase: 'preparing', after: null }
        // Reserve before any provider effect. Failure/replay never runs it twice.
        initial = { input, record, attempted: false }
        try {
          await strategy.prepareInitial({agent,input,invalidParams})
          record.state = 'prepared'; record.phase = 'awaiting-native-creation'
        } catch { record.phase = 'preparation-outcome-unknown' }
        return structuredClone(record)
      })
    }, queryCreation(input) {
      input = creationQueryParser.parse(input)
      if (!initial || input.operationId !== initial.record.operationId)
        throw invalidParams('Unknown initial configuration operation')
      return structuredClone(initial.record)
    },
    apply(input) {
      if (input.operationId?.startsWith('restore:')) throw invalidParams('Reserved restoration operation namespace')
      return operation.apply(input)
    }, queryOperation(input) {
      return input.operationId?.startsWith('restore:') ? restoration.query(input) : operation.query(input)
    }, async withCreation(params, work) {
      if (creations.size >= 128 && !creations.has(params.sessionId))
        throw invalidParams('Session creation evidence capacity exhausted')
      if (Buffer.byteLength(stableJSON(params)) > 65536) throw invalidParams('Session creation evidence exceeds bounds')
      const captured = structuredClone(params)
      return withLifecycle(async () => {
        const configuringInitial = initial && !Object.hasOwn(captured, 'sessionId')
        if (configuringInitial) {
          if (initial.attempted) throw invalidParams('Initial creation already attempted')
          if (initial.record.state !== 'prepared' || captured.sessionId
              || !strategy.isFreshCreation(captured))
            throw invalidParams('Initial configuration requires a fresh native creation')
          initial.attempted = true
          initial.record.state = 'unknown'; initial.record.phase = 'creating'
          strategy.augmentInitialCreation(captured, initial)
        }
        const result = await work(captured)
        const sessionId = params.sessionId ?? result.sessionId
        if (strategy.retainsCreation(agent, sessionId)) creations.set(sessionId, captured)
        if (configuringInitial) {
          initial.record.after = read({ sessionId })
          initial.record.phase = 'initial-model-application'
          // Standard ACP model selection requires a live session. Apply it
          // immediately after creation, before returning the prepared session
          // to its caller; no prompt, close or resume occurs here.
          await agent.setSessionConfigOption({ sessionId, configId: 'model', value: initial.input.model })
          const after = read({ sessionId })
          initial.record.after = after
          const selected = after.configOptions.filter(item => item.id === 'model')
          if (after.busy || selected.length !== 1 || selected[0].currentValue !== initial.input.model) {
            initial.record.phase = 'initial-readback-mismatch'
            throw invalidParams('Initial model readback differs')
          }
          const flatten = options => options.flatMap(option => [option, ...flatten(option.options ?? [])])
          const models = flatten(selected[0].options).filter(option => option.value === initial.input.model)
          const route = models.length === 1 ? models[0]._meta?.ordessaModel : null
          const managed = initial.input.provider.authentication === 'managed-account'
          if (!route || route.provider !== initial.input.provider.providerId
              || route.api !== strategy.nativeApi
              || route.baseUrl !== (managed ? null : initial.input.provider.baseUrl)
              || managed && route.authentication !== 'managed-account' || route.model !== initial.input.model) {
            initial.record.phase = 'initial-route-readback-mismatch'
            throw invalidParams('Initial native construction routing differs')
          }
          initial.record.state = 'observed'; initial.record.phase = 'initial-model-readback'
          // This is creation evidence, never a Profile C4 receipt or proof of every resource.
        }
        return result
      })
    }, read(input) {
    const observed = read(input)
    return { ...observed, busy: observed.busy || providerBusy || operation.isBusy(input.sessionId) }
  }, withLifecycle, withProvider,
    withExternalProvider(work) {
      if (strategy.externalProviderRefused())
        throw invalidParams('Managed account route cannot be changed by session clients')
      return withProvider(work)
    } }
}
