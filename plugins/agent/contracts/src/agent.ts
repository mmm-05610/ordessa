import { Token, type IDisposable } from '@ordessa/extension-api'

// Revision ledger (chat-api r4 rules: every semantic change carries its
// compatibility note here and in the delivering package's report).
//
// 0.2.0 — 014 P-C (R-Z2-1/2/3/5):
// - `AgentClient.send` upgraded from `Promise<void>` to a decidable three-state
//   `AgentSubmissionOutcome | void` (see the member's note for the
//   resolve→accepted compatibility rule and the migrated consumers).
// - Optional members added: `submitWithAttachments`, `getNativeCommands`,
//   `attachmentCapabilities`, `prepareAttachment`, `releasePreparedAttachment`,
//   `admissionEvidence`. Absent members disable the corresponding UI honestly —
//   never fake it; every one of them is satisfied by the existing ACP
//   connector implementation without touching the frozen connectors packages.
// - `AgentMessage.reasoningState` (R-Z2-5): optional evidence; absent = the
//   legacy string-only shape (status inherits the run status, no fabricated
//   duration). No current connector produces it (registered S-05 family).
// - `AgentSessions.send` upgraded to `Promise<AgentSubmissionOutcome>` with an
//   optional opaque prepared-reference list; `commandCatalog` and
//   `attachments` added; `AgentWorkspaceSnapshot.runtimeGeneration` added (PC-5).

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
  /** R-Z2-5: reasoning's own evidence, when the connector reports one. Absent
   * means the string-only legacy shape: the display status then inherits the
   * message's run status and no duration may be fabricated. */
  reasoningState?: { readonly status: 'streaming' | 'complete' | 'interrupted' | 'unknown'; readonly durationMs?: number }
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

/** R-Z2-1: the three decidable submission outcomes. `accepted` means the send
 * path took the submission — never that tools or the run succeeded. `refused`
 * carries the backend's typed code; `unknown` means the outcome is
 * undecidable (lost answer, channel down) and carries the operation id the
 * caller must keep: no automatic resend may follow it. */
export type AgentSubmissionOutcome =
  | { readonly kind: 'accepted' }
  | { readonly kind: 'refused'; readonly code: string; readonly reason: string }
  | { readonly kind: 'unknown'; readonly operationId: string; readonly reason: string }

/** One native (brand) command as the connector observed it. Names are data,
 * never an instruction to submit. */
export interface AgentNativeCommand {
  readonly name: string
  readonly description: string
  readonly inputHint?: string
}

/** Connector-level native command catalog (R-Z2-3). `unknown` reasons are the
 * connector's own evidence verdicts, never synthesized brand menus. */
export type AgentNativeCommandCatalog =
  | Readonly<{ kind: 'absent' }>
  | Readonly<{ kind: 'unknown'; reason: 'malformed' | 'stale-session' | 'channel-down' | 'unobservable' }>
  | Readonly<{ kind: 'available'; connectionId: string; nativeSessionId: string; commands: readonly AgentNativeCommand[] }>

/** Facade-level command catalog projection (R-Z2-3): the four states the chat
 * panel renders. `loading` is declarable by a connector that can observe a
 * catalog in flight; no current connector produces it (registered in the 014
 * P-C report), so absence of evidence must never be rendered as loading. */
export type AgentCommandCatalog =
  | Readonly<{ kind: 'absent' }>
  | Readonly<{ kind: 'loading' }>
  | Readonly<{ kind: 'error'; reason: string }>
  | Readonly<{ kind: 'available'; connectionId: string; nativeSessionId: string; commands: readonly AgentNativeCommand[] }>

/** Connector-level attachment capability answer (R-Z2-2). */
export type AgentAttachmentCapabilities =
  | { readonly kind: 'available'; readonly mimeTypes: readonly string[]; readonly uriSchemes: readonly string[];
      readonly maxBytes: number; readonly maxCount: number }
  | { readonly kind: 'absent'; readonly reason: string }
  | { readonly kind: 'unknown'; readonly reason: string }

/** One owner-prepared attachment. `preparedId` is opaque owner-issued
 * identity; `sha256` is the content digest the round trip must reproduce. */
export interface AgentPreparedAttachment {
  readonly preparedId: string
  readonly name: string
  readonly uri: string
  readonly mimeType: string
  readonly sha256: string
  readonly byteLength: number
}

export type AgentAttachmentPreparation =
  | { readonly kind: 'prepared'; readonly reference: AgentPreparedAttachment }
  | { readonly kind: 'refused'; readonly reason: string }
  | { readonly kind: 'unknown'; readonly operationId: string }

/** Backend-observed admission facts (S-05 producer surface, mirrored from the
 * Server's controlled next-submit coordinator). Only a backend owner may
 * supply them; a client that cannot observe them must not implement this
 * member, and an absent member is itself the fail-closed evidence. */
export interface AgentAdmissionEvidence {
  readonly connectionId: string
  readonly nativeSessionId: string
  readonly runtimeGeneration: number
  readonly admissionSupported: boolean
  readonly q5Ready: boolean
  readonly chatApiReady: boolean
  readonly outputInProgress: boolean
}

/** A live, authoritative adapter instance. Operations never imply a terminal run state. */
export interface AgentClient extends IDisposable {
  getSnapshot(): AgentSnapshot
  subscribe(listener: () => void): () => void
  refreshSessions(): Promise<void>
  newSession(): Promise<string>
  openSession(id: string): Promise<void>
  /**
   * Revision 0.2.0 (014 P-C, R-Z2-1): upgraded from `Promise<void>` to a
   * decidable three-state outcome. Compatibility rule: a client that resolves
   * with `void` (every connector published before this revision) means exactly
   * the old send-path acceptance — resolve→accepted, never execution success;
   * typed refusals and evidenced channel loss map to refused/unknown. Consumers
   * migrated one by one and recorded in the 014 P-C report: the sessions
   * facade (the mapping owner), the chat gateway (1:1), and the retired
   * agent-conversation view (PC-6). Attachments never ride this member: a
   * client that cannot carry prepared refs end to end must not be handed any —
   * the carry path is `submitWithAttachments` below.
   */
  send(sessionId: string, text: string): Promise<AgentSubmissionOutcome | void>
  /** R-Z2-2 carry path: text plus already-prepared attachment references,
   * admitted through the backend's controlled submission. Present exactly when
   * the client can carry refs end to end (prepare→verify→admit); absent means
   * the facade must refuse attachments before any call — never drop them. */
  submitWithAttachments?(sessionId: string, text: string, attachments: readonly AgentPreparedAttachment[]): Promise<AgentSubmissionOutcome>
  /** R-Z2-3: the native command catalog of one session key (the snapshot's
   * session id). Absent member = the connector projects no catalog. */
  getNativeCommands?(sessionKey: string): AgentNativeCommandCatalog
  /** R-Z2-2 attachment seam. All-or-nothing: a client offering preparation
   * must offer release too; `submitWithAttachments` is the only carry path. */
  attachmentCapabilities?(sessionId: string): Promise<AgentAttachmentCapabilities>
  /** `sourceId` names content the port already owns, never a renderer path. */
  prepareAttachment?(sessionId: string, sourceId: string, idempotencyKey: string): Promise<AgentPreparedAttachment>
  releasePreparedAttachment?(sessionId: string, preparedId: string): Promise<void>
  /** Backend-observed admission facts; absent = fail-closed (the facade refuses
   * before any wire traffic instead of guessing the backend ready). */
  admissionEvidence?(): AgentAdmissionEvidence | undefined
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
  /** PC-5 (R-Z2 generation fence): the selected client's backend-confirmed
   * runtime generation, when it can observe one (admission evidence). Absent
   * means no backend generation evidence exists — the UI-internal revision
   * counters never stand in for it. */
  runtimeGeneration?: number
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
  send(text: string, attachments?: readonly string[]): Promise<AgentSubmissionOutcome>
  stop(runId: string): Promise<void>
  respond(interactionId: string, answer: InteractionAnswer): Promise<void>
  setOption(id: string, value: string): Promise<void>
  /** CP draft/project members are implemented by this facade (F2); optional here so pre-CP consumers keep compiling. */
  startDraft?(): void
  discardDraft?(): void
  selectWorkspace?(id: string): Promise<void>
  addWorkspace?(path: string): Promise<void>
  refreshWorkspaces?(): Promise<void>
  /** R-Z2-3: the selected connection's native command catalog for one session
   * key (a snapshot session id). Always present on this facade: a connection
   * whose client projects no catalog answers `absent`, never a fake menu. */
  commandCatalog(sessionKey: string): AgentCommandCatalog
  /** R-Z2-2 plugin-half attachment seam over the selected connection. Present
   * on the facade, but every answer degrades honestly: a client without the
   * full prepare→carry chain, a draft with no native session, or an absent
   * production prepare owner all answer `absent`/`refused` with the reason. */
  readonly attachments: {
    capability(sessionId?: string): { readonly kind: 'available' } | { readonly kind: 'absent'; readonly reason: string } | { readonly kind: 'unknown'; readonly reason: string }
    prepare(request: { readonly sessionId?: string; readonly sourceId: string; readonly idempotencyKey: string }): Promise<AgentAttachmentPreparation>
    release(preparedId: string, reason: 'draft-removed' | 'draft-cancelled'): Promise<void>
  }
}
export const AgentSessionsToken = new Token<AgentSessions>('ordessa.agent.sessions.v1')
