import type { PluginContext } from '@ordessa/extension-api'
import { CommandsToken, WorkbenchToken, type Commands, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { AgentConnectionsToken, AgentSessionsToken, type AgentConnections } from '@extensions/ordessa.agent-contracts/contract.js'
import { createAgentSessions } from './model'
import { SessionBrowser } from './view'

export default function createPlugin() {
  return { id: 'ordessa.agent-sessions', autoStart: true,
    requires: [AgentConnectionsToken, CommandsToken, WorkbenchToken], provides: AgentSessionsToken,
    activate: (context: PluginContext, connections: AgentConnections, commands: Commands, workbench: Workbench) => {
      const sessions = createAgentSessions(context.resources, connections)
      const ui = workbench.forScope(context.resources)
      ui.addView({ id: 'agent.sessions', title: 'Sessions', presentation: 'region', region: 'left', component: () => <SessionBrowser service={sessions} /> })
      commands.forScope(context.resources).add({ id: 'agent.open', title: 'Agents', execute: () => {
        // ordessa.agent-conversation retired (014 P-C PC-6): the Chat page
        // (ordessa.chat) is the conversation surface now; the old view id
        // belongs to a retired registration chain and is never opened.
        workbench.open('agent.sessions')
      } })
      ui.addUI({ id: 'agent.navigation', kind: 'command', slot: 'navigation', command: 'agent.open', label: 'Agents', icon: () => <span aria-hidden="true">◎</span> })
      return sessions
    } }
}
