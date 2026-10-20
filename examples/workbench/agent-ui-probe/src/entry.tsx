import type { PluginContext } from '@ordessa/extension-api'
import { CommandsToken, WorkbenchToken, type Commands, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { createFixture } from './store'
import { ConversationProbe } from './view'
export default function createPlugin() {
  return { id: 'example.agent-ui', autoStart: true, requires: [CommandsToken, WorkbenchToken],
    activate(context: PluginContext, commands: Commands, workbench: Workbench) {
      const fixture = createFixture()
      context.resources.add(fixture)
      const View = () => <ConversationProbe fixture={fixture} />
      workbench.forScope(context.resources).addView({ id: 'probe.conversation', title: 'Agent UI 验证', presentation: 'region', region: 'main', component: View })
      commands.forScope(context.resources).add({ id: 'probe.open', title: 'Agent 验证', execute: () => workbench.open('probe.conversation') })
      workbench.forScope(context.resources).addUI({ id: 'probe.nav', kind: 'command', slot: 'navigation', command: 'probe.open' })
      workbench.open('probe.conversation')
    },
  }
}
