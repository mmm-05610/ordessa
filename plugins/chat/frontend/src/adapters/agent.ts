// Adapter: AgentSessions facade → chat display DTOs (service-adaptation.md
// §1 discipline). Every mapping below is a verified field of the current
// facade; nothing is inferred from tool names, titles or endpoint strings:
// - No event sequence exists → the display list is a snapshot projection with
//   the message-internal order reasoning → body → tools, never a timeline.
// - reasoning is a bare string → status inherits the message's run status
//   evidence; no fabricated durationMs.
// - Tool structured command display stays undefined (the facade carries no
//   verified command fields) → every tool renders generic; a name like `bash`
//   never fabricates command syntax (X06).
// - Attachment capability is absent in the current facade (send is text-only)
//   → the honest capability is `supported: false` with the reason; no
//   receive-then-drop path exists.
import type {
  AgentClient, AgentInteraction, AgentMessage, AgentSessions, AgentSnapshot, AgentToolCall, AgentWorkspaceSnapshot,
} from '@extensions/ordessa.agent-contracts/contract.js'
import type {
  ChatCommandCatalog, ChatContentStatus, ChatMessageBodyProps, ChatReasoningProps, ChatSessionGateway,
  ChatSubmissionResult, ChatSubmissionSnapshot, ChatToolActivityProps, ChatToolState,
} from '@extensions/ordessa.chat-api/contract.js'

export interface ConversationPart {
  readonly kind: 'reasoning' | 'body' | 'tool'
  readonly reasoning?: ChatReasoningProps
  readonly body?: ChatMessageBodyProps
  readonly tool?: ChatToolActivityProps
}

export interface ChatConversationDisplay {
  readonly conversationKey: string
  readonly parts: readonly ConversationPart[]
}

/** Display-only stable conversation key (connection + session scope). It is a
 * React/state key, never a backend id; business calls keep original ids. */
export function conversationKeyOf(connectionId: string | undefined, sessionId: string): string {
  return `${connectionId ?? '-'}:${sessionId}`
}

function contentStatusOf(status: AgentMessage['status']): ChatContentStatus {
  switch (status) {
    case 'starting':
    case 'running':
    case 'stop-requested': return 'streaming'
    case 'completed': return 'complete'
    case 'cancelled': return 'interrupted'
    default: return 'unknown'
  }
}

function toolStateOf(state: AgentToolCall['status']): ChatToolState {
  return state
}

const prettyJson = (value: unknown): string | undefined => {
  if (value === undefined) return undefined
  if (typeof value === 'string') return value
  try { return JSON.stringify(value, null, 2) } catch { return String(value) }
}

export function projectMessage(message: AgentMessage, conversationKey: string): ConversationPart[] {
  const parts: ConversationPart[] = []
  if (message.role === 'user') {
    parts.push({ kind: 'body', body: {
      conversationKey, messageId: message.id, role: 'user', body: message.text, status: 'complete',
    } })
    return parts
  }
  // reasoning is a plain string on the facade: it can only inherit the
  // message status as evidence — never its own streaming verdict.
  if (message.reasoning) {
    parts.push({ kind: 'reasoning', reasoning: {
      conversationKey, partId: `${message.id}:reasoning`, text: message.reasoning,
      status: contentStatusOf(message.status),
    } })
  }
  if (message.text) {
    parts.push({ kind: 'body', body: {
      conversationKey, messageId: message.id, role: 'assistant', body: message.text,
      status: contentStatusOf(message.status),
    } })
  }
  for (const tool of message.tools ?? []) {
    parts.push({ kind: 'tool', tool: {
      conversationKey, toolId: tool.id, title: tool.name, state: toolStateOf(tool.status),
      paramsText: prettyJson(tool.arguments), outputText: prettyJson(tool.result),
      // `command` stays undefined by design: the facade exposes no verified
      // structured command fields, so the generic renderer is the only
      // honest display (service-adaptation §2, X06).
    } })
  }
  return parts
}

export function projectConversation(snapshot: AgentSnapshot, sessionId: string): ChatConversationDisplay {
  const connectionId = snapshot.connection.id
  const conversationKey = conversationKeyOf(connectionId, sessionId)
  const messages = snapshot.messages[sessionId] ?? []
  return { conversationKey, parts: messages.flatMap(message => projectMessage(message, conversationKey)) }
}

export function interactionsForSession(snapshot: AgentSnapshot, sessionId: string): readonly AgentInteraction[] {
  return snapshot.interactions.filter(item => item.sessionId === sessionId)
}

export interface PaneRunState {
  readonly runId?: string
  readonly status: 'idle' | 'starting' | 'running' | 'stop-requested' | 'completed' | 'cancelled' | 'failed' | 'unknown'
  readonly stoppable: boolean
}

export function paneRunState(snapshot: AgentSnapshot, sessionId: string): PaneRunState {
  const run = Object.values(snapshot.runs).filter(item => item.sessionId === sessionId).at(-1)
  return { runId: run?.id, status: run?.status ?? 'idle', stoppable: run?.stoppable ?? true }
}

/**
 * The only submission shape Chat sends through. Honest mapping of today's
 * text-only facade (service-adaptation §3): a resolved `send` is `accepted`
 * in the send-path sense (during a draft the facade resolves only on the
 * confirmed first-send acceptance, FC-0031); a rejection is `refused` —
 * except when the connection evidence shows the link dropped while awaiting,
 * where the real outcome is unverifiable and `unknown` is returned. The UI
 * must keep the draft on anything but `accepted`.
 */
export function createFacadeGateway(service: AgentSessions): ChatSessionGateway {
  return {
    async submit(snapshot: ChatSubmissionSnapshot): Promise<ChatSubmissionResult> {
      try {
        await service.send(snapshot.text)
        return { status: 'accepted' }
      } catch (cause) {
        const state = service.getSnapshot()
        const connection = state.agent?.connection
        const linkDown = connection?.status === 'disconnected' || connection?.status === 'error'
        if (linkDown) return { status: 'unknown' }
        return { status: 'refused', reason: cause instanceof Error ? cause.message : String(cause) }
      }
    },
  }
}

/** Honest capability of the current facade: attachments are not sendable yet.
 * C0's attachment seam (api-requests R-Z2-2) replaces this projection. */
export const facadeAttachmentCapability = {
  supported: false,
  reason: '当前会话服务未提供附件发送能力（等待传输接缝），入口保持禁用。',
} as const

/** Command catalog projection: the current facade has no native command
 * directory, so `absent` is the truthful state — local plugin menu sources
 * keep working, no fake native commands are shown (R-Z2-3). */
export const facadeCommandCatalog: ChatCommandCatalog = {
  get: () => ({ status: 'absent' }),
}

export function snapshotOf(service: AgentSessions): AgentWorkspaceSnapshot {
  return service.getSnapshot()
}

export function selectedClientOf(service: AgentSessions): AgentClient | undefined {
  void service
  return undefined // the facade deliberately does not expose raw clients to UI
}
