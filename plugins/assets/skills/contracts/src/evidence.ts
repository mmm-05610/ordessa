/**
 * Effect levels: the honest ladder between `stored` and `used`.
 *
 * TypeScript mirror of `src/ordessa_skills/api/evidence.py`; the names of the
 * six levels, the ladder order and the per-level minimum proof are the same
 * facts, deliberately re-declared here instead of imported across the process
 * boundary (the desktop never sees Python types, only the wire view models).
 * Authoritative text: docs/design/skills-v2/contracts.md §"Harness 配置贡献"
 * and docs/design/skills-v2/verification.md G16.
 *
 * The point of grading in the front end too: a view must not be able to render
 * a stronger claim than the proofs it was actually handed. A digest match of a
 * projected tree proves `projection_digest`, which is at most `projected` —
 * never "loaded", never "used" (ux.md §原生发现和错误: 没有独立装载证据时写
 * "已投放，未确认装载").
 */

export type EvidenceLevel = 'stored' | 'selected' | 'projected' | 'loaded' | 'used' | 'unknown'

/** The five provable levels, ordered strongest-first. */
export const EVIDENCE_LADDER = ['used', 'loaded', 'projected', 'selected', 'stored'] as const
/** Every level name in the domain, strongest-first, `unknown` last. */
export const EVIDENCE_LEVELS = [...EVIDENCE_LADDER, 'unknown'] as const

/** A harness without a capability statement never displays above this. */
export const UNCONFIRMED = 'unconfirmed'

/** The proof names a view may receive; these are opaque tokens from the
 * backend's capability matrix, never derived on the client. */
export type ProofToken = 'content_digest' | 'assignment_decision' | 'projection_digest' | 'load_observation' | 'invocation_event'

/** The minimum independent proof each level needs before it may be reported. */
export const PROOF_REQUIREMENTS: Readonly<Record<Exclude<EvidenceLevel, 'unknown'>, ProofToken>> = {
  stored: 'content_digest',
  selected: 'assignment_decision',
  projected: 'projection_digest',
  loaded: 'load_observation',
  used: 'invocation_event',
}

const isLevel = (value: string): value is EvidenceLevel => (EVIDENCE_LEVELS as readonly string[]).includes(value)

/** The strongest provable level among `levels`, or `unknown`. */
export function highest(...levels: readonly string[]): EvidenceLevel {
  for (const candidate of EVIDENCE_LADDER) {
    if (levels.includes(candidate)) return candidate
  }
  return 'unknown'
}

/**
 * Grade one claimed effect level against the proofs actually held.
 *
 * A level stands only while its own minimum proof is present; anything else
 * degrades to `unknown` — the ladder never moves on implied or borrowed
 * evidence. This is the single funnel every view label goes through, so no
 * component can render "已装载"/"已启用" from a projection field alone.
 */
export function attest(level: string | null | undefined, proofs: readonly string[] = []): EvidenceLevel {
  if (typeof level !== 'string' || !isLevel(level) || level === 'unknown') return 'unknown'
  const required = PROOF_REQUIREMENTS[level]
  return proofs.includes(required) ? level : 'unknown'
}
