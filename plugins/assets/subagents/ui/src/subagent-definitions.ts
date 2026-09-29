// T11 domain ports — the faces the Chat menu contribution reads and acts through.
//
// Honesty boundary (capability-matrix.md, verification.md levels): no live
// implementation of either port exists in this repo yet. The server-side
// reader needs the `foundation` checkpoint (plan.md B1); the invoke gateway
// needs the proved native control entry reachable through Ordessa's own ACP
// path (harness-adapters.md §应用闭环 4, C4). This package therefore ships the
// ports plus the pure source built on them, tested against fakes at L1 only —
// nothing here claims L2/L3, and no fake is labelled as assembled production
// wiring.
import type { ChatActionResult, ChatLocation } from '@extensions/ordessa.chat-api/contract.js'

/** The four separate facts of data-model.md §状态和迁移. Absence of observation
 * is its own state: `unknown` is never collapsed into `no` — "no proved
 * control entry" and "proved absence of a control entry" are different gates
 * (FR07/FR15; G17 counter-example column). */
export type EvidenceState = 'yes' | 'no' | 'unknown'

export interface DefinitionState {
  readonly projected: EvidenceState
  readonly loaded: EvidenceState
  /** The gate for Chat availability: 'yes' only when an invocation entry was
   * observed through the target's proved path, never inferred from a visible
   * menu or a materialized file (FR15). */
  readonly invokable: EvidenceState
  /** Recordable only from a real native invocation event; a projection is not
   * a run (harness-adapters.md §应用闭环 4). */
  readonly used: EvidenceState
}

/** `managed` = Ordessa-owned definition; `native-discovered` = the target
 * harness found it itself and Ordessa does not manage it (US5: read-only,
 * never a green "生效" claim). */
export type DefinitionOrigin = 'managed' | 'native-discovered'

/** Item-level typed refusal from the resolver (C5 error taxonomy), e.g.
 * `PERMISSION_EXCEEDS_CEILING` or `NATIVE_VERSION_UNKNOWN`. */
export interface DefinitionRefusal {
  readonly code: string
  readonly detail: string
}

/** TypeScript mirror of the resolver's `ResolvedDefinition` projection for UI
 * consumers (data-model.md §ResolvedDefinition plus the four evidence facts).
 * The live mapping is produced by the future server-side reader; the shape is
 * deliberately conservative: display fields, harness binding, origin and the
 * separate evidence states — no runtime authority, no secrets, no paths. */
export interface EffectiveDefinition {
  readonly definitionId: string
  readonly revision: number
  /** The name the target harness would address the definition by. Never used
   * to derive identity (routing uses definitionId+revision), only for
   * collision diagnostics and display. */
  readonly nativeName: string
  readonly displayName: string
  readonly description: string
  readonly harnessId: string
  readonly origin: DefinitionOrigin
  readonly state: DefinitionState
  readonly refusal?: DefinitionRefusal
}

/** Read side (contracts.md §C1 `resolvePreview` projected to Chat): returns
 * the effective set for exactly the asked location. Read-only — no channel
 * creation, no session side effects, no disk scans (ChatInputSource contract). */
export interface SubagentDefinitionReader {
  readEffective(location: ChatLocation, signal: AbortSignal): Promise<readonly EffectiveDefinition[]>
}

/** One invocation request.
 *
 * `location` is the **selection-time** ChatLocation, i.e. the value Chat handed
 * to the entry action's `execute(location)` (chat-api r3), which this source has
 * just revalidated with `isLocationCurrent` before calling here. It is never the
 * location the entry was queried or rendered for: those can differ, and the whole
 * point of the port shape is that a business call only ever goes out against the
 * target the user actually picked (G17, input-contracts §1). */
export interface InvokeGatewayRequest {
  readonly location: ChatLocation
  readonly definition: EffectiveDefinition
}

/** The only invoke seam (contracts.md §C4): delegation to the existing
 * authorized restricted invocation action, which re-checks caller, target
 * definition, tool/permission/project ceiling, budget and parent session
 * state itself. A UI plugin never sends a bare protocol frame, never spawns,
 * never writes files — this port is that "never" made structural: there is no
 * other way out of an entry action. */
export interface InvokeGateway {
  invoke(request: InvokeGatewayRequest): Promise<ChatActionResult>
}

export type ExistingNameKind = 'slash-command' | 'skills'

/** One name already owned in the panel by another contributor — the FR10/G17
 * collision surface (plugins/commands slash names, Skills names). */
export interface ExistingName {
  readonly name: string
  readonly kind: ExistingNameKind
}

/** Read-only index of names a location already exposes to Chat input. Absence
 * of an entry means "no collision reported by the owner", never proof of
 * vacancy; the index is queried per location, results never cross-fill. */
export interface ExistingNameIndex {
  names(location: ChatLocation, signal: AbortSignal): Promise<readonly ExistingName[]>
}

/** Caller-supplied aggregate caps (data-model.md §范围解释: descriptions can
 * enter catalog/model context, so count and length are bounded before
 * display). Over-budget items drop only with a visible diagnostic entry. */
export interface InputBudget {
  readonly maxEntries?: number
  readonly maxDescriptionChars?: number
}
