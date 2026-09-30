import type { PluginContext } from '@ordessa/extension-api'
import { ProfileServiceToken, type ProfileServiceClient } from '@extensions/ordessa.profile-api/contract.js'
import { ChatContributionsToken, type ChatContributionsService } from '@extensions/ordessa.chat-api/contract.js'
import { UiComponentsToken, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import { ProfileCatalog } from './catalog'
import { createProfileChatGlue, ProfilePickerKey } from './glue'
import { ProfilePicker } from './picker'

export default function createPlugin() {
  return { id: 'ordessa.profile-chat', autoStart: true,
    requires: [ProfileServiceToken, ChatContributionsToken, UiComponentsToken],
    activate(context: PluginContext, profiles: ProfileServiceClient, chat: ChatContributionsService, ui: UiComponents) {
      const catalog = context.resources.add(new ProfileCatalog(profiles))
      ui.forScope(context.resources).register({ key: ProfilePickerKey, providerId: 'ordessa.profile-chat', component: ProfilePicker })
      const glue = createProfileChatGlue(context.resources, chat, {
        profiles, catalog: () => catalog.groups, catalogState: catalog,
      })
      void catalog.refresh()
      return glue
    },
  }
}
export { createProfileChatGlue, ProfilePickerKey } from './glue'
export { ProfileSelectionStore } from './selection'
