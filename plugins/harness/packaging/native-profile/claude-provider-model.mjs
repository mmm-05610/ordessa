import { safeNativeRoute } from './ordessa-native-routing.mjs'

const boundedModel = value => typeof value === 'string'
  && /^[a-zA-Z0-9][a-zA-Z0-9._:/+-]{0,255}$/u.test(value)

/** Explicit external provider only. Candidate is NOT application evidence. */
export function providerModelCandidate(provider, session, value) {
  const route = safeNativeRoute({ provider: 'main', api: session?.ordessaProviderRoute?.apiType,
    baseUrl: session?.ordessaProviderRoute?.baseUrl })
  if (!boundedModel(value) || !route || provider?.apiType !== route.api
      || provider?.baseUrl !== route.baseUrl || session.queryClosed
      || !Array.isArray(session.models?.availableModels)
      || session.models.availableModels.length >= 512) return null
  return { value, name: value }
}

/** Called only after the native SDK accepted setModel; no guessed capabilities. */
export function retainAcceptedProviderModel(session, value) {
  if (!boundedModel(value)) throw new TypeError('Invalid accepted provider model')
  const models = session.models.availableModels
  if (!models.some(model => model.modelId === value))
    session.models = { ...session.models,
      availableModels: [...models, { modelId: value, name: value }] }
}
