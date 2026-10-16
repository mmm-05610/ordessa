import { safeNativeRoute } from './routing.mjs'
export const strategy = Object.freeze({
  ownerId: 'codex', providerId: 'custom-gateway', apiType: 'openai', nativeApi: 'responses', managedProviderId: 'openai', supportsManagedAccount: true, supportsModelCapabilities: true,
  configIds: Object.freeze(['model', 'reasoning_effort']), includeCurrentModel: false,
  session: (agent,id) => agent.sessions.get(id), closing: (agent,id) => agent.sessionIsClosing(id),
  ids: agent => [...agent.sessions.keys()], count: agent => agent.sessions.size,
  busy: (agent,session,id) => agent.activePrompts.has(id) || agent.pendingTurnStarts.has(id),
  options: (agent,session) => agent.createSessionConfigOptions(session),
  captureRoute: (agent,session,id) => agent.codexAcpClient?.codexClient?.ordessaThreadRoutes?.get(id),
  routeMatches: (session,route) => session.authProvider === route.provider || route.authentication === 'managed-account' && session.authProvider == null,
  retainsCreation: (agent,id) => agent.sessions.has(id),
  augmentInitialCreation: captured => {},
  externalProviderRefused: () => !!process.env.ORDESSA_CODEX_MANAGED_ACCOUNT_DIR,
  safeNativeRoute,
  restorationCapabilitiesAllowed: input => input?.provider?.providerId === 'custom-gateway' && input?.provider?.apiType === 'openai',
  isFreshCreation: captured => !captured._meta?.claudeCode?.options?.resume,
  preflightRestoration({input,agent,creations,invalidParams}) {
    const managed = input.provider.providerId === 'openai' && input.provider.authentication === 'managed-account'
    if ((!managed && (input.provider.providerId !== 'custom-gateway' || input.provider.apiType !== 'openai')) || !creations.has(input.sessionId) || typeof agent.ordessaReplaceCodexProcess !== 'function')
      throw invalidParams('Captured Codex session and supported gateway required')
  },
  async restore({agent,input,read,creations,step,stepFailure}) {
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
      
  },
  async prepareInitial({agent,input,invalidParams}) {
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
  }
})
