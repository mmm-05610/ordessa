// The LOADABLE entry of `ordessa.model-provider-chat` (extension
// `ordessa.model-provider-chat`, optional product plugin).
//
// T4.1 (2026-10-01): this file used to register through the package-local
// transcription of the unmerged Chat contract, on a footer slot the frozen
// chat-api contract does not have, so the shipped Chat registry never saw a
// model selector at all. It now consumes the REAL published contracts only:
//
//   - `ChatContributionsToken` → the real scoped contribution service, on the
//     real composer slot (`composer.toolbar`, see chat-api-entry.tsx §SLOT);
//   - `UiComponentsToken`       → the component bound to this domain's key,
//     because Chat renders a contribution by resolving its key through
//     `ui.bind(key, { required: false })`; a key with no provider renders
//     nothing, so registering the contribution alone is not enough;
//   - `WirePortToken`           → the platform's ONE Server wire port, adapted
//     here to the consumer's `WireInvoke`. Without it the next-turn queue has
//     no transport and the selector would be a control that cannot reach the
//     Server, so activation refuses with a typed reason instead.
//
// Nothing in this file reads a Provider list itself: rows come from the shared
// `ModelProviderService` (`ModelProviderToken`), never from a second copy.
import type { PluginContext } from '@ordessa/extension-api'
import type { ResourceScope } from '@ordessa/extension-api'
import {
  ChatContributionsToken, type ChatContributionsService,
} from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, WirePortToken, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import type { WirePort, WireResult } from '@extensions/ordessa.contracts/contract.js'
import { ModelProviderToken, type ModelProviderService } from '../../contracts/index'
import { MODEL_SELECTOR_ID, ModelSelectorKey, modelSelectorComponent, registerModelSelector } from './chat-api-entry'

/** The provider id this domain registers its component under; the ui-components
 * config binds `ModelSelectorKey` to it the same way it binds the Profile
 * picker to `ordessa.profile-chat`. */
export const COMPONENT_PROVIDER_ID = 'ordessa.model-provider-chat'

export const TRANSPORT_MISSING = 'MODEL_PROVIDER_CHAT_TRANSPORT_MISSING'

/** WireResult 三态 → the consumer's `WireInvoke`: `Accepted` hands over the
 * result; `Refused`/`Unknown` raise a typed error carrying the platform reason,
 * so the consumer's own three-state handling sees a fact, never a guess. */
function wireInvokeOf(wire: WirePort) {
  return async (method: string, params: object): Promise<unknown> => {
    const result: WireResult = await wire.call(method, params as Readonly<Record<string, unknown>>)
    if (result.kind === 'Accepted') return result.result
    const error = new Error(`model-provider ${method}: ${result.kind}`) as Error & { details?: { internalCode?: string } }
    error.details = { internalCode: result.reason }
    throw error
  }
}

export default function createPlugin() {
  return {
    id: 'ordessa.model-provider-chat',
    autoStart: true,
    requires: [ChatContributionsToken, UiComponentsToken, WirePortToken, ModelProviderToken],
    activate(context: PluginContext, chat: ChatContributionsService, ui: UiComponents,
            wire: WirePort, service: ModelProviderService) {
      if (wire === undefined || wire === null) {
        throw new Error(
          `${TRANSPORT_MISSING}: no Server wire port was provided for the composer model selector; ` +
          'the host must resolve ordessa.wirePort.v1 - refusing a selector that cannot reach the Server')
      }
      const wiring = { service, invoke: wireInvokeOf(wire) }
      const registration = registerModelSelector(chat, context.resources, wiring)
      const provider = ui.forScope(context.resources).register({
        key: ModelSelectorKey,
        providerId: COMPONENT_PROVIDER_ID,
        component: modelSelectorComponent(wiring),
      })
      context.resources.add(registration)
      context.resources.add(provider)
      return { contributionId: MODEL_SELECTOR_ID }
    },
  }
}

export { MODEL_SELECTOR_ID, ModelSelectorKey } from './chat-api-entry'
