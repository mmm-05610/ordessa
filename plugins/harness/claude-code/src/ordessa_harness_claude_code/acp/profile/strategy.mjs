import { safeNativeRoute } from './routing.mjs'
export const strategy = Object.freeze({
  ownerId: 'claude-code', providerId: 'main', apiType: 'anthropic', nativeApi: 'anthropic', managedProviderId: 'openai', supportsManagedAccount: false, supportsModelCapabilities: false,
  configIds: Object.freeze(['model', 'effort']), includeCurrentModel: true,
  session: (agent,id) => Object.hasOwn(agent.sessions,id) ? agent.sessions[id] : undefined, closing: () => false,
  ids: agent => Object.keys(agent.sessions), count: agent => Object.keys(agent.sessions).length,
  busy: (agent,session) => !!agent.providerUpdate || !!session.activeTurn || (session.turnQueue ?? []).some(turn => !turn.settled),
  options: (agent,session) => session.configOptions,
  captureRoute: (agent,session) => ({ provider: 'main', api: session.ordessaProviderRoute?.apiType, baseUrl: session.ordessaProviderRoute?.baseUrl }),
  routeMatches: () => true, retainsCreation: () => false,
  augmentInitialCreation(captured, initial) { captured._meta = { ...captured._meta, claudeCode: { ...captured._meta?.claudeCode, options: { ...captured._meta?.claudeCode?.options, model: initial.input.model } } } },
  externalProviderRefused: () => false,
  safeNativeRoute,
  restorationCapabilitiesAllowed: () => false,
  isFreshCreation: captured => !captured._meta?.claudeCode?.options?.resume,
  preflightRestoration({input,agent,creations,invalidParams}) {
    if (input.provider.providerId !== 'main' || input.provider.apiType !== 'anthropic') throw invalidParams('Supported Claude provider required')
  },
  async restore({agent,input,read,creations,step,stepFailure}) {
      await step('provider', () => agent.unstable_setProvider(input.provider))
      const session = agent.sessions[input.sessionId]
      if (!session || session.queryClosed) return null
      await step('model', () => agent.setSessionConfigOption({ sessionId: input.sessionId, configId: 'model', value: input.model }))
      // This field is injected at the pinned upstream SDK-query construction,
      // not copied from providers/list or from this restore request.
      return { sessionId: input.sessionId, ...session.ordessaProviderRoute }

  },
  async prepareInitial({agent,input,invalidParams}) {
    await agent.unstable_setProvider(input.provider)
  }
})
