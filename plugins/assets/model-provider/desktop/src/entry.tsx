// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/entry.tsx, verbatim)
import type { PluginContext } from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { ModelProviderToken, type ModelProviderService, type WireInvoke } from '../../contracts/index'
import { createModelProviderService } from './service'
import { ModelProviderSettings } from './settings'

/** The settings section id is the extension's whole registration surface:
 * when this plugin is absent the Workbench shows no such section and the
 * rest of the shell is unaffected (G10 absence comparison). */
export const SETTINGS_SECTION_ID = 'model-provider.settings'

export const TRANSPORT_MISSING = 'MODEL_PROVIDER_TRANSPORT_MISSING'

/**
 * The Server wire invoke is not (yet) a PluginContext capability in this
 * baseline, so the product composition binds it here at assembly time.
 * Unbound transport = a typed activation refusal, never a settings page that
 * cannot reach the Server (integration dependency #6, plan.md §6).
 */
export function createPlugin(transport?: WireInvoke) {
  return {
    id: 'ordessa.model-provider',
    autoStart: true,
    requires: [WorkbenchToken],
    provides: ModelProviderToken,
    activate(context: PluginContext, workbench: Workbench): ModelProviderService {
      if (transport === undefined) {
        throw new Error(
          `${TRANSPORT_MISSING}: no Server wire transport was bound for the model-provider settings; ` +
          'the product composition must inject one - refusing to render a section that cannot reach the Server')
      }
      const service = createModelProviderService(transport)
      const composition = workbench.composition
      // The contract makes absence explicit: consumers must reject it rather
      // than silently substituting legacy navigation (workbench.ts).
      if (composition === undefined) {
        throw new Error('ordessa.model-provider requires the Workbench composition capability; it is absent in this host')
      }
      composition.forScope(context.resources).addSettingsSection({
        id: SETTINGS_SECTION_ID,
        title: '模型与服务',
        component: () => <ModelProviderSettings service={service} />,
      })
      return service
    },
  }
}

export default createPlugin()
