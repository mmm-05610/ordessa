/**
 * The real `SkillsChatSnapshotPort`: the Chat contribution's read of the
 * confirmed effective snapshot, backed by the wire gateway.
 *
 * Q1's half of api-requests.md §R-Q1-2: until chat-api carries a generation
 * guard of its own, Skills owns the transport from the published `skills.*`
 * family onto `SkillsChatSnapshotPort`, so `chatContribution.ts` consumes
 * backend data instead of a test fake. The bound operations are the ones
 * `wire.py` declares (flat, value-shaped params — same discipline as
 * `profileGateway.ts`):
 *
 * * `skills.resolve` (`wire.py:331/407` → `service.py:361` →
 *   `resolver.py Resolution.view():145-156`) — the confirmed effective set for
 *   a target. Fields bound here: `target.{sessionRef, runtimeGeneration,
 *   harnessId, projectId}` (`resolver.py:110-117`), per-item
 *   `assetId/revision/nativeName/description/originScope/selectedBy/excludedBy`
 *   (`resolver.py:477-503`), the item's `capabilityEvidence.effect` ladder
 *   level (`resolver.py:534-555`, `api/evidence.py`), and the resolution-level
 *   `diagnostics[]` kinds `mandatory_policy_unavailable`,
 *   `mandatory_policy_applied`, `mandatory_approval_required`,
 *   `other_harness_scope` (`resolver.py:331-518`).
 * * `skills.previewEffective` (`wire.py:334/410`) — the same algorithm over
 *   session overrides; selectable via `options.method` for a draft preview.
 *   The chat menu's default stays `skills.resolve`: a preview is what the user
 *   chose, not what the running generation can call.
 * * `skills.invokeDescriptor` (`wire.py:340/415` → `service.py:398-414`) — the
 *   per-brand invocation axis. Today it truthfully answers
 *   `invocation: "unknown", browseOnly: true` for every brand, which is what
 *   keeps `explicitInvocationSupported` false without the row list lying.
 *
 * Honesty rules this file exists to keep:
 * * a typed refusal (the `error_families.py` code table) becomes a
 *   `SkillsSnapshotRefusalError` carrying code + explicit UI state — never a
 *   resolved empty list, never a swallowed null;
 * * an answer that said nothing (null response, missing `resolvedSkills`) is
 *   the same refusal class (`RESOLVE_ANSWER_MISSING`), because "the call
 *   answered nothing" is not "there is nothing";
 * * a missing `target.runtimeGeneration` normalizes to `null` (unknown), so
 *   the generation guard in `chatContribution.ts` has real data to refuse on
 *   instead of a fabricated 0;
 * * `pendingUntilNextSend` is derived from the answer's own fields — the
 *   session-override decision layer (`resolver.py:275-283`, applied per send)
 *   or a `pending_until_next_send` diagnostic — never from a test-only flag;
 * * the Chat command catalog is not a Skills wire surface, so
 *   `systemCommandNames` stays `null` (unknown) and the rows keep the
 *   `/skills:` namespace rather than assuming a free name.
 */
import type {
  SkillChoice, SkillChoiceDecision, SkillSnapshotDiagnostic,
  SkillsChatReadTarget, SkillsChatSnapshot, SkillsChatSnapshotPort,
} from '../../contracts/src/chat'
import type { OriginScope } from '../../contracts/src/skills'
import { effectText, resultText } from './effect-text'
import type { WireCaller } from './gateway'

/** The exact subset of `SKILLS_METHOD_IDS` (wire.py:422-430) this port may
 * call; the local type closes the set — a typo is a compile error. */
export const SKILLS_SNAPSHOT_WIRE_METHODS = [
  'skills.resolve', 'skills.previewEffective', 'skills.invokeDescriptor',
] as const
export type SkillsSnapshotWireMethod = typeof SKILLS_SNAPSHOT_WIRE_METHODS[number]

/** The resolver's own layer tokens (`assignments/model.py:65-79`), carried
 * verbatim into `SkillChoiceDecision.layer` so provenance is traceable to a
 * wire field. */
export const WIRE_LAYER_SESSION_OVERRIDE = 'session_override'
/** The diagnostic kind a backend says with when a chosen row only takes
 * effect on the next send (resolver diagnostics entries use `kind`). */
export const WIRE_DIAGNOSTIC_PENDING = 'pending_until_next_send'

/** The explicit UI state class a typed refusal maps to. Every refusal has a
 * state; none of them is "empty menu". */
export type SnapshotRefusalKind =
  | 'invalid-request'      // the target itself was refused (INVALID_REQUEST family)
  | 'not-found'            // a referenced id does not exist in this data root
  | 'stale-version'        // CAS / snapshot moved — retry after a re-read
  | 'foreign-target'       // the answer belongs to another target
  | 'unavailable'          // a seam this composition has not composed (§G2/§G3)
  | 'malformed-answer'     // the answer did not carry its declared shape
  | 'unknown-refusal'      // a code this table never saw: say so, do not guess

/** The code → kind table below mirrors `error_families.SKILLS_ERROR_FAMILIES`
 * (`src/ordessa_skills/error_families.py`) plus the resolver's raised codes;
 * an unmapped code is `unknown-refusal`, never silently dropped. */
const REFUSAL_KINDS: Record<string, SnapshotRefusalKind> = {
  INVALID_REQUEST: 'invalid-request', ASSET_INVALID: 'invalid-request',
  ASSIGNMENT_INVALID: 'invalid-request', SESSION_OVERRIDE_INVALID: 'invalid-request',
  SCOPE_INJECTION_MISSING: 'invalid-request', PROFILE_NOT_FOUND: 'not-found',
  ASSET_NOT_FOUND: 'not-found', WORKSPACE_UNKNOWN: 'not-found', PROFILE_UNKNOWN: 'not-found',
  SKILL_APPROVAL_MISSING: 'not-found', ASSIGNMENT_ASSET_UNKNOWN: 'not-found',
  SNAPSHOT_STALE: 'stale-version', ASSIGNMENT_VERSION_CONFLICT: 'stale-version',
  BINDING_VERSION_CONFLICT: 'stale-version',
  SNAPSHOT_TARGET_MISMATCH: 'foreign-target', RESOLUTION_FOREIGN_CONTENT: 'foreign-target',
  SKILL_NAME_COLLISION: 'foreign-target', PROFILE_HARNESS_MISMATCH: 'foreign-target',
  PROFILE_LAYER_UNAVAILABLE: 'unavailable', MANDATORY_POLICY_UNAVAILABLE: 'unavailable',
  NATIVE_TARGET_ROOT_UNAVAILABLE: 'unavailable', ASSIGNMENT_SCHEMA_UNAVAILABLE: 'unavailable',
  BINDING_CAS_UNAVAILABLE: 'unavailable', UNAVAILABLE: 'unavailable',
  // This file's own answer-shape refusals.
  RESOLVE_ANSWER_MISSING: 'malformed-answer', RESOLVE_ANSWER_MALFORMED: 'malformed-answer',
}

export class SkillsSnapshotRefusalError extends Error {
  readonly code: string
  readonly kind: SnapshotRefusalKind
  /** Retryable mirrors the family table: UNAVAILABLE is retryable, a
   * deterministic refusal is not — the UI must not offer "重试" on a target
   * the server will refuse again. */
  readonly retryable: boolean
  constructor(code: string, message: string) {
    super(`skills snapshot refused (${code}): ${message}`)
    this.name = 'SkillsSnapshotRefusalError'
    this.code = code
    this.kind = REFUSAL_KINDS[code] ?? 'unknown-refusal'
    this.retryable = this.kind === 'unavailable' || this.kind === 'stale-version'
  }
}

/** Extracts the published code from a wire rejection: the host's
 * `ServerError` carries `.code` verbatim (error_families.to_server_error);
 * a bare Error is read for a leading CODE token; anything else is an
 * unclassified refusal — still an explicit state, still never an empty list. */
export function refusalFromWire(failure: unknown): SkillsSnapshotRefusalError {
  if (failure instanceof SkillsSnapshotRefusalError) return failure
  const candidate = failure as { code?: unknown; message?: unknown } | null
  const rawCode = typeof candidate?.code === 'string' ? candidate.code : null
  const message = String(candidate?.message ?? 'wire call failed')
  const embedded = /^\s*([A-Z][A-Z0-9_]{2,})\b/.exec(message)?.[1] ?? null
  return new SkillsSnapshotRefusalError(rawCode ?? embedded ?? 'WIRE_ANSWER_UNCLASSIFIED', message)
}

export interface SkillsSnapshotGatewayOptions {
  /** `skills.previewEffective` reads the same shared algorithm over session
   * overrides; the chat menu default is the confirmed `skills.resolve`. */
  method?: Extract<SkillsSnapshotWireMethod, 'skills.resolve' | 'skills.previewEffective'>
  /** Set false to skip the per-read `skills.invokeDescriptor` probe (the
   * answer then says `unknown` honestly via a diagnostic). */
  probeInvocation?: boolean
}

// —————————————————————————— raw wire shapes (resolver.py outputs, camelCase)

interface WireScope {
  layer?: string | null
  scopeKind?: string | null
  scopeId?: string | null
  harnessId?: string | null
  rowVersion?: number | null
}

interface WireResolvedItem {
  assetId?: unknown
  revision?: unknown
  nativeName?: unknown
  description?: unknown
  originScope?: unknown
  selectedBy?: WireScope | null
  excludedBy?: WireScope | null
  capabilityEvidence?: { effect?: unknown } | null
}

interface WireDiagnostic {
  kind?: unknown
  assetId?: unknown
  reason?: unknown
  note?: unknown
  priorState?: unknown
  policyDecision?: unknown
  harnesses?: unknown
}

interface WireResolveAnswer {
  target?: {
    projectId?: string | null
    harnessId?: string | null
    profileId?: string | null
    sessionRef?: string | null
    runtimeGeneration?: number | null
  } | null
  resolvedSkills?: unknown
  excludedSkills?: unknown
  diagnostics?: unknown
}

interface WireInvokeAnswer {
  harnessId?: string
  invocation?: unknown
  browseOnly?: unknown
  reason?: unknown
}

const ORIGIN_SCOPES: readonly string[] = ['public', 'project', 'profile']

/** One wire-backed implementation of the port `chatContribution.ts` consumes. */
export function createSkillsSnapshotGateway(
  wire: WireCaller,
  options: SkillsSnapshotGatewayOptions = {},
): SkillsChatSnapshotPort {
  const method = options.method ?? 'skills.resolve'
  const probeInvocation = options.probeInvocation !== false

  const send = async (name: SkillsSnapshotWireMethod, params: Record<string, unknown>): Promise<unknown> => {
    try {
      return await wire.call(name, params)
    } catch (failure) {
      throw refusalFromWire(failure)
    }
  }

  return {
    async read(target: SkillsChatReadTarget): Promise<SkillsChatSnapshot> {
      if (target.signal.aborted) throw refusalFromWire(Error('ABORTED: snapshot read was cancelled'))
      // Flat, value-shaped params exactly as `wire.py:_resolve_params`
      // validates them (sessionRef carries the session identity the source
      // asked for; the answer must echo it — identity is never guessed).
      const params: Record<string, unknown> = { sessionRef: target.sessionKey }
      if (target.harnessId !== null) params.harnessId = target.harnessId
      if (target.projectId !== null) params.projectId = target.projectId
      const answer = parseAnswer(await send(method, params))

      const runtimeGeneration = Number.isInteger(answer.target!.runtimeGeneration)
        ? (answer.target!.runtimeGeneration as number)
        : null
      const rawDiagnostics = answer.diagnostics as WireDiagnostic[]
      const diagnostics = rawDiagnostics.map(diagnosticOf)
      const skillParams = answer.resolvedSkills as WireResolvedItem[]

      // The invocation axis is a per-brand fact the backend answers honestly
      // (`service.py:398-414`); a failed probe is said through a diagnostic,
      // never treated as "no route, confidently".
      let invocation: { supported: boolean; detail: string | null } = { supported: false, detail: 'INVOKE_DESCRIPTOR_UNKNOWN' }
      if (probeInvocation && target.harnessId !== null) {
        try {
          const probe = await send('skills.invokeDescriptor', { harnessId: target.harnessId }) as WireInvokeAnswer | null
          const supported = probe?.invocation === 'supported' && probe?.browseOnly === false
          invocation = { supported, detail: supported ? null : `INVOKE_${String(probe?.invocation ?? 'unknown').toUpperCase()}` }
        } catch (failure) {
          const refusal = refusalFromWire(failure)
          diagnostics.push({
            code: 'INVOKE_ROUTE_UNKNOWN',
            message: `显式调用入口状态未能确认（${refusal.code}）：所有行保持只读`,
            assetId: null,
          })
        }
      }

      const skills: SkillChoice[] = skillParams.map((item): SkillChoice => {
        const selectedBy = decisionOf(item.selectedBy)
        const revision = typeof item.revision === 'number' ? item.revision : null
        const evidenceLevel = typeof item.capabilityEvidence?.effect === 'string'
          ? item.capabilityEvidence.effect
          : 'unknown'
        // `resolver.py` attests `selected` together with the
        // `assignment_decision` proof (resolver.py:540); the pair travels
        // together or the display degrades through `effectText`.
        const evidenceText = effectText({
          evidence: evidenceLevel,
          proofs: evidenceLevel === 'selected' ? ['assignment_decision'] : [],
        })
        const pending = selectedBy?.layer === WIRE_LAYER_SESSION_OVERRIDE
          || rawDiagnostics.some(d => d.kind === WIRE_DIAGNOSTIC_PENDING && d.assetId === item.assetId)
        return {
          // The answer's own session echo (checked above is the one asked
          // for; anything else was already refused as a malformed answer).
          targetSession: answer.target!.sessionRef as string,
          assetId: item.assetId as string,
          revision,
          nativeName: typeof item.nativeName === 'string' ? item.nativeName : String(item.assetId),
          description: typeof item.description === 'string' && item.description.length > 0 ? item.description : null,
          origin: item.originScope as OriginScope,
          // 调用状态 wording is composed only from resolver facts (resultText +
          // the graded evidence), so a projection can never read as a load.
          state: pending
            ? `${resultText({ selectedBy: scopeFieldsOf(selectedBy, revision), excludedBy: null })} · 待本次发送生效 · 证据 ${evidenceText}`
            : `${resultText({ selectedBy: scopeFieldsOf(selectedBy, revision), excludedBy: null })} · 证据 ${evidenceText}`,
          explicitInvocationSupported: invocation.supported,
          ...(invocation.supported && revision !== null
            ? { invokeDescriptor: { assetId: item.assetId as string, revision, kind: 'invoke' as const } }
            : {}),
          pendingUntilNextSend: pending,
          selectedBy,
          excludedBy: decisionOf(item.excludedBy),
          evidenceLevel,
        }
      })

      return {
        // Echo-first: the source's target guard compares this against the
        // session it asked for; a mis-routed read is dropped there, not here.
        targetSession: String(answer.target!.sessionRef),
        runtimeGeneration,
        harnessId: answer.target!.harnessId ?? target.harnessId,
        projectId: answer.target!.projectId ?? target.projectId,
        skills,
        systemCommandNames: null,
        diagnostics,
      }
    },
  }
}

/** The snapshot port for an activation that was never given a wire gateway:
 * every read answers `null` = "not confirmed", which the menu renders as the
 * 未确认/待解析 notice — never an empty list that could read as success. */
export const unloadedSkillsSnapshotPort: SkillsChatSnapshotPort = {
  read: async () => null,
}

// —————————————————————————— normalization helpers

function parseAnswer(value: unknown): WireResolveAnswer {
  if (value === null || value === undefined) {
    throw new SkillsSnapshotRefusalError('RESOLVE_ANSWER_MISSING', 'the resolve call answered nothing')
  }
  const answer = value as WireResolveAnswer
  if (typeof answer !== 'object' || answer.target === null || answer.target === undefined
      || typeof answer.target.sessionRef !== 'string'
      || !Array.isArray(answer.resolvedSkills) || !Array.isArray(answer.diagnostics)) {
    throw new SkillsSnapshotRefusalError(
      'RESOLVE_ANSWER_MALFORMED',
      'the resolve answer lacks its declared shape (target.sessionRef / resolvedSkills / diagnostics)')
  }
  for (const item of answer.resolvedSkills as WireResolvedItem[]) {
    if (typeof item?.assetId !== 'string' || typeof item.originScope !== 'string'
        || !ORIGIN_SCOPES.includes(item.originScope)) {
      throw new SkillsSnapshotRefusalError('RESOLVE_ANSWER_MALFORMED', 'a resolvedSkills row carries no traceable assetId/originScope')
    }
  }
  return answer
}

function decisionOf(scope: WireScope | null | undefined): SkillChoiceDecision | null {
  if (scope === null || scope === undefined || typeof scope.layer !== 'string') return null
  return {
    layer: scope.layer,
    scopeKind: scope.scopeKind ?? null,
    scopeId: scope.scopeId ?? null,
    harnessId: scope.harnessId ?? null,
    rowVersion: typeof scope.rowVersion === 'number' ? scope.rowVersion : null,
  }
}

/** The `resultText`/`scopeText` DTO shape: the resolver's raw layer token
 * maps onto the display kind (`profileGateway.layerKindOf` mirror). */
function scopeFieldsOf(decision: SkillChoiceDecision | null, revision: number | null) {
  return {
    layer: wireLayerKind(decision?.layer ?? 'none'),
    scopeId: decision?.scopeKind === 'user_global' ? null : decision?.scopeId ?? null,
    harnessId: decision?.harnessId ?? null,
    revision,
  }
}

/** `assignments/model.py:65-79` → contracts `LayerKind` spellings. */
export function wireLayerKind(raw: string): string {
  if (raw.startsWith('user_global')) return 'user-global'
  if (raw.startsWith('project')) return 'project'
  if (raw === 'profile') return 'profile'
  if (raw === WIRE_LAYER_SESSION_OVERRIDE) return 'session'
  if (raw === 'mandatory_policy') return 'mandatory'
  return 'none'
}

function diagnosticOf(entry: WireDiagnostic): SkillSnapshotDiagnostic {
  const code = typeof entry.kind === 'string' ? entry.kind : 'unclassified_diagnostic'
  const assetId = typeof entry.assetId === 'string' ? entry.assetId : null
  const detail = typeof entry.reason === 'string' ? entry.reason
    : typeof entry.note === 'string' ? entry.note
      : typeof entry.policyDecision === 'string' ? `策略决定 ${entry.policyDecision}`
        : Array.isArray(entry.harnesses) ? `其他 Harness：${entry.harnesses.join('、')}`
          : null
  return { code, message: detail === null ? '解析层报告了一条诊断（无附加说明）' : detail, assetId }
}
