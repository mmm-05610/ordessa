import type { PluginContext } from '@ordessa/extension-api'
import { WorkbenchToken, WirePortToken, type Workbench, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { ProfileServiceToken } from '@extensions/ordessa.profile-api/contract.js'
import { createWireClient } from './wire-client'
import { ConnectedProfileManager } from './connected-manager'

export default function createPlugin() {
  return {
    id: 'ordessa.profile-frontend', autoStart: true,
    requires: [WorkbenchToken, WirePortToken], provides: ProfileServiceToken,
    activate(context: PluginContext, workbench: Workbench, wire: WirePort) {
      const client = createWireClient(wire)
      const composition = workbench.composition?.forScope(context.resources)
      if (!composition) throw new Error('Profile requires Workbench composition')
      composition.addSettingsSection({ id: 'profile.management', title: 'Profile',
        component: () => <ConnectedProfileManager client={client} wire={wire} /> })
      return client
    },
  }
}
