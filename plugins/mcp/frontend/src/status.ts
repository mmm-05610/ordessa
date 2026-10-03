// McpStatusService: the six-tier fact grading the Chat panel consumes
// (docs/design/mcp/spec.md FR-02 — 保存/探测/启用/连接/工具发现/可调用 are six
// separate facts, never one `available` boolean). Every tier is derived only
// from evidence the wire client returned for THAT tier:
//
//   defined   ← the definition row exists (mcp.listDefinitions)
//   approved  ← latest revision approval or an approved effective snapshot
//   enabled   ← the resolve preview includes it enabled for this target
//   connected ← inspectConnection reported an evidenced connection
//   catalog   ← listTools returned an identity-matched toolNames catalog
//   callable  ← ONLY when the backend states it (tri-state; absence stays
//               `unknown`, it is never inferred from the previous tiers)
//
// The observation keeps pending / connected / catalog-changed / refused apart
// (contracts.md §2), and an absent or failing lower tier never colour-boosts a
// higher one. When no wire client was injected the whole service reports
// `absent` — the panel then renders "unavailable" and nothing else (no data
// is manufactured locally).

import type {
  McpCatalogFacts, McpConnectionFacts, McpConnectionObservation, McpDefinitionSummary, McpSessionTarget, McpRevisionView,
} from './dto'
import type { McpWireClient } from './wire'

export const MCP_FACT_LEVELS = ['defined', 'approved', 'enabled', 'connected', 'catalog', 'callable'] as const
export type McpFactLevel = (typeof MCP_FACT_LEVELS)[number]

/** Display copy per tier. Wording discipline: `connected` is the ONLY place a
 * connection may be claimed; a probe success renders as 探测成功 elsewhere. */
export const MCP_LEVEL_LABELS: Record<McpFactLevel, string> = {
  defined: '已定义',
  approved: '已批准',
  enabled: '已启用（本会话范围）',
  connected: '连接成功',
  catalog: '工具已发现',
  callable: '本次可调用',
}

export interface McpServerFacts {
  readonly definitionId: string
  readonly name: string
  readonly transport: 'stdio' | 'remote'
  /** Highest evidenced tier; `null` means nothing is proven beyond the row
   * existing. Gaps are kept: if `connected` lacks evidence but `enabled` has
   * it, the level stays `enabled` with a pending/unknown observation. */
  readonly reachedLevel: McpFactLevel | null
  /** Connection observation class for the session; `none` before any
   * connection was ever attempted. */
  readonly observation: McpConnectionObservation | 'none'
  readonly approvedRevision: number | null
  readonly toolsDiscovered: number | null
  /** Tri-state exactly as stated by the backend; null = 未确认. */
  readonly callableNow: boolean | null
  /** Human-readable refusal/uncertainty note from the service, display only. */
  readonly note?: string
}

export interface McpSessionFacts {
  /** `absent` = no status provider at all (wire client not injected).
   * `loading` = never refreshed; `error` = the last refresh failed. */
  readonly status: 'ready' | 'loading' | 'error' | 'absent'
  readonly error?: string
  readonly servers: readonly McpServerFacts[]
}

/** Shape-compatible with chat-api `ChatActionResult`, so the panel can hand
 * the result straight to the shared entry action without a translation. */
export type McpSelectResult =
  | { readonly status: 'accepted' }
  | { readonly status: 'refused'; readonly message: string }
  | { readonly status: 'unavailable'; readonly message?: string }

/** The abstract data source of the Chat MCP panel. The session-service owner
 * implements it over its own wire access; the panel only ever consumes this
 * interface. `select` is optional on purpose: an owner that cannot take a
 * per-session selection leaves it undefined and the UI disables the affordance
 * with a reason instead of faking one. */
export interface McpStatusService {
  /** Synchronous last-known snapshot; stable identity until `refresh` lands. */
  snapshot(target: McpSessionTarget): McpSessionFacts
  refresh(target: McpSessionTarget, signal?: AbortSignal): Promise<McpSessionFacts>
  select?(target: McpSessionTarget, definitionId: string, enabled: boolean): Promise<McpSelectResult>
}

const EMPTY: McpSessionFacts = { status: 'absent', servers: [] }

/** Wire-backed status service. `client === undefined` is the honest absence:
 * every snapshot says `absent` and every refresh keeps it that way.
 *
 * `options.select` is deliberately NOT derived from the wire client: the §1
 * operation table has no per-session selection method with a non-guessed
 * scope identity, so a default `select` would fabricate one. The session
 * service owner passes a real select implementation when it has one; without
 * it the panel disables the affordance with a reason (never a local toggle). */
export function createMcpStatusService(client?: McpWireClient, options?: {
  select?: (target: McpSessionTarget, definitionId: string, enabled: boolean) => Promise<McpSelectResult>
  /** Only the session owner can bind these runtime identities. Chat location
   * ids alone do not establish a backend sessionRef or generation. */
  context?: (target: McpSessionTarget) => { sessionRef: string; runtimeGeneration: number } | undefined
}): McpStatusService {
  if (!client) {
    return {
      snapshot: () => EMPTY,
      refresh: async () => EMPTY,
      // No select member: the panel must render the affordance disabled with
      // the「服务缺席」reason, never attempt a local toggle.
    }
  }
  const keyOf = (target: McpSessionTarget) =>
    `${target.kind}:${target.connectionId ?? ''}:${target.serverInstanceId ?? ''}:${target.sessionId ?? target.draftId ?? ''}`
  let cacheKey = ''
  let cache: McpSessionFacts = { status: 'loading', servers: [] }

  const refresh = async (target: McpSessionTarget, signal?: AbortSignal): Promise<McpSessionFacts> => {
    if (target.kind !== 'session' || !target.connectionId || !target.sessionId) {
      // Draft targets have no session facts to show; stay honestly empty.
      cache = { status: 'ready', servers: [] }
      cacheKey = keyOf(target)
      return cache
    }
    let definitions: readonly McpDefinitionSummary[]
    try {
      definitions = await client.listDefinitions(signal)
    } catch (error) {
      cache = { status: 'error', error: messageOf(error), servers: keyOf(target) === cacheKey ? cache.servers : [] }
      cacheKey = keyOf(target)
      return cache
    }
    const context = options?.context?.(target)
    const bound = context && context.sessionRef.trim() && Number.isInteger(context.runtimeGeneration) && context.runtimeGeneration >= 0 ? context : undefined
    let preview: Awaited<ReturnType<McpWireClient['resolvePreview']>> | undefined
    let contextNote = '会话运行上下文缺席：启用、连接和工具目录未确认'
    if (bound) {
      try {
        preview = await client.resolvePreview({ ...bound, targetSession: bound.sessionRef, signal })
        if (preview.snapshot.targetSession !== bound.sessionRef || preview.snapshot.runtimeGeneration !== bound.runtimeGeneration) {
          preview = undefined
          contextNote = '运行快照与会话或 generation 不匹配'
        }
      } catch (error) { contextNote = messageOf(error) }
    }
    const servers = await Promise.all(definitions.filter(row => !row.archived).map(async row => {
      let revision: McpRevisionView | undefined
      let note = preview ? undefined : contextNote
      try { revision = await client.getDefinition(row.definitionId, signal) } catch (error) { note = messageOf(error) }
      if (revision && (revision.definitionId !== row.definitionId || revision.revision !== row.latestRevision)) {
        revision = undefined
        note = '修订元数据与定义不匹配：审批未确认'
      }
      const previewEntry = preview?.snapshot.definitionRevisions.find(entry => entry.definitionId === row.definitionId && entry.revision !== null)
      let connection: McpConnectionFacts | undefined
      let catalog: McpCatalogFacts | undefined
      if (bound && previewEntry?.revision !== null && previewEntry?.revision !== undefined) {
        try {
          const listed = await client.listTools({ ...bound, definitionId: row.definitionId, revision: previewEntry.revision, signal })
          if (listed.catalog.leaseId !== listed.leaseId || listed.catalog.definitionId !== row.definitionId || listed.catalog.revision !== previewEntry.revision) {
            throw new Error('工具目录身份与请求不匹配')
          }
          const inspected = await client.inspectConnection({ ...bound, leaseId: listed.leaseId, signal })
          if (inspected.definitionId !== row.definitionId || inspected.revision !== previewEntry.revision || inspected.generation !== bound.runtimeGeneration) {
            throw new Error('连接身份或 generation 与请求不匹配')
          }
          connection = inspected
          if (inspected.observation === 'connected' || inspected.observation === 'catalog-changed') catalog = listed.catalog
        } catch (error) { note = messageOf(error) }
      }
      const approvedRevision = previewEntry?.revision ?? (revision?.approval ? revision.revision : null)
      if (approvedRevision === null) note = note ? `${note}；审批未确认（历史修订不可读）` : '审批未确认（历史修订不可读）'
      return grade(row, approvedRevision, previewEntry !== undefined, connection, catalog, note)
    }))
    cache = { status: 'ready', servers }
    cacheKey = keyOf(target)
    return cache
  }
  return {
    snapshot: target => (keyOf(target) === cacheKey ? cache : { status: 'loading', servers: [] }),
    refresh,
    ...(options?.select ? { select: options.select } : {}),
  }
}

function grade(
  row: McpDefinitionSummary,
  approvedRevision: number | null,
  enabled: boolean,
  connection: McpConnectionFacts | undefined,
  catalog: McpCatalogFacts | undefined,
  note: string | undefined,
): McpServerFacts {
  let reachedLevel: McpFactLevel | null = 'defined'
  if (approvedRevision !== null) reachedLevel = 'approved'
  if (enabled && approvedRevision !== null) reachedLevel = 'enabled'
  const observation: McpConnectionObservation | 'none' = connection?.observation ?? 'none'
  if (connection && (connection.observation === 'connected' || connection.observation === 'catalog-changed')) reachedLevel = 'connected'
  if (catalog && connection && (connection.observation === 'connected' || connection.observation === 'catalog-changed')) reachedLevel = 'catalog'
  // `callable` needs the backend to state it; the tri-state stays null until then.
  const callableNow = connection?.callableNow ?? null
  if (callableNow === true && catalog) reachedLevel = 'callable'
  return {
    definitionId: row.definitionId,
    name: row.nativeName,
    transport: row.transport,
    // Enabling is only evidenced on top of an approval; an enabled row whose
    // approval vanished (dangling reference) stops at `defined`.
    reachedLevel: approvedRevision === null ? 'defined' : reachedLevel,
    observation,
    approvedRevision,
    toolsDiscovered: catalog ? catalog.toolNames.length : null,
    callableNow,
    ...(note ? { note } : {}),
  }
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
