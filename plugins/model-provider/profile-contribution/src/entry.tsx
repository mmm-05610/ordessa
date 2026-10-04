import type { PluginContext } from '@ordessa/extension-api'
import { UiComponentsToken, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import {
  profileFacetEditorKey,
  type ProfileFacetEditorProps,
} from '@extensions/ordessa.profile-api/contract.js'
import {
  ModelProviderToken,
  type ModelProviderService,
} from '@extensions/ordessa.model-provider/contract.js'
import { ModelProfileEditor } from './profile-editor'

/** Optional bridge that supplies Model Provider's editor to Profile. */
export default function createPlugin() {
  return {
    id: 'ordessa.model-provider-profile',
    autoStart: true,
    requires: [ModelProviderToken, UiComponentsToken],
    activate(context: PluginContext, service: ModelProviderService, ui: UiComponents) {
      ui.forScope(context.resources).register({
        key: profileFacetEditorKey('assets.model-provider'),
        // Keep the existing provider identity so saved Profile editor selections remain valid.
        providerId: 'ordessa.model-provider',
        component: (props: ProfileFacetEditorProps) => <ModelProfileEditor {...props} service={service} />,
      })
    },
  }
}
