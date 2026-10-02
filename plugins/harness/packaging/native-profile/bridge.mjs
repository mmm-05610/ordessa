import { nativeConfigurationReader } from './ordessa-native-configuration-query.mjs'
import { configurationOperations } from './ordessa-configuration-operation.mjs'
import { restorationOperations } from './ordessa-restoration.mjs'
import { stableJSON, jsonDigest } from './ordessa-configuration-query.mjs'

export function nativeProfileBridge(agent, brand, invalidParams) {
  const { read, assertIdle } = nativeConfigurationReader({ agent, brand, invalidParams })
  let providerBusy = false
  let lifecycleBusy = 0
  const creations = new Map()
  let initial = null
  const creationParser = { parse(input) {
    const exact = (value, keys) => value && typeof value === 'object' && !Array.isArray(value)
      && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key))
    const text = (value, max = 4096) => typeof value === 'string' && value.length > 0
      && value.length <= max && value === value.trim() && !/[\u0000-\u001f\u007f]/u.test(value)
    if (brand === 'codex' && exact(input, ['operationId', 'provider', 'model'])
        && text(input.operationId, 128) && input.operationId.startsWith('create:') && text(input.model)
        && exact(input.provider, ['providerId', 'authentication'])
        && input.provider.providerId === 'openai' && input.provider.authentication === 'managed-account')
      return structuredClone(input)
    const keys = ['operationId', 'provider', 'model']
    if (brand === 'codex' && Object.hasOwn(input ?? {}, 'modelCapabilities')) keys.push('modelCapabilities')
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
    if (input.provider.providerId !== (brand === 'codex' ? 'custom-gateway' : 'main')
        || input.provider.apiType !== (brand === 'codex' ? 'openai' : 'anthropic'))
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
  const withLifecycle = async work => {
    if (providerBusy) throw invalidParams('Provider operation busy')
    lifecycleBusy++
    try { return await work() } finally { lifecycleBusy-- }
  }
  const withProvider = async work => {
    if (providerBusy || lifecycleBusy) throw invalidParams('Provider/lifecycle operation busy')
    const ids = brand === 'codex' ? [...agent.sessions.keys()] : Object.keys(agent.sessions)
    for (const sessionId of ids) {
      assertIdle(sessionId)
      if (operation.isBusy(sessionId)) throw invalidParams('Session operation busy')
    }
    providerBusy = true
    try { return await work() } finally { providerBusy = false }
  }
  const restoration = restorationOperations({ read, withProvider, invalidParams,
    preflight(input) {
      const ids = brand === 'codex' ? [...agent.sessions.keys()] : Object.keys(agent.sessions)
      if (ids.length !== 1 || ids[0] !== input.sessionId)
        throw invalidParams('Provider restoration requires one dedicated live session')
      const managed = input.provider.providerId === 'openai' && input.provider.authentication === 'managed-account'
      if (brand === 'codex' && ((!managed && (input.provider.providerId !== 'custom-gateway'
          || input.provider.apiType !== 'openai')) || !creations.has(input.sessionId)
          || typeof agent.ordessaReplaceCodexProcess !== 'function'))
        throw invalidParams('Captured Codex session and supported gateway required')
      if (brand === 'claude-code' && (input.provider.providerId !== 'main' || input.provider.apiType !== 'anthropic'))
        throw invalidParams('Supported Claude provider required')
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
      if (brand === 'codex') {
        const params = structuredClone(creations.get(input.sessionId))
        const preserved = read({ sessionId: input.sessionId }).configOptions
          .filter(item => item.id !== 'model')
        await step('restart', () => agent.ordessaReplaceCodexProcess(input))
        const managed = input.provider.authentication === 'managed-account'
        if (!managed) await step('provider', () => agent.setProvider(input.provider))
        try {
          await step('resume', () => agent.resumeSession({ ...params, sessionId: input.sessionId }))
        } finally {
          delete agent.codexAcpClient.ordessaResumeRolloutPath
        }
        await step('model', () => agent.setSessionConfigOption({ sessionId: input.sessionId, configId: 'model', value: input.model }))
        for (const item of preserved) {
          try {
            await step('preferences', () => agent.setSessionConfigOption({ sessionId: input.sessionId, configId: item.id, value: item.currentValue }))
            // Re-offering is not preservation: read the independently live value
            // back, never report a restarted default as the user's choice.
            const applied = read({ sessionId: input.sessionId }).configOptions
              .find(option => option.id === item.id)
            const native = agent.sessions.get(input.sessionId)
            // Upstream hides the fast selector when the selected model has no
            // fast tier. Off remains off only with explicit native proof; an
            // enabled or unknown state cannot pass this exception.
            const disabledFast = !applied && item.id === 'fast-mode'
              && (item.currentValue === 'off' || item.currentValue === false)
              && native?.currentModelSupportsFast === false && native?.fastModeEnabled === false
            if (!disabledFast && (!applied || applied.currentValue !== item.currentValue))
              throw stepFailure('preferences', `preserved preference ${item.id} readback differs`)
          } catch (failure) {
            if (['mode', 'collaboration_mode', 'reasoning_effort', 'fast-mode'].includes(item.id))
              failure.restorationPreference = item.id
            throw failure
          }
        }
        const session = agent.sessions.get(input.sessionId)
        const route = agent.codexAcpClient?.codexClient?.ordessaThreadRoutes?.get(input.sessionId)
        if (managed) return session && session.authProvider === 'openai' && route?.provider === 'openai'
          && route?.authentication === 'managed-account'
          ? {sessionId: input.sessionId, providerId: 'openai', authentication: 'managed-account'} : null
        if (!session || session.authProvider !== 'custom-gateway') return null
        return { sessionId: input.sessionId, apiType: route?.api === 'responses' ? 'openai' : null, baseUrl: route?.baseUrl }
      }
      await step('provider', () => agent.unstable_setProvider(input.provider))
      const session = agent.sessions[input.sessionId]
      if (!session || session.queryClosed) return null
      await step('model', () => agent.setSessionConfigOption({ sessionId: input.sessionId, configId: 'model', value: input.model }))
      // This field is injected at the pinned upstream SDK-query construction,
      // not copied from providers/list or from this restore request.
      return { sessionId: input.sessionId, ...session.ordessaProviderRoute }
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
        const count = brand === 'codex' ? agent.sessions.size : Object.keys(agent.sessions).length
        if (count !== 0) throw invalidParams('Initial configuration requires a dedicated empty adapter')
        const record = { operationId: input.operationId, inputDigest: digest, state: 'unknown',
          kind: 'initial-provider-model', phase: 'preparing', after: null }
        // Reserve before any provider effect. Failure/replay never runs it twice.
        initial = { input, record, attempted: false }
        try {
          if (brand === 'codex') {
            if (input.provider.authentication === 'managed-account') {
              if (!process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR
                  || agent.codexAcpClient.getModelProvider() !== null)
                throw invalidParams('Explicit managed account launch required')
              const account = await agent.codexAcpClient.codexClient.accountRead({ refreshToken: true })
              if (account.account?.type !== 'chatgpt') throw invalidParams('Managed account login required')
            } else {
              if (process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR)
                throw invalidParams('API provider requires a separate private instance')
              if (Object.hasOwn(input, 'modelCapabilities')) {
                if (typeof agent.ordessaPrepareCodexCatalog !== 'function')
                  throw invalidParams('Native model catalogue launch unavailable')
                await agent.ordessaPrepareCodexCatalog(input)
              }
              await agent.setProvider(input.provider)
            }
          } else await agent.unstable_setProvider(input.provider)
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
              || captured._meta?.claudeCode?.options?.resume)
            throw invalidParams('Initial configuration requires a fresh native creation')
          initial.attempted = true
          initial.record.state = 'unknown'; initial.record.phase = 'creating'
          if (brand === 'claude-code') captured._meta = { ...captured._meta,
            claudeCode: { ...captured._meta?.claudeCode,
              options: { ...captured._meta?.claudeCode?.options, model: initial.input.model } } }
        }
        const result = await work(captured)
        const sessionId = params.sessionId ?? result.sessionId
        if (brand === 'codex' && agent.sessions.has(sessionId)) creations.set(sessionId, captured)
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
              || route.api !== (managed || initial.input.provider.apiType === 'openai' ? 'responses' : 'anthropic')
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
      if (brand === 'codex' && process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR)
        throw invalidParams('Managed account route cannot be changed by session clients')
      return withProvider(work)
    } }
}
