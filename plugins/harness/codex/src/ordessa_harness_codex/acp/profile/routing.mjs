import { safeEndpoint } from "../../../../../../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/endpoint.mjs"
export function safeNativeRoute(input) {
  if (input?.provider === 'openai' && input.api === 'responses' && input.baseUrl === null && input.authentication === 'managed-account')
    return { provider: 'openai', api: 'responses', baseUrl: null, authentication: 'managed-account' }
  if (!input || input.provider !== 'custom-gateway' || input.api !== 'responses' || !safeEndpoint(input.baseUrl)) return null
  return {provider: input.provider, api: input.api, baseUrl: input.baseUrl}
}
export function captureCodexThreadRoute(params, response, { managedAccountVerified = false } = {}) {
  if (managedAccountVerified === true && [undefined, null, 'openai'].includes(params?.modelProvider)
      && response?.modelProvider === 'openai' && !params?.config?.model_provider
      && !params?.config?.model_providers?.openai)
    return safeNativeRoute({ provider: 'openai', api: 'responses', baseUrl: null, authentication: 'managed-account' })
  if (params?.modelProvider !== 'custom-gateway' || response?.modelProvider !== params.modelProvider) return null
  const config = params.config?.model_providers?.[params.modelProvider]
  return safeNativeRoute({ provider: params.modelProvider, api: config?.wire_api, baseUrl: config?.base_url })
}
