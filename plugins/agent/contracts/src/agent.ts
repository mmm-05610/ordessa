import { Token, type IDisposable } from '@ordessa/extension-api'

export type Availability = 'supported' | 'unsupported' | 'unknown' | 'unavailable'
export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected' | 'error'
export type RunStatus = 'starting' | 'running' | 'stop-requested' | 'completed' | 'cancelled' | 'failed' | 'unknown'

export interface AgentCapabilities {
  history: Availability
  reasoning: Availability
  tools: Availability
  stop: Availability
  interactions: Availability
  models: Availability
  modes: Availability
  /** Server-authoritative project targeting (CP-SESSION-001); absent ≠ supported — never fall back silently. */
  workspaces?: Availability
}
export interface AgentConnectionInfo {
  id: string
  title: string
  status: ConnectionStatus
  error?: string
  capabilities: AgentCapabilities
  /** Real Server instance identity behind this connection; project selections are scoped by it, never by plugin id alone. */
  serverInstanceId?: string
}
/** One Server-authoritative project workspace record (FE never invents or reuses paths across servers). */
export interface AgentWorkspaceInfo {
  id: string
  normalizedPath: string
  environment?: string
}
export interface AgentSessionInfo {
  id: string
  title: string
  updatedAt?: string
  detail?: string
  /** Backend-authoritative project id; absent/null means a standalone session (P2-3, C-023). */
  workspaceId?: string
  pinned?: boolean
}
export interface AgentToolCall {
  id: string
  name: string
  arguments?: unknown
  result?: unknown
  status: 'running' | 'completed' | 'failed' | 'unknown'
}
export interface AgentMessage {
  id: string
  role: 'user' | 'assistant' | 'tool'
  text: string
  reasoning?: string
  tools?: readonly AgentToolCall[]
  status?: RunStatus
}
export interface AgentInteraction {
  id: string
  sessionId: string
  turnId?: string
  kind: 'approval' | 'choice' | 'confirm' | 'input' | 'editor'
  title: string
  detail?: string
  choices?: readonly { id: string; label: string }[]
  fields?: readonly { id: string; title: string; detail?: string; choices?: readonly { id: string; label: string }[]; secret?: boolean }[]
  state: 'pending' | 'responding' | 'resolved' | 'expired' | 'unknown'
}
export interface AgentOption {
  id: string
  title: string
  value?: string
  values?: readonly { id: string; title: string }[]
  availability: Availability
}
export interface AgentSnapshot {
  connection: AgentConnectionInfo
  sessions: readonly AgentSessionInfo[]
  sessionList: 'unknown' | 'loading' | 'ready' | 'partial' | 'error'
  selectedSessionId?: string
  messages: Readonly<Record<string, readonly AgentMessage[]>>
  runs: Readonly<Record<string, { id: string; sessionId: string; status: RunStatus; stoppable?: boolean }>>
  interactions: readonly AgentInteraction[]
  options: readonly AgentOption[]
  /** Server project table projection; present only when the client supports project targeting. */
  workspaces?: {
    state: 'unknown' | 'loading' | 'ready' | 'error'
    items: readonly AgentWorkspaceInfo[]
    /** Last selection revalidated against this Server; invalid or absent means sends are blocked. */
    selectedWorkspaceId?: string
  }
  diagnostic?: string
}
export type InteractionAnswer =
  | { kind: 'choice'; choiceId: string }
  | { kind: 'confirm'; confirmed: boolean }
  | { kind: 'text'; value: string }
  | { kind: 'answers'; answers: Readonly<Record<string, readonly string[]>> }
  | { kind: 'cancel' }

/** Explicit lifecycle of a managed channel's backend release. In-flight exists as a state of its
 * own so an unanswered attempt is NEVER inferable as confirmed: an empty failure record only ever
 * means "nothing failed", not "nothing outstanding". A confirmation is announced and then leaves
 * the live view — its absence is evidence only because the states were complete before it. */
export type AgentReleaseStatus = 'in-flight' | 'failed' | 'confirmed'
export interface AgentReleaseState {
  readonly connectionId: string
  readonly status: AgentReleaseStatus
  readonly reason?: string
}

/** A live, authoritative adapter instance. Operations never imply a terminal run state. */
export interface AgentClient extends IDisposable {
  getSnapshot(): AgentSnapshot
  subscribe(listener: () => void): () => void
  refreshSessions(): Promise<void>
  newSession(): Promise<string>
  openSession(id: string): Promise<void>
  send(sessionId: string, text: string): Promise<void>
  stop(sessionId: string, runId: string): Promise<void>
  respond(interactionId: string, answer: InteractionAnswer): Promise<void>
  setOption(id: string, value: string): Promise<void>
  /** Project-capable clients only (CP backend connector). Absent members must disable project UI, never fake it. */
  refreshWorkspaces?(): Promise<void>
  openWorkspace?(id: string): Promise<AgentWorkspaceInfo>
  /** Register a user-picked local directory with this Server, then select its authoritative project id. */
  addWorkspace?(path: string): Promise<AgentWorkspaceInfo>
  /** Channel-capable clients only (ACP connector): backend releases that failed, as host-readable
   * diagnostics. The host observes them here and retries through `retryReleases()`; absent or
   * empty means nothing stands retryable (in-flight answers live in `releaseStates()`). */
  readonly releaseFailures?: { readonly connectionId: string; readonly reason: string }[]
  /** Live view of every release the backend has not confirmed yet — in-flight or failed. A host
   * taking over observation must read this synchronously when it subscribes: a release that
   * answered before the subscription exists is outstanding here, and an absent subscription is
   * not an absence of history. */
  releaseStates?(): AgentReleaseState[]
  /** Subscribe to every release-state transition. Delivered after `dispose()` too: an evicted
   * client's asynchronous answers are precisely what the host must keep receiving, and this
   * notification — not polling — is how a state change reaches the host's published surface. */
  subscribeReleaseStates?(listener: (state: AgentReleaseState) => void): () => void
  /** The client's own attestation that it can NEVER announce another release state: it is
   * disposed, every in-flight acquire/initialize has finished standing its handle down, and
   * every stand-down it ever started is confirmed. Until this settles the host must not forget
   * the client — a live view that is empty RIGHT NOW is not evidence, because a handle still
   * being acquired can fail its release later. Resolves (never rejects); absent means the
   * client attests nothing, so there is nothing to forget. */
  readonly releasesSettled?: Promise<void>
  /** The host's explicit pass over outstanding releases: in-flight attempts are JOINED (never
   * doubled), failed ones get one further attempt, and a refusal propagates to the caller —
   * nothing is booked as confirmed except the backend's own answer. Works after dispose(). */
  retryReleases?(): Promise<void>
  /** First send of a draft: Server creates and executes under workspaceId with the given idempotency requestId.
   * Resolves only once the same requestId is confirmed accepted and the real non-empty session id is in the
   * snapshot and selected (FC-0031); an unknown outcome rejects and the caller keeps the requestId. */
  createAndSend?(workspaceId: string, text: string, requestId: string): Promise<{ sessionId: string }>
}
export interface AgentConnector {
  id: string
  title: string
  connect(): Promise<AgentClient>
}

export interface AgentWorkspaceSnapshot {
  available: readonly Pick<AgentConnector, 'id' | 'title'>[]
  selectedConnectionId?: string
  connectingId?: string
  error?: string
  /** Backend releases of evicted clients the Server has not confirmed yet — in-flight or failed —
   * with their explicit states: the connections workspace holds those lifecycle references, a
   * release-state notification re-publishes this surface the moment it changes, and a confirmed
   * answer is what removes an entry. */
  pendingReleases?: AgentReleaseState[]
  agent?: AgentSnapshot
  /** Front-end-only new-session draft; never a backend session until first send is accepted. */
  draft?: {
    active: boolean
    /** Draft inherits the revalidated per-connection project selection; absence blocks send. */
    workspaceId?: string
    canSend: boolean
    blockReason?: 'unsupported' | 'no-project' | 'project-invalid'
    /** How the last draft ended, so downstream can distinguish without guessing (C-0030):
     * 'discarded' = discardDraft, the previously selected session was never cleared and is restored;
     * 'opened' = openSession moved the selection away from the draft. Cleared by the next startDraft;
     * an accepted first send ends the draft by selecting the new real session and reports no endedBy. */
    endedBy?: 'discarded' | 'opened'
  }
}
/** Owns connected instances independently of mounted Workbench views. */
export interface AgentSessions {
  getSnapshot(): AgentWorkspaceSnapshot
  subscribe(listener: () => void): () => void
  selectConnection(id: string): Promise<void>
  reconnect(id: string): Promise<void>
  refreshSessions(): Promise<void>
  newSession(): Promise<void>
  openSession(id: string): Promise<void>
  send(text: string): Promise<void>
  stop(runId: string): Promise<void>
  respond(interactionId: string, answer: InteractionAnswer): Promise<void>
  setOption(id: string, value: string): Promise<void>
  /** CP draft/project members are implemented by this facade (F2); optional here so pre-CP consumers keep compiling. */
  startDraft?(): void
  discardDraft?(): void
  selectWorkspace?(id: string): Promise<void>
  addWorkspace?(path: string): Promise<void>
  refreshWorkspaces?(): Promise<void>
}
export const AgentSessionsToken = new Token<AgentSessions>('ordessa.agent.sessions.v1')
