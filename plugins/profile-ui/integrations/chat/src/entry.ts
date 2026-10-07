import type { PluginContext } from '@ordessa/extension-api'
import { ProfileServiceToken, type ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { ChatContributionsToken, type ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, WirePortToken, type UiComponents, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { AgentSessionsToken, type AgentSessions, createWireConfigurationClient } from '@extensions/ordessa.agent-contracts/contract.js'
import { ProfileCatalog } from './catalog'
import { createCanonicalProfileGlue, CanonicalProfilePickerKey } from './canonical-glue'
import { ProfilePicker } from './picker'

/** The optional Profile consumer writes only through the backend Agent owner. */
export default function createPlugin() {
  return {
    id: 'ordessa.profile-chat',
    autoStart: true,
    requires: [ProfileServiceToken, ChatContributionsToken, UiComponentsToken, WirePortToken, AgentSessionsToken],
    activate(
      context: PluginContext,
      profiles: ProfileServiceClient,
      chat: ChatContributionsService,
      ui: UiComponents,
      wire: WirePort,
      sessions: AgentSessions,
    ) {
      const catalog = context.resources.add(new ProfileCatalog(profiles))
      const configuration = createWireConfigurationClient({ wire, sessions, scope: context.resources })
      ui.forScope(context.resources).register({
        key: CanonicalProfilePickerKey,
        providerId: 'ordessa.profile-chat',
        component: ProfilePicker,
      })
      const glue = createCanonicalProfileGlue(context.resources, chat, {
        profiles,
        catalog: () => catalog.groups,
        catalogState: catalog,
        configuration,
      })
      void catalog.refresh()
      return glue
    },
  }
}

export { CanonicalProfilePickerKey as ProfilePickerKey } from './canonical-glue'
