// McpStatusService: the six-tier fact grading the Chat panel consumes
// (docs/design/mcp/spec.md FR-02 — 保存/探测/启用/连接/工具发现/可调用 are six
// separate facts, never one `available` boolean). Every tier is derived only
// from evidence the wire client returned for THAT tier:
//
//   defined   ← the definition row exists (mcp.listDefinitions)
//   approved  ← the row carries an approved revision
//   enabled   ← the resolve preview includes it enabled for this target
//   connected ← inspectConnection reported an evidenced connection
//   catalog   ← listTools returned a discovered tool set
//   callable  ← ONLY when the backend states it (tri-state; absence stays
//               `unknown`, it is never inferred from the previous tiers)
//
// The observation keeps pending / connected / catalog-changed / refused apart
// (contracts.md §2), and an absent or failing lower tier never colour-boosts a
// higher one. When no wire client was injected the whole service reports
// `absent` — the panel then renders "unavailable" and nothing else (no data
// is manufactured locally).

import type {
  McpCatalogFacts, McpConnectionFacts, McpConnectionObservation, McpDefinitionSummary, McpSessionTarget,
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
  const notes = new Map<string, string>()

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
      cache = { status: 'error', error: messageOf(error), servers: cache.servers }
      cacheKey = keyOf(target)
      return cache
    }
    let preview: McpPreviewShape | undefined
    try { preview = (await client.resolvePreview({ target, signal })).entries } catch { preview = undefined }
    const servers: McpServerFacts[] = []
    for (const row of definitions) {
      if (row.archived) continue
      const previewEntry = preview?.find(entry => entry.definitionId === row.definitionId && entry.enabled)
      let connection: McpConnectionFacts | undefined
      let catalog: McpCatalogFacts | undefined
      notes.delete(row.definitionId)
      if (previewEntry) {
        try { connection = await client.inspectConnection({ target, definitionId: row.definitionId, signal }) }
        catch (error) { notes.set(row.definitionId, messageOf(error)) }
        if (connection && (connection.observation === 'connected' || connection.observation === 'catalog-changed')) {
          try { catalog = await client.listTools({ target, definitionId: row.definitionId, generation: connection.generation, signal }) }
          catch (error) { notes.set(row.definitionId, messageOf(error)) }
        }
      }
      servers.push(grade(row, previewEntry !== undefined, connection, catalog, notes.get(row.definitionId)))
    }
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

type McpPreviewShape = readonly { definitionId: string; revision: number; enabled: boolean }[]

function grade(
  row: McpDefinitionSummary,
  enabled: boolean,
  connection: McpConnectionFacts | undefined,
  catalog: McpCatalogFacts | undefined,
  note: string | undefined,
): McpServerFacts {
  let reachedLevel: McpFactLevel | null = 'defined'
  if (row.approvedRevision !== null) reachedLevel = 'approved'
  if (enabled && row.approvedRevision !== null) reachedLevel = 'enabled'
  const observation: McpConnectionObservation | 'none' = connection?.observation ?? 'none'
  if (connection && (connection.observation === 'connected' || connection.observation === 'catalog-changed')) reachedLevel = 'connected'
  if (catalog && connection && (connection.observation === 'connected' || connection.observation === 'catalog-changed')) reachedLevel = 'catalog'
  // `callable` needs the backend to state it; the tri-state stays null until then.
  const callableNow = connection?.callableNow ?? null
  if (callableNow === true && catalog) reachedLevel = 'callable'
  return {
    definitionId: row.definitionId,
    name: row.name,
    transport: row.transport,
    // Enabling is only evidenced on top of an approval; an enabled row whose
    // approval vanished (dangling reference) stops at `defined`.
    reachedLevel: row.approvedRevision === null ? 'defined' : reachedLevel,
    observation: catalog?.catalogChanged === true ? 'catalog-changed' : observation,
    approvedRevision: row.approvedRevision,
    toolsDiscovered: catalog ? catalog.tools.length : null,
    callableNow,
    ...(note ? { note } : {}),
  }
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
