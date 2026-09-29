// ordessa.chat — Chat domain plugin (v2 implementation line). Provides the
// ChatContributions service (chat-api), registers the Chat page, the global
// project dialog overlay through the Workbench's existing composition, a
// chat-owned composer.toolbar contribution (the connection badge), and the
// real-seam input sources: the brand's native command catalog (R-Z2-3) and
// the capability-driven attachment entry (R-Z2-2). The old
// ordessa.agent-conversation chain is retired (014 P-C PC-6); this plugin is
// the conversation surface now.
import { useSyncExternalStore } from 'react'
import type { PluginContext } from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { AgentSessionsToken, type AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'
import { ChatContributionsToken, createChatContributions, chatContribution, type ChatContributionsService, type ChatProjection } from '@extensions/ordessa.chat-api/contract.js'
import { ChatPage } from './views/chat-page'
import { ProjectDialog } from './views/project-dialog'
import { ConnectionBadge } from './views/connection-badge'
import { connectionBadgeKey } from './state/keys'
import { createAttachmentSource, createNativeCommandSource } from './adapters/agent'

export default function createPlugin() {
  return { id: 'ordessa.chat', autoStart: true,
    requires: [WorkbenchToken, AgentSessionsToken], provides: ChatContributionsToken,
    activate: (context: PluginContext, workbench: Workbench, sessions: AgentSessions): ChatContributionsService => {
      const chat = createChatContributions()
      const ui = workbench.forScope(context.resources)

      ui.addView({ id: 'chat.page', title: 'Chat', presentation: 'region', region: 'main',
        component: () => <ChatPage service={sessions} chat={chat} /> })

      // Global project dialog + product nav entry via the Workbench
      // composition (N06): Chat owns the content, the Workbench owns
      // dismissal — no second floating layer.
      const composition = workbench.composition?.forScope(context.resources)
      composition?.addModule({ id: 'ordessa.chat', title: 'Chat', order: 20, homeViewId: 'chat.page' })
      composition?.addOverlay({
        id: 'chat.project-dialog', title: '选择项目', presentation: 'dialog', order: 10,
        component: ({ close }) => <ChatProjectOverlay service={sessions} close={close} />,
      })

      // Chat's own toolbar widget: a real contribution exercising the scoped
      // path (registered under the plugin's scope; revoking the scope removes
      // only this entry).
      const badgeProjection: ChatProjection<{ readonly status: string }> = slotContext =>
        slotContext.slot === 'composer.toolbar'
          ? { hidden: false, props: { status: slotContext.connection.status } }
          : { hidden: true }
      chat.forScope(context.resources).addContribution(chatContribution({
        id: 'ordessa.chat.connection-badge', slot: 'composer.toolbar', order: 100, key: connectionBadgeKey,
        project: badgeProjection,
      }))

      // Real-seam input sources (014 P-C PC-2/PC-3): the brand's native
      // command catalog projects into the slash surface, and the attachment
      // entry activates only on the facade's real capability (no picker
      // channel is installed yet, so the entry carries its honest reason —
      // R-Z2-6/S-05).
      chat.forScope(context.resources).addInputSource(createNativeCommandSource(sessions))
      chat.forScope(context.resources).addInputSource(createAttachmentSource(sessions))
      return chat
    },
  }
}

function ChatProjectOverlay({ service, close }: { service: AgentSessions; close(): void }) {
  const state = useSyncExternalStore(service.subscribe, service.getSnapshot, service.getSnapshot)
  return <ProjectDialog service={service} snapshot={state} close={close}
    onProjectSelected={() => { close() }} />
}
