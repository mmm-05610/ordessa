import type { AgentSessionInfo, AgentSnapshot } from '@extensions/ordessa.agent-contracts/contract.js'
import { hasAwaitingInteraction, hasOpenRun } from '@extensions/ordessa.agent-contracts/contract.js'

export const STANDALONE_GROUP = 'standalone'

export interface SessionGroup {
  readonly key: string
  readonly title: string
  readonly standalone: boolean
  readonly sessions: readonly AgentSessionInfo[]
}

/** Project a workspace path id down to its last segment for a compact group title. */
export function workspaceLabel(workspaceId: string): string {
  const trimmed = workspaceId.replace(/\/+$/, '')
  const tail = trimmed.slice(trimmed.lastIndexOf('/') + 1)
  return tail || workspaceId
}

/** Two-level projection over the flat sessions list: project groups in first-appearance
 * order, the standalone group (no workspaceId) last; pinned sessions lead inside a group.
 * Pure derivation from the existing surface — no new aggregation API (S-0005 facade rule). */
export function projectSessionGroups(sessions: readonly AgentSessionInfo[]): readonly SessionGroup[] {
  const order: string[] = []
  const grouped = new Map<string, AgentSessionInfo[]>()
  for (const session of sessions) {
    const key = session.workspaceId?.replace(/\/+$/, '') || STANDALONE_GROUP
    const bucket = grouped.get(key)
    if (bucket) bucket.push(session)
    else { grouped.set(key, [session]); order.push(key) }
  }
  const keys = [...order.filter(key => key !== STANDALONE_GROUP), ...(grouped.has(STANDALONE_GROUP) ? [STANDALONE_GROUP] : [])]
  return keys.map(key => ({
    key,
    standalone: key === STANDALONE_GROUP,
    title: key === STANDALONE_GROUP ? 'Standalone sessions' : workspaceLabel(key),
    sessions: [...(grouped.get(key) ?? []).sort((a, b) => Number(Boolean(b.pinned)) - Number(Boolean(a.pinned)))],
  }))
}

export interface SessionActivity { openRun: boolean; awaiting: boolean }

/** Per-session badge state, scanning every run and interaction of that session (not only the
 * last run) through the shared gate predicates (FC-0015/C-0033): kind is not consulted and
 * no terminal-state wording is inferred. */
export function sessionActivity(agent: AgentSnapshot, sessionId: string): SessionActivity {
  const scoped: AgentSnapshot[] = [{
    ...agent,
    runs: Object.fromEntries(Object.entries(agent.runs).filter(([, run]) => run.sessionId === sessionId)),
    interactions: agent.interactions.filter(interaction => interaction.sessionId === sessionId),
  }]
  return { openRun: hasOpenRun(scoped), awaiting: hasAwaitingInteraction(scoped) }
}
