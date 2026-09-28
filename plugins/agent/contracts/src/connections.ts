import { Token, type ResourceScope, type IDisposable } from '@ordessa/extension-api'
// `createConnectionKind` comes from the contracts FOUNDATION carrier on purpose: a relative path
// into @ordessa/connections would compile a second copy of the platform API module into this
// bundle, and the product would then hold two `ConnectionKind`/`ConnectionsToken` instances — the
// CN-08 counterexample the product token guard rejects. The carrier is the single shared runtime
// copy, the same mechanism `ordessa.workbench.v1` and `ordessa.connections.v1` ride.
import { createConnectionKind } from '@extensions/ordessa.contracts/contract.js'
import type { AgentClient, AgentConnector, AgentReleaseState, AgentSnapshot, AgentWorkspaceSnapshot } from './agent'

/** The Agent domain's connection kind, created ONCE here and compared by identity at open time.
 * Concrete protocol kinds belong to their owning domain (contract C6 §3): the platform ships none,
 * and every `AgentClient` handed out by the Agent facade is opened under this kind. */
export const AgentClientConnectionKind = createConnectionKind<AgentClient>('ordessa.agent-client')

export interface AgentConnections {
  getSnapshot(): readonly Pick<AgentConnector, 'id' | 'title'>[]
  subscribe(listener: () => void): () => void
  forScope(scope: ResourceScope): { add(connector: AgentConnector): IDisposable }
  connect(id: string): Promise<AgentClient>
  /** Connection workspace: client holding, selection, and reconnection (P2-1 extraction). */
  readonly workspace: AgentConnectionWorkspace
}
export const AgentConnectionsToken = new Token<AgentConnections>('ordessa.agent.connections.v1')

/** Owns connected client instances, selection, and reconnection independent of mounted views.
 * The instance is owned by the connections service; consumers share the same one. */
export interface AgentConnectionWorkspace {
  getSnapshot(): AgentWorkspaceSnapshot
  subscribe(listener: () => void): () => void
  selectConnection(id: string): Promise<void>
  reconnect(id: string): Promise<void>
  /** The connected client of the current selection; throws while nothing is connected. */
  selected(): AgentClient
  /** Live snapshot of every connected client — the input of the gate predicates. */
  clientSnapshots(): readonly AgentSnapshot[]
  /** Live read (never a cache) of the backend releases left behind by evicted clients that are
   * still outstanding — in-flight or failed — with their explicit states: the workspace takes
   * over the client's live view when it retains the reference (seeded synchronously, then kept
   * current by the client's release-state notifications, each of which re-publishes the
   * snapshot), and only the backend's own confirmation removes an entry.
   * Optional: workspaces whose connectors own no managed channels report nothing to confirm. */
  releaseCleanup?(): AgentReleaseState[]
  /** The host's explicit pass over the retained evicted clients (each one's `retryReleases()`,
   * which JOINS in-flight attempts instead of booking them as clean). A refusal propagates and
   * everything stays retryable — never automatic. The reference itself is dropped only on the
   * client's `releasesSettled` attestation that it can never announce another release; an empty
   * live view is not that proof, because a still-acquiring handle can fail its release later. */
  retryReleaseCleanup?(): Promise<void>
}

/** Layer-1 switch gate: any run still open on any connection. */
export function hasOpenRun(snapshots: readonly AgentSnapshot[]): boolean {
  return snapshots.some(snapshot => Object.values(snapshot.runs).some(run =>
    run.status === 'starting' || run.status === 'running' || run.status === 'stop-requested'))
}

/** Layer-1 switch gate: any approval/input still awaiting an answer on any connection. */
export function hasAwaitingInteraction(snapshots: readonly AgentSnapshot[]): boolean {
  return snapshots.some(snapshot => snapshot.interactions.some(interaction =>
    interaction.state === 'pending' || interaction.state === 'responding'))
}
