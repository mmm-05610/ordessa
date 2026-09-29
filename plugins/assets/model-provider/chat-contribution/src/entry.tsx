// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/entry.tsx, verbatim)
import type { PluginContext } from '@ordessa/extension-api'
import type { ResourceScope } from '@ordessa/extension-api'
import { ModelProviderToken, type ModelProviderService } from '../../contracts/index'
import { ChatContributionsToken, type ChatContributions } from './stub-chat-contract'
import { ModelSelector } from './selector'

/** Registers the composer.footer model selector against Chat's public
 * contribution contract only - never Chat's internal store (design.md §5).
 * Unloading this extension disposes the registration; Chat itself is
 * untouched. */
export default function createPlugin() {
  return {
    id: 'ordessa.model-provider-chat',
    autoStart: true,
    requires: [ChatContributionsToken, ModelProviderToken],
    activate(context: PluginContext, chat: ChatContributions, service: ModelProviderService) {
      const disposable = chat.forScope(context.resources).add({
        id: 'model-provider.composer.footer',
        slot: 'composer.footer',
        // The contract hands the component { location } only; the lane's
        // service is closed over here, not passed through Chat.
        component: (props) => <ModelSelector service={service} location={props.location} />,
      })
      context.resources.add(disposable)
    },
  }
}
