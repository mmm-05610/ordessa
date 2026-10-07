import type { PluginContext } from '@ordessa/extension-api'
import { ChatContributionsToken, type ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, WirePortToken, type UiComponents, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { AgentSessionsToken, type AgentSessions, createWireConfigurationClient } from '@extensions/ordessa.agent-contracts/contract.js'
import { ModelProviderToken, type ModelProviderService } from '@extensions/ordessa.model-provider/contract.js'
import {
  CANONICAL_MODEL_SELECTOR_ID, CanonicalModelSelectorKey,
  canonicalModelSelectorComponent, registerCanonicalModelSelector,
} from './canonical-selector'

export const COMPONENT_PROVIDER_ID = 'ordessa.model-provider-chat'
export const MODEL_SELECTOR_ID = CANONICAL_MODEL_SELECTOR_ID
export const TRANSPORT_MISSING = 'MODEL_PROVIDER_CHAT_TRANSPORT_MISSING'

/** Model selection writes intent to Agent's backend-owned configuration. */
export default function createPlugin() {
  return {
    id: 'ordessa.model-provider-chat',
    autoStart: true,
    requires: [ChatContributionsToken, UiComponentsToken, WirePortToken, ModelProviderToken, AgentSessionsToken],
    activate(context: PluginContext, chat: ChatContributionsService, ui: UiComponents,
      wire: WirePort | undefined, service: ModelProviderService, sessions: AgentSessions) {
      if (wire === undefined) throw new Error(TRANSPORT_MISSING)
      const configuration = createWireConfigurationClient({ wire, sessions, scope: context.resources })
      const provider = ui.forScope(context.resources).register({
        key: CanonicalModelSelectorKey,
        providerId: COMPONENT_PROVIDER_ID,
        component: canonicalModelSelectorComponent({ service, wire, configuration }),
      })
      context.resources.add(provider)
      context.resources.add(registerCanonicalModelSelector(chat, context.resources, configuration, { service, wire }))
      return { contributionId: MODEL_SELECTOR_ID }
    },
  }
}

export { CanonicalModelSelectorKey as ModelSelectorKey }
