// Chat 输入区按需小面板 (ux.md「Chat 输入区与状态」, contracts.md §2):
// a ChatInputSource over the chat-api r3 shared plus-panel plus a
// composer.toolbar chatContribution carrying the six-tier facts chip.
//
// Everything rendered here comes from the abstract McpStatusService; when the
// service is absent (no wire client from the session-service owner) the panel
// shows one `unavailable` entry and the chip says 状态服务不可用 — no tier is
// ever faked, and pending/unknown are kept apart from connected
// (「Pending 和 Unknown 不是 Connected」).

import type {
  ChatComponentKey, ChatContributionContext, ChatContributionRegistration, ChatInputEntry, ChatInputQuery, ChatInputSource, ChatProjection,
} from '@extensions/ordessa.chat-api/contract.js'
import { chatContribution, defineChatComponentKey } from '@extensions/ordessa.chat-api/contract.js'
import type { McpSessionFacts, McpServerFacts, McpStatusService } from './status'
import { MCP_LEVEL_LABELS } from './status'

export const MCP_CHAT_SOURCE_ID = 'ordessa.asset.mcp.chat-status'
const SERVERS_GROUP = { id: 'mcp.servers', title: '本会话 MCP 服务器', order: 10 }

/** Per-row copy for one server fact row. Six tiers plus the observation
 * class; refusal/pending never collapse into a connection claim. */
export function serverFactLine(fact: McpServerFacts): string {
  const level = fact.reachedLevel === null ? '无已证实等级' : MCP_LEVEL_LABELS[fact.reachedLevel]
  const parts = [level]
  switch (fact.observation) {
    case 'pending': parts.push('连接确认中（pending，非已连接）'); break
    case 'connected': parts.push('连接成功'); break
    case 'catalog-changed': parts.push('目录已变化（本轮仍用旧目录，变更只影响下轮）'); break
    case 'refused': parts.push('连接被拒绝'); break
    case 'unknown': parts.push('连接状态未知'); break
    case 'none': break
  }
  if (fact.toolsDiscovered !== null) parts.push(`工具已发现 ${fact.toolsDiscovered} 个`)
  if (fact.callableNow === true) parts.push('本次可调用')
  else if (fact.callableNow === false) parts.push('本次不可调用')
  else parts.push('可调用性未确认')
  if (fact.approvedRevision !== null) parts.push(`批准修订 r${fact.approvedRevision}`)
  if (fact.note) parts.push(fact.note)
  return parts.join(' · ')
}

const UNAVAILABLE_ENTRY: ChatInputEntry = {
  id: 'mcp.unavailable',
  title: 'MCP 状态服务不可用',
  description: '未接入 MCP 状态来源（wire client 由会话服务 owner 提供）；面板不显示猜测数据。',
  groupId: SERVERS_GROUP.id,
  order: 0,
  surfaces: ['plus'],
  availability: { kind: 'disabled', reason: 'mcp-status-service-absent' },
  action: { kind: 'insert-command', text: '' },
}

const EMPTY_ENTRY: ChatInputEntry = {
  id: 'mcp.none-defined',
  title: '本会话尚无 MCP 定义',
  groupId: SERVERS_GROUP.id,
  order: 0,
  surfaces: ['plus'],
  availability: { kind: 'disabled', reason: 'no-definitions' },
  action: { kind: 'insert-command', text: '' },
}

/** The on-demand source registered with ChatContributionsService.addInputSource.
 * `status` may be undefined — the source then answers with the unavailable
 * row instead of inventing a snapshot. */
export function createMcpChatInputSource(status?: McpStatusService): ChatInputSource {
  return {
    id: MCP_CHAT_SOURCE_ID,
    title: 'MCP',
    groups: [SERVERS_GROUP],
    query: async (request: ChatInputQuery): Promise<readonly ChatInputEntry[]> => {
      if (!status) return [UNAVAILABLE_ENTRY]
      const facts = await status.refresh({
        kind: request.location.kind,
        ...(request.location.connectionId !== undefined ? { connectionId: request.location.connectionId } : {}),
        ...(request.location.serverInstanceId !== undefined ? { serverInstanceId: request.location.serverInstanceId } : {}),
        ...(request.location.kind === 'session' ? { sessionId: request.location.sessionId } : { draftId: request.location.draftId }),
      }, request.signal)
      if (facts.status === 'absent') return [UNAVAILABLE_ENTRY]
      if (facts.servers.length === 0) return [EMPTY_ENTRY]
      return facts.servers.map((server, index) => ({
        id: `mcp.server.${server.definitionId}`,
        title: `${server.name} · ${serverFactLine(server).split(' · ')[0]}`,
        description: serverFactLine(server),
        groupId: SERVERS_GROUP.id,
        order: index + 1,
        surfaces: ['plus'] as const satisfies readonly ('plus' | 'slash')[],
        // Selection needs the owning service's `select`; without it the row is
        // a read-only fact row, disabled with the reason (never a local toggle).
        availability: status.select
          ? { kind: 'ready' as const }
          : { kind: 'disabled' as const, reason: '会话选择由会话服务 owner 提供，当前缺席' },
        action: {
          kind: 'invoke' as const,
          execute: async location => status.select
            ? await status.select({ kind: location.kind, connectionId: location.connectionId, serverInstanceId: location.serverInstanceId,
                ...(location.kind === 'session' ? { sessionId: location.sessionId } : { draftId: location.draftId }) },
              server.definitionId, nextEnabled(server))
            : { status: 'unavailable' as const },
        },
      }))
    },
  }
}

/** Toggle direction derived from the evidenced tier: a row that ever reached
 * the `enabled` tier (or beyond) is switched off, everything else on. */
function nextEnabled(server: McpServerFacts): boolean {
  const enabledTiers = ['enabled', 'connected', 'catalog', 'callable'] as const
  return !(server.reachedLevel && (enabledTiers as readonly (string | null)[]).includes(server.reachedLevel))
}

// ---------------------------------------------------------------------------
// composer.toolbar status chip (chatContribution path)
// ---------------------------------------------------------------------------

export interface McpStatusChipProps {
  readonly facts: McpSessionFacts
}

/** The chip's component key. NOTE (registered in the report): the chat
 * frontend's default resolver table is chat-internal, so an external key only
 * renders once integration adds this id to the table — until then the slot
 * honestly stays empty (chat-page.tsx `if (!Component) return null`). */
export const mcpStatusChipKey: ChatComponentKey<McpStatusChipProps> =
  defineChatComponentKey<McpStatusChipProps>('ordessa.asset.mcp.status-chip', 1)

export function mcpStatusChipContribution(status?: McpStatusService): ChatContributionRegistration {
  const project: ChatProjection<McpStatusChipProps> = (context: ChatContributionContext) =>
    context.slot === 'composer.toolbar'
      ? { hidden: false, props: { facts: status ? status.snapshot(context.location) : { status: 'absent' as const, servers: [] } } }
      : { hidden: true }
  return chatContribution({ id: 'ordessa.asset.mcp.status-chip', slot: 'composer.toolbar', order: 110, key: mcpStatusChipKey, project })
}

/** Compact one-line summary; absence and pending never read as connected. */
export function summarizeMcpFacts(facts: McpSessionFacts): string {
  if (facts.status === 'absent') return 'MCP：状态服务不可用'
  if (facts.servers.length === 0) return 'MCP：本会话暂无定义'
  const connected = facts.servers.filter(server => server.observation === 'connected').length
  const catalog = facts.servers.filter(server => server.reachedLevel === 'catalog' || server.reachedLevel === 'callable').length
  const callable = facts.servers.filter(server => server.callableNow === true).length
  return `MCP：已定义 ${facts.servers.length} · 连接 ${connected} · 工具目录 ${catalog} · 可调用 ${callable}`
}

export function McpStatusChip({ facts }: McpStatusChipProps) {
  return <span className="mcp-status-chip" data-testid="mcp-status-chip" data-state={facts.status}>{summarizeMcpFacts(facts)}</span>
}
