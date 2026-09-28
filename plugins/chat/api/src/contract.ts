// Chat domain public contract (chat-api; r3 consumes foundation types, r4 is
// the 014 P-C real-seam revision — see the ledger at the bottom of this file).
//
// Depends on `@ordessa/extension-api` and the shared platform component API.
// Component keys are constructed by `defineChatComponentKey` through C7's
// public factory. This package copies no platform Token and invents no
// ServiceLocator; provider ownership always comes from the host-issued
// ResourceScope, never a caller-supplied owner string (contracts.md §4).
import { Token, type IDisposable, type ResourceScope } from '@ordessa/extension-api'
import { defineUiComponent, type UiComponentKey } from '@ordessa/ui-components/api'
import type { ReactNode } from 'react'

// ---------------------------------------------------------------------------
// Component keys (the platform's UiComponentKey)
// ---------------------------------------------------------------------------

/** Identity of one replaceable Chat display interface — the platform's own
 * branded `UiComponentKey` type, so a chat key satisfies every C7-typed
 * consumer API unchanged (contracts.md §4). */
export type ChatComponentKey<P> = UiComponentKey<P>

/** The only Chat construction site; delegates to the platform factory. */
export function defineChatComponentKey<P>(id: string, major: number): ChatComponentKey<P> {
  return defineUiComponent<P>(id, major)
}

/** Full-width readable agent/user body (contracts.md §6 `message-body`). */
export const ChatMessageBodyKey = defineChatComponentKey<ChatMessageBodyProps>('ordessa.chat.message-body', 1)
/** Collapsible reasoning block; user choice beats every state transition. */
export const ChatReasoningKey = defineChatComponentKey<ChatReasoningProps>('ordessa.chat.reasoning', 1)
/** Compact tool summary row with lazy detail (contracts.md §6 `tool-activity`). */
export const ChatToolActivityKey = defineChatComponentKey<ChatToolActivityProps>('ordessa.chat.tool-activity', 1)
/** Fixed bottom input surface; owns no draft persistence (contracts.md §6 `composer`). */
export const ChatComposerKey = defineChatComponentKey<ChatComposerProps>('ordessa.chat.composer', 1)

// ---------------------------------------------------------------------------
// Action semantics (aligned with the platform UiAction: `accepted` means the
// business took the operation, never that it finished)
// ---------------------------------------------------------------------------

export type ChatActionResult =
  | { readonly status: 'accepted' }
  | { readonly status: 'refused'; readonly message: string }
  | { readonly status: 'unavailable' }

/** Scoped action dispatched with the location that was revalidated at
 * selection time; stale locations must yield `unavailable` without a
 * business call (input-contracts §1). */
export type ChatScopedAction<I> = (input: I) => Promise<ChatActionResult>

// ---------------------------------------------------------------------------
// Location (contracts.md §3). Session identity maps the agent-contracts
// facade (connectionId + serverInstanceId? + sessionId); no second routing
// standard is invented here. Absent fields stay absent — identity is never
// guessed from titles, plugin ids or endpoints.
// ---------------------------------------------------------------------------

export type ChatLocation =
  | { readonly kind: 'draft'; readonly draftId: string; readonly connectionId?: string; readonly serverInstanceId?: string;
      readonly projectId?: string; readonly harnessId?: string; readonly contextRevision: number; readonly runtimeGeneration?: number }
  | { readonly kind: 'session'; readonly connectionId: string; readonly serverInstanceId?: string; readonly sessionId: string;
      readonly projectId?: string; readonly harnessId?: string; readonly contextRevision: number; readonly runtimeGeneration?: number }

// ---------------------------------------------------------------------------
// Display DTOs for the four replaceable keys (contracts.md §6)
// ---------------------------------------------------------------------------

/** Content-level output state. `unknown` is its own state: evidence absence is
 * never rendered as success, and a parent run state never proves this content
 * finished (service-adaptation §2). */
export type ChatContentStatus = 'streaming' | 'complete' | 'interrupted' | 'unknown'

export interface ChatMessageBodyProps {
  readonly conversationKey: string
  readonly messageId: string
  readonly role: 'user' | 'assistant'
  readonly body: string
  readonly status: ChatContentStatus
  /** Display-only options (line wrapping); never a data source. */
  readonly display?: { readonly codeWrap?: boolean }
  /** Provided by the consumer or the buttons do not exist; the component itself
   * never opens links or touches the clipboard. Links are pre-verified. */
  readonly actions?: {
    readonly openLink?: (url: string) => Promise<ChatActionResult>
    readonly copyVisibleBody?: () => Promise<ChatActionResult>
  }
}

export interface ChatReasoningProps {
  readonly conversationKey: string
  readonly partId: string
  readonly text: string
  readonly status: ChatContentStatus
  /** Only a real backend-provided duration; UI timers must not fake it. */
  readonly durationMs?: number
  /** Consumer-provided; the copy affordance is hidden when absent. */
  readonly copy?: () => Promise<ChatActionResult>
}

export type ChatToolState = 'running' | 'completed' | 'failed' | 'unknown'

export interface ChatToolActivityProps {
  readonly conversationKey: string
  readonly toolId: string
  readonly title: string
  readonly state: ChatToolState
  /** Pre-formatted, display-safe input/output text; adapters decide formatting,
   * the component never parses service payloads (research-plan §5). */
  readonly paramsText?: string
  readonly outputText?: string
  /** Structured command display when verified fields exist; absence renders
   * generic and the component never reconstructs command details. */
  readonly command?: {
    readonly command: string
    readonly output?: { readonly text: string; readonly truncated?: boolean; readonly exitCode?: number | 'unknown' }
  }
  readonly truncationNote?: string
  readonly errorText?: string
  readonly actions?: {
    readonly viewFullOutput?: () => Promise<ChatActionResult>
    readonly copy?: () => Promise<ChatActionResult>
    readonly openRelated?: () => Promise<ChatActionResult>
  }
}

export interface ChatComposerProps {
  readonly draftId: string
  /** Controlled text; the composer stores no draft of its own. */
  readonly text: string
  readonly editable: boolean
  readonly onTextChange: (value: string) => void
  readonly send: { readonly enabled: boolean; readonly pending: boolean; readonly reason?: string; readonly submit: () => void }
  readonly stop?: { readonly enabled: boolean; readonly pending: boolean; readonly reason?: string; readonly request: () => void }
  /** Contribution area (composer.toolbar); core send/stop never depends on it. */
  readonly toolbar?: ReactNode
  /** Attachment/suggestion callbacks exist only when the consumer verified the
   * capability; absent means the affordance is disabled with a reason, never
   * receive-then-drop (input-spec A03). */
  readonly attachments?: ChatComposerAttachments
  readonly suggestions?: {
    readonly openPanel: (surface: ChatInputSurface) => void
    readonly closePanel: () => void
  }
}

export interface ChatComposerAttachments {
  readonly disabledReason?: string
  readonly pick: (kinds: readonly ('file' | 'image')[]) => void
  readonly remove: (itemId: string) => void
  readonly retry: (itemId: string) => void
}

// ---------------------------------------------------------------------------
// Contributions (contracts.md §2/§4): six positions, typed descriptors, opaque
// registration records
// ---------------------------------------------------------------------------

export type ChatSlot =
  | 'composer.toolbar'
  | 'session.actions'
  | 'session.auxiliary'
  | 'message.actions'
  | 'settings.sections'
  | 'content.renderers'

export interface ChatDisplayEnvironment {
  readonly locale: string
  readonly theme: 'light' | 'dark' | 'system'
}

/** Read-only context handed to a projection; never credentials, full history,
 * service instances or an execution escape hatch (contracts.md §3). */
export type ChatContributionContext =
  | { readonly slot: 'composer.toolbar'; readonly location: ChatLocation; readonly connection: { readonly status: string; readonly runStatus?: string } }
  | { readonly slot: 'session.actions'; readonly location: ChatLocation & { readonly kind: 'session' } }
  | { readonly slot: 'session.auxiliary'; readonly location: ChatLocation & { readonly kind: 'session' }; readonly connection: { readonly status: string; readonly runStatus?: string } }
  | { readonly slot: 'message.actions'; readonly location: ChatLocation & { readonly kind: 'session' }; readonly messageId: string; readonly messageStatus: ChatContentStatus }
  | { readonly slot: 'settings.sections'; readonly environment: ChatDisplayEnvironment }
  | { readonly slot: 'content.renderers'; readonly location: ChatLocation; readonly contentKind: string; readonly payload: unknown }

export type ChatProjection<P> = (context: ChatContributionContext) => { readonly hidden: true } | { readonly hidden: false; readonly props: P }

declare const registrationBrand: unique symbol
/** Opaque, erased contribution record built only by {@link chatContribution}
 * (see ./registry); the read side cannot reassemble one by hand. */
export interface ChatContributionRegistration {
  readonly [registrationBrand]: never
}

// ---------------------------------------------------------------------------
// Input sources (input-contracts §1): structured entries for the shared
// plus/slash panel — not a seventh component slot
// ---------------------------------------------------------------------------

export type ChatInputSurface = 'plus' | 'slash'

export interface ChatInputQuery {
  readonly location: ChatLocation
  readonly query: string
  readonly surface: ChatInputSurface
  readonly signal: AbortSignal
}

declare const referenceBrand: unique symbol
/** Opaque content reference owned by the service that issued it. Local preview
 * URLs never enter the protocol (input-contracts §2). */
export type ChatContentReference = string & { readonly [referenceBrand]: never }

export type ChatInputEntryAction =
  | { readonly kind: 'insert-command'; readonly text: string }
  | { readonly kind: 'add-content'; readonly prepare: (location: ChatLocation, idempotencyKey: string) => Promise<ChatPrepareResult> }
  | { readonly kind: 'invoke'; readonly execute: (location: ChatLocation) => Promise<ChatActionResult> }

/** Result of an add-content preparation: `accepted` carries the service-owned
 * reference; a refusal is explicit and never interpreted; `unknown` means the
 * preparation outcome is undecidable — the item stays in the draft, nothing is
 * auto-retried or auto-cleaned (r4). */
export type ChatPrepareResult =
  | { readonly status: 'accepted'; readonly reference: ChatContentReference }
  | { readonly status: 'refused'; readonly message: string }
  | { readonly status: 'unavailable' }
  | { readonly status: 'unknown' }

export interface ChatInputEntry {
  /** Unique within its source; routing uses this id, never the display title. */
  readonly id: string
  readonly title: string
  readonly description?: string
  readonly groupId: string
  readonly order: number
  readonly surfaces: readonly ChatInputSurface[]
  readonly availability: { readonly kind: 'ready' } | { readonly kind: 'disabled'; readonly reason: string }
  readonly action: ChatInputEntryAction
}

export interface ChatInputSource {
  /** Namespaced source id; duplicates are rejected. */
  readonly id: string
  /** Display provenance; same-named entries stay distinguishable by this. */
  readonly title: string
  readonly groups: readonly { readonly id: string; readonly title: string; readonly order: number }[]
  /** Read-only query: no channel creation, no session side effects, no disk
   * scans. A returned cancellation is a UI cancellation, never a business one
   * (input-contracts §1). */
  query(request: ChatInputQuery): Promise<readonly ChatInputEntry[]>
}

// ---------------------------------------------------------------------------
// Draft, submission snapshot and attachment lifecycle (input-contracts §2)
// ---------------------------------------------------------------------------

export type ChatInputItemKind = 'file' | 'image' | 'directory-reference'

export type ChatAttachmentPhase =
  | { readonly state: 'selected' }
  | { readonly state: 'preparing' }
  | { readonly state: 'ready'; readonly reference: ChatContentReference }
  | { readonly state: 'failed'; readonly reason: string }
  | { readonly state: 'unknown'; readonly operationId?: string }
// Retry returns to `preparing`; remove terminates the current UI generation and
// releases only this draft's own resources. Content already handed to a sent
// record is never released by UI teardown (input-spec A05). `unknown` (r4) is
// the undecidable preparation outcome: the item stays visible and send-blocking,
// retry re-uses the SAME idempotency key, and nothing is auto-reclaimed.

export interface ChatInputItem {
  readonly id: string
  readonly sourceId: string
  readonly kind: ChatInputItemKind
  readonly displayName: string
  readonly size?: number
  readonly mimeType?: string
  readonly phase: ChatAttachmentPhase
  /** Local object URL for preview only; never serialized into a submission. */
  readonly previewUrl?: string
}

export interface ChatDraftState {
  readonly draftId: string
  readonly connectionId?: string
  readonly serverInstanceId?: string
  readonly projectId?: string
  readonly harnessId?: string
  readonly text: string
  readonly inputItems: readonly ChatInputItem[]
  readonly revision: number
}

/** Everything a submission commits to, frozen at send time; text or items the
 * user adds afterwards are not part of it. */
export interface ChatSubmissionSnapshot {
  readonly submissionId: string
  readonly target: ChatLocation
  readonly draftId: string
  readonly draftRevision: number
  readonly text: string
  readonly attachmentIds: readonly string[]
  /** r4 (R-Z2-2): the opaque prepared references of the ready items, in item
   * order. The gateway resolves them through the owning service; ids stay for
   * draft bookkeeping. Absent in pre-r4 producers — consumers must treat it as
   * optional forever. */
  readonly attachmentRefs?: readonly ChatContentReference[]
}

export type ChatSubmissionResult =
  | { readonly status: 'accepted' }
  | { readonly status: 'refused'; readonly reason: string }
  | { readonly status: 'unknown' }
// `accepted` means the send path took the submission — never that tools or the
// run succeeded. `unknown` keeps the draft and its ids: no automatic resend, no
// draft clearing, no session re-creation (input-contracts §2).

// ---------------------------------------------------------------------------
// Consumer-side service seams (implemented by the session/transport owners).
// An absent member disables the corresponding UI with a reason; it is never
// faked locally (input-contracts §3, service-adaptation §2).
// ---------------------------------------------------------------------------

export interface ChatCommandCatalog {
  get(target: ChatLocation):
    | { readonly status: 'ready'; readonly commands: readonly { readonly id: string; readonly title: string;
        readonly insertText: string; readonly description?: string }[] }
    | { readonly status: 'loading' }
    | { readonly status: 'error'; readonly message: string }
    | { readonly status: 'absent' }
}

export interface ChatAttachmentCapability {
  readonly supported: boolean
  readonly reason?: string
  readonly limits?: { readonly maxCount?: number; readonly maxBytes?: number; readonly mimeTypes?: readonly string[] }
  /** Directories may be attached as explicit references (never recursive reads). */
  readonly directoryReferences?: boolean
}

export interface ChatAttachmentService {
  capability(target: ChatLocation): ChatAttachmentCapability
  /** Content preparation through the owning service; the idempotency key is
   * the retry identity, not the file name (input-spec A05). */
  prepare(request: { readonly target: ChatLocation; readonly item: ChatInputItem; readonly idempotencyKey: string; readonly signal: AbortSignal }):
    Promise<ChatActionResult & { readonly reference?: ChatContentReference }>
  release(reference: ChatContentReference, request: { readonly reason: 'draft-removed' | 'draft-cancelled' }): Promise<void>
}

export interface ChatSessionGateway {
  /** The only send shape Chat consumes. With today's text-only facade the
   * adapter maps honestly: a resolved send is `accepted` (the send path took
   * it), a typed rejection is `refused`, and only evidenced outcomes produce
   * `unknown` — a resolve is never upgraded to execution success. */
  submit(snapshot: ChatSubmissionSnapshot): Promise<ChatSubmissionResult>
}

// ---------------------------------------------------------------------------
// The scoped service (contracts.md §4 + input-contracts §1: one scoped API,
// `addInputSource` is not a seventh slot)
// ---------------------------------------------------------------------------

/** Erased read-side view of a contribution. The key↔props pairing was checked
 * at registration; reads are intentionally untyped per item (an `unknown`
 * props carrier, not an `any` array) so the outlet can resolve the component
 * by key identity. */
export interface ChatContributionView {
  readonly id: string
  readonly slot: ChatSlot
  readonly order: number
  readonly keyId: string
  readonly keyMajor: number
  readonly contentKind?: string
  readonly project?: (context: ChatContributionContext) => { readonly hidden: true } | { readonly hidden: false; readonly props: unknown }
  readonly decode?: (payload: unknown) => unknown | null
}

export interface ChatInputSourceState {
  readonly status: 'ready' | 'loading' | 'error'
  readonly error?: string
}

export interface ChatInputSourceView {
  readonly source: ChatInputSource
  readonly state: ChatInputSourceState
  /** Merged, stably ordered entries; `ordering` is (group.order, group.id,
   * entry.order, entry.id) and never depends on registration timing. */
  readonly entries: readonly ChatInputEntry[]
}

export interface ObservableValues<T> {
  getSnapshot(): readonly T[]
  subscribe(listener: () => void): () => void
}

export interface ChatContributionsService {
  /** Ownership comes from the host-issued scope; closing the scope revokes
   * exactly this scope's registrations. */
  forScope(scope: ResourceScope): {
    addContribution(registration: ChatContributionRegistration): IDisposable
    addInputSource(source: ChatInputSource): IDisposable
  }
  contributionsBySlot(slot: ChatSlot): ObservableValues<ChatContributionView>
  /** Aggregated live query state; drives the shared panel's per-source
   * loading/error/ready presentation (input-spec P04). */
  queryInputSources(request: ChatInputQuery): ObservableValues<ChatInputSourceView>
}

export const ChatContributionsToken = new Token<ChatContributionsService>('ordessa.chat.contributions.v1')

// The registration factory and the in-memory service implementation live in
// ./registry (single runtime direction: registry → types here, never back).
export { chatContribution, createChatContributions } from './registry'

// ---------------------------------------------------------------------------
// Revision ledger (r4 rules: every semantic change carries its compatibility
// note here and in the delivering package's report).
//
// r1 — domain contract + registry (a3ec20c046).
// r2 — prepare/execute signatures narrowed to explicit location params +
//      ChatPrepareResult three-state (be672a59a0); no external consumers at
//      publication, compatibility recorded in the checkpoint limitations.
// r3 — ChatComponentKey aligned to the platform UiComponentKey (type-only;
//      runtime objects unchanged) (47459b0acb).
// r4 — 014 P-C real-seam revision (all changes additive; pre-r4 consumers keep
//      compiling and behaving identically):
//      1. ChatLocation.runtimeGeneration (PC-5): the backend-confirmed runtime
//         generation when the session service observes one. Compatibility:
//         contextRevision KEEPS its UI-internal staleness meaning; it never
//         stands in for a backend generation, and an absent runtimeGeneration
//         means exactly "no backend generation evidence" — producers must not
//         synthesize one from UI counters.
//      2. ChatSubmissionSnapshot.attachmentRefs (PC-3): opaque prepared
//         references riding the submission; attachmentIds stay the draft
//         bookkeeping identity. Optional; gateways resolve refs through the
//         owning service and must refuse unknown refs, never drop them.
//      3. ChatAttachmentPhase gains `unknown` and ChatPrepareResult gains an
//         `unknown` status (PC-3): the undecidable preparation outcome keeps
//         the item in the draft, send-blocking, retry with the SAME
//         idempotency key, never auto-reclaimed.
//      4. add-content prepare gains the idempotencyKey parameter (input-spec
//         A05: the key is the retry identity, not the file name); the caller
//         mints it once per item and re-uses it on every retry.
//      5. ready catalog commands gain an optional `description` (the brand's
//         own command description; absence renders title-only).
// ---------------------------------------------------------------------------
