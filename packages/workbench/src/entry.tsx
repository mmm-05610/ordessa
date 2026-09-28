import type { PluginContext } from '@ordessa/extension-api'
import { CommandsToken, WorkbenchToken, type Commands } from '@extensions/ordessa.contracts/contract.js'
import { createWorkbench } from './model'
import { WorkbenchShell } from './shell'
export default function createPlugin() {
  return { id: 'ordessa.workbench', autoStart: true, provides: WorkbenchToken, requires: [CommandsToken],
    activate(context: PluginContext, commands: Commands) {
      const model = createWorkbench(context.resources)
      context.root.mount({ id: 'ordessa.workbench.root', component: () => <WorkbenchShell model={model} commands={commands} /> })
      return model.service
    },
  }
}
