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
import { WorkbenchToken, UiComponentsToken, WirePortToken, type Workbench, type UiComponents, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import { AgentSessionsToken, createWireConfigurationClient, createFrontendSubmissionJournal, createDurableSubmissionClient, createSubmissionRecoveryClient, type AgentSessions } from '@extensions/ordessa.agent-contracts/contract.js'
import { ChatContributionsToken, createChatContributions, chatContribution, type ChatContributionsService, type ChatProjection } from '@extensions/ordessa.chat-api/contract.js'
import { ChatPage } from './views/chat-page'
import { ProjectDialog } from './views/project-dialog'
import { ConnectionBadge } from './views/connection-badge'
import { connectionBadgeKey } from './state/keys'
import { createAttachmentSource, createNativeCommandSource } from './adapters/agent'
import { createReliableChatSubmission } from './adapters/reliable-agent'
import { SubmissionRecoveryPanel, type SubmissionRecovery } from './components/submission-recovery'

export default function createPlugin() {
  return { id: 'ordessa.chat', autoStart: true,
    requires: [WorkbenchToken, AgentSessionsToken, WirePortToken, UiComponentsToken], provides: ChatContributionsToken,
    activate: (context: PluginContext, workbench: Workbench, sessions: AgentSessions, wire: WirePort, components: UiComponents): ChatContributionsService => {
      const chat = createChatContributions()
      const ui = workbench.forScope(context.resources)
      const uiComponents = components.forScope(context.resources)
      const configuration = createWireConfigurationClient({ wire, sessions, scope: context.resources })
      let journal: ReturnType<typeof createFrontendSubmissionJournal> | undefined
      let submissions: ReturnType<typeof createDurableSubmissionClient> | undefined
      let disposed = false
      function getJournal() {
        if (disposed) throw new Error('Chat submission scope is disposed')
        return journal ??= createFrontendSubmissionJournal()
      }
      context.resources.add({ get isDisposed() { return disposed }, dispose() {
        if (disposed) return
        disposed = true
        void journal?.dispose()
      } })
      const reliableSubmission = createReliableChatSubmission(configuration, {
        async submit(capture) {
          if (disposed) return { status: 'refused', reason: 'Chat submission scope is disposed' }
          // A readable Chat may exist without durable browser storage. Only the
          // reliable operation is refused; no volatile or raw fallback is used.
          try {
            submissions ??= createDurableSubmissionClient({ wire: wire.call.bind(wire), journal: getJournal() })
          } catch (cause) {
            return { status: 'refused', reason: cause instanceof Error ? cause.message : String(cause) }
          }
          const result = await submissions.submit(capture)
          if (result.status === 'unavailable') return { status: 'refused', reason: result.reason }
          return result.status === 'accepted' ? { status: 'accepted' }
            : result.status === 'refused' ? { status: 'refused', reason: result.reason }
            : { status: 'unknown', reason: result.queryHint }
        },
      })
      const recovery: SubmissionRecovery = {
        async list() {
          try { return await createSubmissionRecoveryClient({ wire: wire.call.bind(wire), journal: getJournal() }).list() }
          catch (cause) { return { status: 'unavailable', reason: String(cause) } }
        },
        async reconcile(key) {
          try { return await createSubmissionRecoveryClient({ wire: wire.call.bind(wire), journal: getJournal() }).reconcile(key) }
          catch (cause) { return { status: 'unavailable', reason: String(cause) } }
        },
      }
      ui.addView({ id: 'chat.submission-recovery', title: '提交恢复', presentation: 'region', region: 'right',
        component: () => <SubmissionRecoveryPanel recovery={recovery} /> })

      ui.addView({ id: 'chat.page', title: 'Chat', presentation: 'region', region: 'main',
        component: () => <ChatPage service={sessions} chat={chat} uiComponents={uiComponents} reliableSubmission={reliableSubmission} /> })

      // Global project dialog + product nav entry via the Workbench
      // composition (N06): Chat owns the content, the Workbench owns
      // dismissal — no second floating layer.
      const composition = workbench.composition?.forScope(context.resources)
      composition?.addModule({ id: 'ordessa.chat', title: 'Chat', order: 20, homeViewId: 'chat.page' })
      composition?.addModule({ id: 'ordessa.chat.recovery', title: '提交恢复', order: 21,
        homeViewId: 'chat.submission-recovery' })
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
      // The Chat plugin owns its landing view; registering a view alone does
      // not activate it. No connection or native session is created here.
      workbench.open('chat.page')
      return chat
    },
  }
}

function ChatProjectOverlay({ service, close }: { service: AgentSessions; close(): void }) {
  const state = useSyncExternalStore(service.subscribe, service.getSnapshot, service.getSnapshot)
  return <ProjectDialog service={service} snapshot={state} close={close}
    onProjectSelected={() => { close() }} />
}
