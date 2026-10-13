import { safeEndpoint } from "../../../../../../../packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/endpoint.mjs"
export function safeNativeRoute(input) {
  if (!input || input.provider !== 'main' || input.api !== 'anthropic' || !safeEndpoint(input.baseUrl)) return null
  return {provider: input.provider, api: input.api, baseUrl: input.baseUrl}
}
