/**
 * The `SkillChoice` contribution DTO (docs/design/skills-v2/contracts.md
 * §Chat 可消费的贡献, ux.md §Chat `/` 与 `+`, verification.md G17).
 *
 * Skills does not own a Chat menu component: it hands Chat one structured row
 * per Skill for the existing `/` and `+` surfaces. Two rules shape these types:
 *
 * * **The menu reads the CURRENT confirmed effective snapshot only.** A
 *   snapshot therefore carries the `runtimeGeneration` its set was confirmed
 *   for (data-model.md `SkillSnapshot`), so a late reply from an old runtime
 *   generation can be recognised as stale instead of repainting a newer menu.
 *   An unconfirmed read is `null`, never an empty list — "we do not know" must
 *   not render as "nothing is installed" (G06/G09 discipline).
 * * **`explicitInvocationSupported` is a proved fact or it is false.** The
 *   backend declares `skills.invokeDescriptor` `unknown` for pi, codex and
 *   claude-code (`src/ordessa_skills/wire.py`,
 *   `harness_adapters/capabilities.py`), so no row may promise a call. An
 *   unproven ability is not an ability (`effect-text.ts` `nativeMaskText` uses
 *   the same rule for masking).
 */
import type { InvokeDescriptor, OriginScope } from './skills'

/** Namespaced source/group identity for the Skills input contribution. The
 * Chat registry rejects a duplicate source id, so these are constants rather
 * than per-call strings. */
export const SKILLS_CHAT_SOURCE_ID = 'ordessa.skills.input'
export const SKILLS_CHAT_SOURCE_TITLE = 'Skills'
/** Managed rows that the current generation has confirmed. */
export const SKILLS_CHAT_GROUP_EFFECTIVE = 'ordessa.skills.effective'
/** Rows the profile layer chose but the running generation has not applied. */
export const SKILLS_CHAT_GROUP_PENDING = 'ordessa.skills.pending'
/** Rows the Harness or the project provides natively: read-only observations. */
export const SKILLS_CHAT_GROUP_NATIVE = 'ordessa.skills.native'
/** The slash namespace Skills falls back to when a name is taken or unknown;
 * a system command name is never overwritten (contracts.md §Chat 可消费的贡献). */
export const SKILLS_SLASH_PREFIX = '/skills:'

/** Ownership as the menu shows it: the resolver's ownership plus the native
 * category, which is an observation rather than managed content (FR10). */
export type SkillChoiceOrigin = OriginScope | 'native'

/** One layer's decision as the backend resolver reported it
 * (`assignments/resolver.py` `selectedBy`/`excludedBy` entries: layer token +
 * scope identity + the row version read in the resolution transaction).
 * The raw backend layer spellings (`user_global_any`, `session_override`,
 * `mandatory_policy`, …) are carried verbatim so the provenance a row shows
 * can always be traced back to a wire field, never to a client guess. */
export interface SkillChoiceDecision {
  layer: string
  scopeKind: string | null
  scopeId: string | null
  harnessId: string | null
  rowVersion: number | null
}

/** One diagnostic from the resolve answer itself
 * (`assignments/resolver.py` `Resolution.diagnostics`: `mandatory_policy_unavailable`,
 * `mandatory_policy_applied`, `other_harness_scope`, `pending_until_next_send`, …).
 * Diagnostics are UI states, never filtered out (contracts.md
 * 不可用不以静默过滤达成"成功"). */
export interface SkillSnapshotDiagnostic {
  code: string
  message: string
  assetId: string | null
}

/** One row offered to Chat. Field order follows contracts.md §Chat 可消费的
 * 贡献 (`targetSession, assetId, revision, nativeName, description, origin,
 * state, explicitInvocationSupported, invokeDescriptor?`) so the Z2/C0
 * transport wiring is a mapping, not a rename. */
export interface SkillChoice {
  /** The session this snapshot was confirmed for; identity is
   * connectionId(+serverInstanceId)+sessionId (chat-api `ChatLocation`), never
   * a guessed title. A row whose target differs from the request is stale. */
  targetSession: string
  assetId: string
  /** The revision the resolution pinned; null when nothing pinned one. */
  revision: number | null
  nativeName: string
  description: string | null
  origin: SkillChoiceOrigin
  /** 调用状态 wording, produced only from the resolver + evidence fields
   * (`effect-text.ts`), so a projection can never read as a load. */
  state: string
  /** True only when a verified explicit-invocation route exists. `unknown`
   * from the backend maps to false here — the menu must not offer what the
   * brand cannot honour (FR13, US6). */
  explicitInvocationSupported: boolean
  /** Present only when `explicitInvocationSupported` is true; a `browse-only`
   * descriptor is not an invocation route. */
  invokeDescriptor?: InvokeDescriptor
  /** The profile layer chose this but the running generation has not applied
   * it: showable as an expected row, never submittable (ux.md §Chat). Real
   * data drives this from the resolve answer (session-override layer /
   * `pending_until_next_send` diagnostic), not from a client-side guess. */
  pendingUntilNextSend?: boolean
  /** The layer that switched this Skill on, verbatim from the resolver's
   * `selectedBy` (provenance display; absent on rows built without a
   * resolver answer). */
  selectedBy?: SkillChoiceDecision | null
  /** The layer that switched it off again; the resolver's `excludedBy`
   * (`null` + `absentReason` on the wire means "not in the set, nobody
   * disabled it" — inherit and disable stay distinct, G06). */
  excludedBy?: SkillChoiceDecision | null
  /** The effect level the backend can prove for this item
   * (`capabilityEvidence.effect`, one of the `evidence.py` ladder names;
   * absence is `unknown`, never an implied level). */
  evidenceLevel?: string | null
}

/** The current confirmed effective snapshot for one session target. */
export interface SkillsChatSnapshot {
  targetSession: string
  /** Monotonic runtime generation the effective set was confirmed against.
   * A read whose generation is lower than the one already confirmed for the
   * same session is stale and must not repaint the menu (G17). `null` is
   * "the answer carried no generation" — unknown, never 0: an unknown
   * generation cannot move the confirmed floor and cannot support a
   * "ready in this session" claim. */
  runtimeGeneration: number | null
  /** The Harness brand of the target; displayed as 品牌. */
  harnessId: string | null
  projectId: string | null
  skills: readonly SkillChoice[]
  /** The slash names Chat's command catalog already owns for this target.
   * `null`/absent means the catalog could not be read: the name space is then
   * unknown, and an unknown collision is never resolved by taking the bare
   * name (contracts.md §Chat 可消费的贡献). */
  systemCommandNames?: readonly string[] | null
  /** Diagnostics the resolve answer carried (`Resolution.diagnostics`, and
   * anything the read path itself had to qualify). They render as explicit
   * notice rows — an unavailable layer is said, not filtered (G06 discipline). */
  diagnostics?: readonly SkillSnapshotDiagnostic[]
}

export interface SkillsChatReadTarget {
  /** The session key the source was queried for; the snapshot must echo it in
   * `targetSession` or the source drops it. */
  sessionKey: string
  harnessId: string | null
  projectId: string | null
  signal: AbortSignal
}

/**
 * The read port the Skills chat source consumes. Implementations must return
 * the *confirmed* snapshot of the running session (the apply-then-confirm path
 * of FR08/G18), never a freshly resolved preview: a preview is what the user
 * chose, not what the runtime can call. `null` says "not confirmed".
 */
export interface SkillsChatSnapshotPort {
  read(target: SkillsChatReadTarget): Promise<SkillsChatSnapshot | null>
}

/** The session-owner invocation route (Z2/C0 gap: no ACP explicit-invoke route
 * is published today). Supplied by the integrator only when the brand really
 * has one; the source never synthesises it. */
export type SkillsChatInvokePort = (request: {
  readonly targetSession: string
  readonly choice: SkillChoice
  readonly signal: AbortSignal
}) => Promise<{ readonly status: 'accepted' } | { readonly status: 'refused'; readonly message: string } | { readonly status: 'unavailable' }>

/** True only for a proved invocation route: the flag, a `kind: 'invoke'`
 * descriptor and an injected session-owner invoker all have to agree. */
export function invocationProven(
  choice: SkillChoice,
  invoker: SkillsChatInvokePort | null | undefined,
): boolean {
  if (invoker === null || invoker === undefined) return false
  if (choice.explicitInvocationSupported !== true) return false
  return choice.invokeDescriptor?.kind === 'invoke'
    && choice.invokeDescriptor.assetId === choice.assetId
    && (choice.revision === null || choice.invokeDescriptor.revision === choice.revision)
}

/** The outcome of choosing the slash form for a Skill name. */
export interface SkillSlashName {
  /** The command text to insert; empty when nothing may be inserted. */
  readonly text: string
  /** True when the Skills namespace had to be applied. */
  readonly namespaced: boolean
  /** True when even the namespaced form is taken: the row is read-only and no
   * text is offered at all — a system command is never displaced. */
  readonly refused: boolean
}

const taken = (name: string, owned: readonly string[]): boolean =>
  owned.includes(name) || owned.includes(`/${name}`)

/**
 * Slash naming with a hard no-overwrite rule.
 *
 * * the bare `/<name>` is offered only when the catalog proves the name free;
 * * a known collision falls back to `/skills:<name>`;
 * * an unreadable catalog (`owned === null`) also falls back — unknown is not
 *   "free";
 * * a collision on the namespaced form refuses the command text entirely
 *   instead of registering a second command under a taken id.
 */
export function skillSlashName(nativeName: string, owned: readonly string[] | null | undefined): SkillSlashName {
  const namespacedText = `${SKILLS_SLASH_PREFIX}${nativeName}`
  if (owned === null || owned === undefined) return { text: namespacedText, namespaced: true, refused: false }
  if (!taken(nativeName, owned)) return { text: `/${nativeName}`, namespaced: false, refused: false }
  // `owned` may list names with or without the leading slash; both spellings of
  // the namespaced form are checked before the row gives up on a command text.
  if (owned.includes(namespacedText) || owned.includes(`skills:${nativeName}`)) return { text: '', namespaced: true, refused: true }
  return { text: namespacedText, namespaced: true, refused: false }
}
