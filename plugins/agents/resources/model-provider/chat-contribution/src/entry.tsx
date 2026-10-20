import type { PluginContext } from '@ordessa/extension-api'
import { ChatContributionsToken, type ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import { ModelProviderToken, type ModelProviderService } from '@extensions/ordessa.model-provider/contract.js'
import {
  CANONICAL_MODEL_SELECTOR_ID, CanonicalModelSelectorKey,
  canonicalModelSelectorComponent, registerCanonicalModelSelector,
} from './canonical-selector'

export const COMPONENT_PROVIDER_ID = 'ordessa.model-provider-chat'
export const MODEL_SELECTOR_ID = CANONICAL_MODEL_SELECTOR_ID

/** Exposes Provider resources in Chat; configuration application is unsupported. */
export default function createPlugin() {
  return {
    id: 'ordessa.model-provider-chat',
    autoStart: true,
    requires: [ChatContributionsToken, UiComponentsToken, ModelProviderToken],
    activate(context: PluginContext, chat: ChatContributionsService, ui: UiComponents,
      service: ModelProviderService) {
      const provider = ui.forScope(context.resources).register({
        key: CanonicalModelSelectorKey,
        providerId: COMPONENT_PROVIDER_ID,
        component: canonicalModelSelectorComponent({ service }),
      })
      context.resources.add(provider)
      context.resources.add(registerCanonicalModelSelector(chat, context.resources))
      return { contributionId: MODEL_SELECTOR_ID }
    },
  }
}

export { CanonicalModelSelectorKey as ModelSelectorKey }
