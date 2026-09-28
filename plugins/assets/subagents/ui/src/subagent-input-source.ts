// T11 — subagent definitions as a ChatInputSource (G17, US6, FR11, FR15, FR06).
//
// The rule this module exists to enforce (ux.md §Chat/调用, contracts.md §C2):
// Chat may offer "use this subagent" ONLY for a definition whose `invokable`
// evidence is 'yes' at its pin; everything else is detail-only, and a detail
// entry must never degrade into a pseudo-call — no `insert-command` text like
// "use <name>", nothing appended to the user message. Structurally, this file
// contains no construction of the `insert-command` action kind at all; the
// behaviour tests scan every emitted action's `kind` to keep that honest.
//
// Location honesty (chat-api r3): `invoke` actions receive the selection-time
// ChatLocation from Chat. This module treats that argument as the only
// authoritative target for a business call and never threads the query's
// location into an action closure; a stale target yields `unavailable` with
// zero reader and zero gateway calls (G17, input-contracts §1).
import {
  type ChatActionResult, type ChatInputEntry, type ChatInputEntryAction, type ChatInputQuery,
  type ChatInputSource, type ChatInputSurface, type ChatLocation,
} from '@extensions/ordessa.chat-api/contract.js'
import type {
  DefinitionOrigin, DefinitionState, EffectiveDefinition, ExistingName, ExistingNameIndex,
  InputBudget, InvokeGateway, SubagentDefinitionReader,
} from './subagent-definitions'

/** Namespaced source id; the real registry rejects a second registration
 * under this id (input-contracts §1). */
export const SUBAGENT_INPUT_SOURCE_ID = 'ordessa.assets.native-subagents'

const GROUP = { id: 'ordessa.assets.native-subagents/subagents', title: 'Subagents', order: 10 } as const
const SURFACES: readonly ChatInputSurface[] = Object.freeze(['plus', 'slash'])

/** Adapter pins measured in specs/011-q3-subagents/capability-matrix.md (T02,
 * frozen 2026-09-28). A reason cites a pin only when the pin is registered
 * here — G01's negative column forbids upgrading an unregistered brand into a
 * versioned claim, in either direction. */
const HARNESS_PINS: Readonly<Record<string, string>> = Object.freeze({
  claude: '@agentclientprotocol/claude-agent-acp@0.81.2',
  codex: '@agentclientprotocol/codex-acp@1.1.14',
  pi: '@automatalabs/pi-acp@0.5.0',
})

/** Mirrors `RESERVED_NATIVE_NAMES` in the resolver
 * (plugins/assets/subagents/src/ordessa_assets_subagents/resolution.py) — kept
 * as a local constant because the TS face may not import Python; the boundary
 * stays one-directional through the reader port's data. */
const RESERVED_NATIVE_NAMES: readonly string[] = Object.freeze(['default', 'main', 'root', 'self'])

export interface SubagentInputSourceDeps {
  /** Required and explicit: either the real invocation owner or a written-down
   * `null` ("no invocation owner is wired yet"). There is no optional/default
   * gateway — a silent default would pretend an invoke could happen. */
  readonly gateway: InvokeGateway | null
  readonly existingNames: ExistingNameIndex
  /** Identity check against the current Chat input target. Location identity
   * comes from Chat (session/draft ids on ChatLocation), never guessed from
   * titles or plugin ids.
   *
   * chat-api r3: the `invoke` action is dispatched with the selection-time
   * ChatLocation, so this is called with exactly that argument — the target
   * the user picked, not the target the entry was rendered for. The render
   * location is not available to the action any more. */
  readonly isLocationCurrent: (location: ChatLocation) => boolean
  readonly limits?: InputBudget
}

const originLabel = (origin: DefinitionOrigin): string =>
  origin === 'managed' ? 'Ordessa-managed' : 'native-discovered, not Ordessa-managed (read-only)'

/** Why an entry is disabled at the evidence layer (origin / refusal /
 * invokability), independent of location freshness, collisions and gateway
 * wiring. Every branch names the missing evidence concretely; `unknown` and
 * `no` produce different sentences by construction (FR07, G17). */
export function evidenceReason(definition: EffectiveDefinition): string | undefined {
  if (definition.origin === 'native-discovered')
    return 'native-discovered item is not managed by Ordessa; detail only — no invoke, no disable claim Ordessa cannot enforce (US5/G13)'
  if (definition.refusal)
    return `${definition.refusal.code}: ${definition.refusal.detail}`
  const pin = HARNESS_PINS[definition.harnessId]
  switch (definition.state.invokable) {
    case 'yes':
      return undefined
    case 'unknown':
      if (pin === undefined)
        return `harness "${definition.harnessId}" has no registered capability pin; invokability unobserved — unknown is not no (FR07)`
      if (definition.harnessId === 'claude')
        return `no proved control entry at pin ${pin}: the adapter exposes a native subagent control tool, but Ordessa's ACP path passes none of it through (capability-matrix SR-1/SR-3); invokability unobserved — unknown is not no`
      if (definition.harnessId === 'codex')
        return `no proved control entry at pin ${pin}: the pinned adapter discovers no subagent root on the ACP path; invokability unobserved — unknown is not no`
      if (definition.harnessId === 'pi')
        return `Pi extension-backed entry absent: no Harness-audited extension and no control port at pin ${pin}; invokability unobserved — unknown is not no (G14)`
      return `no proved control entry at pin ${pin}; invokability unobserved — unknown is not no`
    case 'no':
      if (pin === undefined)
        return `harness "${definition.harnessId}" has no registered capability pin; an observed "not invokable" cannot be tied to a version, so the entry stays detail-only`
      if (definition.harnessId === 'pi')
        return `Pi extension-backed entry absent (proven at pin ${pin}: no extension package installed, no Harness audit; G14 "explicitly absent")`
      return `explicit subagent invocation observed as absent at pin ${pin} — proven not invokable at this pin, not merely unobserved`
  }
}

const refusedAction = (reason: string): ChatInputEntryAction => ({
  // The type requires an action even for disabled entries; this one is
  // inert by construction: it closes over nothing but its reason string —
  // not the reader, not the gateway, not a location — so no selection can
  // turn it into a business call, on a fresh or a stale target. chat-api r3
  // hands the selection-time ChatLocation to every invoke action; this one
  // has arity 0, which proves structurally that the location cannot be
  // forwarded anywhere. A disabled entry is detail only; executing it
  // refuses, it never degrades into a pseudo-call.
  kind: 'invoke',
  execute: async (): Promise<ChatActionResult> => ({
    status: 'refused',
    message: `Ordessa does not invoke this entry (detail only): ${reason}`,
  }),
})

const compareDefinitions = (a: EffectiveDefinition, b: EffectiveDefinition): number =>
  a.harnessId.localeCompare(b.harnessId)
  || a.origin.localeCompare(b.origin)
  || a.nativeName.localeCompare(b.nativeName)
  || a.definitionId.localeCompare(b.definitionId)
  || a.revision - b.revision

interface CollisionContext {
  /** definitions sharing this nativeName within the asked location */
  readonly duplicateNames: ReadonlyMap<string, number>
  readonly existing: readonly ExistingName[]
}

function collisionReason(definition: EffectiveDefinition, ctx: CollisionContext): string | undefined {
  const name = definition.nativeName
  if (RESERVED_NATIVE_NAMES.includes(name))
    return `NATIVE_NAME_CONFLICT: "${name}" is a reserved native name for this target; the item stays detail-only (FR10)`
  const claimants = ctx.duplicateNames.get(name) ?? 0
  if (claimants > 1)
    return `NATIVE_NAME_CONFLICT: "${name}" is claimed by ${claimants} definitions at this location; Ordessa never lets registration or display order pick a winner — every claimant is detail-only (FR10/US5)`
  const clash = ctx.existing.find(entry => entry.name === name)
  if (clash)
    return `NATIVE_NAME_CONFLICT: "${name}" is already owned by ${clash.kind === 'slash-command' ? 'an existing slash command' : 'an existing Skill'}; this entry is detail-only, never last-registered-wins (FR10)`
  return undefined
}

function entryFor(
  definition: EffectiveDefinition,
  order: number,
  deps: SubagentInputSourceDeps,
  collision: string | undefined,
): ChatInputEntry {
  const evidence = evidenceReason(definition)
  const gateReason = collision ?? evidence
    ?? (definition.state.invokable === 'yes' && deps.gateway === null
      ? `invokability is proved for ${definition.harnessId}, but no invocation owner (InvokeGateway) is wired into this build; detail only — a ready entry without an executor would fake capability (C4)`
      : undefined)
  const id = `${definition.origin === 'managed' ? 'managed' : 'native'}/${definition.harnessId}/${definition.definitionId}@r${definition.revision}`
  const title = `${definition.displayName} · ${definition.harnessId}`
  const description = `${originLabel(definition.origin)} · ${definition.description || '(no description)'}`
  if (gateReason !== undefined) {
    return {
      id, title, description, groupId: GROUP.id, order, surfaces: SURFACES,
      availability: { kind: 'disabled', reason: gateReason },
      action: refusedAction(gateReason),
    }
  }
  // chat-api r3 (contract.ts `invoke`): Chat passes the *selection-time*
  // ChatLocation into execute. That argument is the only location this path
  // may trust — the location the entry was queried for is deliberately not
  // even in this scope, so re-capturing it is not a mistake one can make here.
  // The stale-target rule (input-contracts §1, G17) is therefore evaluated
  // against the target the user actually picked.
  const execute = async (location: ChatLocation): Promise<ChatActionResult> => {
    // Re-validate first: a stale target yields `unavailable` without any
    // business call — the reader is not touched and the gateway is not
    // entered (input-contracts §1).
    if (!deps.isLocationCurrent(location)) return { status: 'unavailable' }
    if (deps.gateway === null) return { status: 'unavailable' } // unreachable: 'ready' requires a gateway
    return deps.gateway.invoke({ location, definition })
  }
  return {
    id, title, description, groupId: GROUP.id, order, surfaces: SURFACES,
    availability: { kind: 'ready' },
    action: { kind: 'invoke', execute },
  }
}

const BUDGET_DIAGNOSTIC_ID = 'budget/diagnostic'

function applyBudget(entries: readonly ChatInputEntry[], limits: InputBudget | undefined): {
  readonly kept: ChatInputEntry[]
  readonly dropped: ChatInputEntry[]
} {
  const maxEntries = limits?.maxEntries ?? Number.POSITIVE_INFINITY
  const maxChars = limits?.maxDescriptionChars ?? Number.POSITIVE_INFINITY
  const kept: ChatInputEntry[] = []
  const dropped: ChatInputEntry[] = []
  let usedChars = 0
  for (const entry of entries) {
    const cost = entry.description?.length ?? 0
    if (kept.length >= maxEntries || usedChars + cost > maxChars) { dropped.push(entry); continue }
    kept.push(entry)
    usedChars += cost
  }
  return { kept, dropped }
}

function budgetDiagnostic(dropped: readonly ChatInputEntry[]): ChatInputEntry {
  const reason = `input budget reached; ${dropped.length} subagent entr${dropped.length === 1 ? 'y is' : 'ies are'} not shown: ${dropped.map(entry => entry.id).join(', ')}`
  return {
    id: BUDGET_DIAGNOSTIC_ID,
    title: `${dropped.length} subagent entr${dropped.length === 1 ? 'y' : 'ies'} hidden by the input budget`,
    description: 'caller-supplied max entry count or description budget reached; drops are always reported here, never silent',
    groupId: GROUP.id,
    order: Number.MAX_SAFE_INTEGER,
    surfaces: SURFACES,
    availability: { kind: 'disabled', reason },
    action: refusedAction(reason),
  }
}

/** The Chat input source for native subagent definitions. Stateful only in
 * one respect: at most the newest query may publish results (see query()). */
export function createSubagentInputSource(
  reader: SubagentDefinitionReader,
  deps: SubagentInputSourceDeps,
): ChatInputSource {
  let querySeq = 0
  /** Entries last published by the newest non-stale query. A late resolution
   * of a superseded query returns this unchanged value, so the shared record
   * it lands in keeps its content — a response computed for an old location
   * can never write the current result (G17 counter-example column, ux.md
   * §交互验收 "切换 Server/Profile/项目后旧异步结果不落到新目标"). */
  let publishedEntries: readonly ChatInputEntry[] = []

  return {
    id: SUBAGENT_INPUT_SOURCE_ID,
    title: 'Native subagents',
    groups: [GROUP],
    async query(request: ChatInputQuery): Promise<readonly ChatInputEntry[]> {
      const mySeq = ++querySeq
      let definitions: readonly EffectiveDefinition[]
      let existing: readonly ExistingName[]
      try {
        ;[definitions, existing] = await Promise.all([
          reader.readEffective(request.location, request.signal),
          deps.existingNames.names(request.location, request.signal),
        ])
      } catch (error) {
        // An aborted or superseded query is a UI cancellation, never a source
        // error: the previous entries stand (registry abort semantics).
        if (request.signal.aborted || mySeq !== querySeq) return publishedEntries
        throw error
      }
      if (request.signal.aborted || mySeq !== querySeq) return publishedEntries
      const duplicateNames = new Map<string, number>()
      for (const definition of definitions)
        duplicateNames.set(definition.nativeName, (duplicateNames.get(definition.nativeName) ?? 0) + 1)
      const sorted = [...definitions].sort(compareDefinitions)
      const built = sorted.map((definition, index) => entryFor(
        definition, index + 1, deps, collisionReason(definition, { duplicateNames, existing }),
      ))
      const needle = request.query.trim().toLowerCase()
      const filtered = needle === ''
        ? built
        : built.filter(entry => `${entry.title} ${entry.description ?? ''} ${entry.id}`.toLowerCase().includes(needle))
      const { kept, dropped } = applyBudget(filtered, deps.limits)
      publishedEntries = dropped.length > 0 ? [...kept, budgetDiagnostic(dropped)] : kept
      return publishedEntries
    },
  }
}

/** Read-only detail payload — a first-class output, not a degraded invoke
 * (ux.md: "只给详情/管理入口"). Pure over one definition; the future Settings
 * UI (T09) renders the same shape the menu's disabled entries carry. */
export interface SubagentDefinitionDetail {
  readonly definitionId: string
  readonly revision: number
  readonly nativeName: string
  readonly displayName: string
  readonly description: string
  readonly harnessId: string
  readonly origin: DefinitionOrigin
  /** The four evidence facts pass through verbatim: the detail view keeps
   * `unknown` visible instead of rendering it as success or absence. */
  readonly state: DefinitionState
  readonly refusal?: EffectiveDefinition['refusal']
  /** Evidence-layer verdict only; collisions and gateway wiring are query
   * context, evaluated by the input source, never guessed here. */
  readonly usableFromChat: boolean
  readonly detailOnlyReason: string
  readonly surfaces: readonly ChatInputSurface[]
}

export function describeDefinition(definition: EffectiveDefinition): SubagentDefinitionDetail {
  const evidence = evidenceReason(definition)
  return {
    definitionId: definition.definitionId,
    revision: definition.revision,
    nativeName: definition.nativeName,
    displayName: definition.displayName,
    description: definition.description,
    harnessId: definition.harnessId,
    origin: definition.origin,
    state: definition.state,
    ...(definition.refusal !== undefined ? { refusal: definition.refusal } : {}),
    usableFromChat: evidence === undefined,
    detailOnlyReason: evidence ?? `invokability is proved for ${definition.harnessId}; Chat action availability still requires a live invocation owner and location revalidation at selection time`,
    surfaces: SURFACES,
  }
}
