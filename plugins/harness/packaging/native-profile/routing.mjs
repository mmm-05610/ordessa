/** Non-secret native construction facts; never provider-list or desired-state evidence. */
export function safeNativeRoute(input) {
  if (!input || !['custom-gateway', 'main'].includes(input.provider)
      || !['responses', 'anthropic'].includes(input.api)
      || (input.provider === 'custom-gateway' ? input.api !== 'responses' : input.api !== 'anthropic')
      || typeof input.baseUrl !== 'string' || !input.baseUrl || input.baseUrl.length > 4096
      || input.baseUrl.trim() !== input.baseUrl || /[\u0000-\u001f\u007f]/u.test(input.baseUrl)) return null
  let url
  try { url = new URL(input.baseUrl) } catch { return null }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) return null
  return { provider: input.provider, api: input.api, baseUrl: input.baseUrl }
}

export function captureCodexThreadRoute(params, response) {
  if (params?.modelProvider !== 'custom-gateway' || response?.modelProvider !== params.modelProvider) return null
  const config = params.config?.model_providers?.[params.modelProvider]
  return safeNativeRoute({ provider: params.modelProvider, api: config?.wire_api, baseUrl: config?.base_url })
}
