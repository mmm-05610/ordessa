// Adapter: AgentSessions facade → chat display DTOs (service-adaptation.md
// §1 discipline). Every mapping below is a verified field of the current
// facade; nothing is inferred from tool names, titles or endpoint strings:
// - No event sequence exists → the display list is a snapshot projection with
//   the message-internal order reasoning → body → tools, never a timeline.
// - reasoning evidence: `reasoningState` (contracts 0.2.0, R-Z2-5) when the
//   connector reports one; otherwise the bare string inherits the message's
//   run status and no durationMs is fabricated.
// - Tool structured command display stays undefined (the facade carries no
//   verified command fields) → every tool renders generic; a name like `bash`
//   never fabricates command syntax (X06).
// - Submission (R-Z2-1, contracts 0.2.0): the facade answers the decidable
//   three-state outcome itself — a void-resolving legacy connector is mapped
//   to `accepted` inside the facade; this adapter maps 1:1 and adds nothing.
// - Command catalog (R-Z2-3) and attachments (R-Z2-2) are real facade
//   projections: absence and errors are states with reasons, never fake menus
//   or receive-then-drop items.
import type {
  AgentCommandCatalog, AgentSessions,
  AgentInteraction, AgentMessage, AgentSnapshot, AgentToolCall, AgentWorkspaceSnapshot,
} from '@extensions/ordessa.agent-contracts/contract.js'
import type {
  ChatCommandCatalog, ChatContentReference, ChatContentStatus, ChatInputEntry, ChatInputSource, ChatLocation,
  ChatMessageBodyProps, ChatReasoningProps, ChatSessionGateway, ChatSubmissionResult, ChatSubmissionSnapshot,
  ChatToolActivityProps, ChatToolState,
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
  // Reasoning evidence: the connector's own reasoningState when present
  // (R-Z2-5); a bare string can only inherit the message status — never its
  // own streaming verdict, and never a fabricated duration.
  if (message.reasoning) {
    parts.push({ kind: 'reasoning', reasoning: {
      conversationKey, partId: `${message.id}:reasoning`, text: message.reasoning,
      status: message.reasoningState?.status ?? contentStatusOf(message.status),
      ...(message.reasoningState?.durationMs !== undefined ? { durationMs: message.reasoningState.durationMs } : {}),
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
 * The only submission shape Chat sends through. Revision 0.2.0 migration
 * (R-Z2-1): the FACADE owns the three-state mapping (typed refusal,
 * evidenced link-down → unknown, legacy void resolve → send-path acceptance);
 * this adapter maps the outcome 1:1 and invents no state. `accepted` means
 * the send path took the submission — never execution success. The UI must
 * keep the draft on anything but `accepted`.
 */
export function createFacadeGateway(service: AgentSessions): ChatSessionGateway {
  return {
    async submit(snapshot: ChatSubmissionSnapshot): Promise<ChatSubmissionResult> {
      const refs = snapshot.attachmentRefs ?? []
      let outcome
      try {
        outcome = await service.send(snapshot.text, refs.length ? refs : undefined)
      } catch (cause) {
        // Precondition failures (no session selected, closed gate) are not
        // submission outcomes; they surface as refusals with their reason.
        return { status: 'refused', reason: cause instanceof Error ? cause.message : String(cause) }
      }
      switch (outcome.kind) {
        case 'accepted': return { status: 'accepted' }
        case 'refused': return { status: 'refused', reason: outcome.code ? `${outcome.code}: ${outcome.reason}` : outcome.reason }
        case 'unknown': return { status: 'unknown' }
      }
    },
  }
}

/** Facade attachment capability for one location (PC-3). The facade member
 * always answers; a missing production prepare owner, a partial client
 * surface or a draft without a native session are all honest `absent`s with
 * their reason — the entry renders exactly that, never a fake activation. */
export function attachmentCapabilityOf(service: AgentSessions, location: ChatLocation) {
  const sessionId = location.kind === 'session' ? location.sessionId : undefined
  const cap = service.attachments.capability(sessionId)
  if (cap.kind === 'available') return { supported: true } as const
  return { supported: false, reason: cap.reason } as const
}

const commandReasonCopy: Record<string, string> = {
  malformed: '原生命令目录帧不可解析。',
  'stale-session': '命令目录属于已切换的会话。',
  'channel-down': '连接已断开，命令目录不可用。',
  unobservable: '连接断连结果不可观测，命令目录状态未知。',
}

/** Command catalog projection (R-Z2-3, PC-2): the facade's four-state catalog
 * mapped 1:1. `absent` is the truthful state for connections that project no
 * native directory — local plugin menu sources keep working, no fake native
 * commands are shown. `loading` is mapped when a connector declares it; no
 * current connector does (registered in the 014 P-C report). */
export function facadeCommandCatalog(service: AgentSessions): ChatCommandCatalog {
  return {
    get: (target): ReturnType<ChatCommandCatalog['get']> => {
      if (target.kind !== 'session') return { status: 'absent' }
      let catalog: AgentCommandCatalog
      try { catalog = service.commandCatalog(target.sessionId) } catch { return { status: 'absent' } }
      switch (catalog.kind) {
        case 'available': return { status: 'ready', commands: catalog.commands.map(command => ({
          id: command.name, title: command.name, insertText: `/${command.name}`,
          ...(command.description ? { description: command.description } : {}),
        })) }
        case 'loading': return { status: 'loading' }
        case 'error': return { status: 'error', message: commandReasonCopy[catalog.reason] ?? catalog.reason }
        case 'absent': return { status: 'absent' }
      }
    },
  }
}

/** The slash-surface input source backed by the real catalog (US3-1): ready
 * commands become insert-command entries; an absent catalog shows one
 * disabled "no commands" entry WITH its reason; a catalog error surfaces as
 * this source's own error state (retry-able, other sources unaffected). */
export function createNativeCommandSource(service: AgentSessions): ChatInputSource {
  const catalog = facadeCommandCatalog(service)
  return {
    id: 'ordessa.chat.native-commands',
    title: '原生命令',
    groups: [{ id: 'native', title: '原生命令', order: 10 }],
    async query(request) {
      if (request.surface !== 'slash') return []
      const state = catalog.get(request.location)
      if (state.status === 'ready') {
        return state.commands.map((command, index): ChatInputEntry => ({
          id: `native:${command.id}`, title: command.title,
          ...(command.description !== undefined ? { description: command.description } : {}),
          groupId: 'native', order: index, surfaces: ['slash'],
          availability: { kind: 'ready' },
          action: { kind: 'insert-command', text: command.insertText },
        }))
      }
      if (state.status === 'error') throw new Error(state.message)
      if (state.status === 'absent') {
        return [{
          id: 'native:none', title: '原生命令', groupId: 'native', order: 0, surfaces: ['slash'],
          availability: { kind: 'disabled', reason: '当前会话没有品牌原生命令目录（该品牌未播发）。' },
          action: { kind: 'insert-command', text: '' },
        }]
      }
      return [] // loading: the shared panel's per-source state carries it while the query is in flight
    },
  }
}

/** The plus-surface attachment entry (PC-3). Without a picker channel
 * (R-Z2-6) the entry stays disabled with that reason even when the transport
 * capability is real; with both present it prepares content through the
 * facade's attachment seam and returns the service-owned reference. */
export function createAttachmentSource(service: AgentSessions, picker?: {
  pick(): Promise<{ sourceId: string; name: string; mimeType?: string } | undefined>
}): ChatInputSource {
  const PICKER_REASON = '文件选择通道未接通（R-Z2-6），附件入口保持禁用。'
  const entry = async (location: ChatLocation): Promise<ChatInputEntry> => {
    const capability = attachmentCapabilityOf(service, location)
    const disabledReason = !picker ? PICKER_REASON : !capability.supported ? capability.reason : undefined
    return {
      id: 'attachments:add', title: '添加附件', groupId: 'attachments', order: 0, surfaces: ['plus'],
      ...(disabledReason !== undefined
        ? { availability: { kind: 'disabled' as const, reason: disabledReason } }
        : { availability: { kind: 'ready' as const } }),
      action: {
        kind: 'add-content',
        prepare: async (target, idempotencyKey) => {
          if (!picker || !capability.supported) return { status: 'unavailable' }
          const picked = await picker.pick()
          if (!picked) return { status: 'refused', message: '未选择任何文件。' }
          const sessionId = target.kind === 'session' ? target.sessionId : undefined
          const preparation = await service.attachments.prepare({ sessionId, sourceId: picked.sourceId, idempotencyKey })
          switch (preparation.kind) {
            case 'prepared': return { status: 'accepted', reference: preparation.reference.preparedId as ChatContentReference }
            case 'refused': return { status: 'refused', message: preparation.reason }
            case 'unknown': return { status: 'unknown' }
          }
        },
      },
    }
  }
  return {
    id: 'ordessa.chat.attachments',
    title: '附件',
    groups: [{ id: 'attachments', title: '附件', order: 20 }],
    async query(request) {
      if (request.surface !== 'plus') return []
      return [await entry(request.location)]
    },
  }
}

export function snapshotOf(service: AgentSessions): AgentWorkspaceSnapshot {
  return service.getSnapshot()
}
