/**
 * The one place effect wording is produced.
 *
 * Views must not compose their own sentences about what happened to a Skill:
 * every claim goes through `effectText()`, which grades the level the backend
 * reported with `attest()` before wording it. Consequences the G14/G16
 * counterexamples depend on:
 *
 * * `projected` words as "已投放，未确认装载" (ux.md §原生发现和错误) — a
 *   projection digest is not a load observation, so no surface can call it
 *   "已装载";
 * * a claimed `loaded`/`used` without its own `load_observation` /
 *   `invocation_event` proof degrades to "装载状态未知";
 * * nothing in this table ever writes 已启用: 启用/禁用/继承 belongs to a
 *   *decision* (`decisionText`), and a decision is a different column from the
 *   effect. A projection field alone therefore cannot produce either word.
 */
import { attest, type EvidenceLevel } from '../../contracts/src/evidence'
import type { Decision } from '../../contracts/src/skills'

export interface EvidenceFields {
  evidence: string
  proofs: readonly string[]
}

export function effectText(fields: EvidenceFields): string {
  const level = attest(fields.evidence, fields.proofs)
  return describeEvidence(level)
}

/** Wording for an already-graded level. Split out so `unknown` can be reached
 * only through `attest()`. */
export function describeEvidence(level: EvidenceLevel): string {
  switch (level) {
    case 'used': return '已调用（有独立调用事件证据）'
    case 'loaded': return '已装载（Harness 有装载观察证据）'
    case 'projected': return '已投放，未确认装载'
    case 'selected': return '已选择，尚未投放'
    case 'stored': return '已保存'
    default: return '装载状态未知'
  }
}

/** The graded level a surface may display — always read this instead of the
 * raw `evidence` field. */
export function provableLevel(fields: EvidenceFields): EvidenceLevel {
  return attest(fields.evidence, fields.proofs)
}

export function decisionText(decision: Decision): string {
  switch (decision) {
    case 'enable': return '启用'
    case 'disable': return '禁用'
    default: return '继承'
  }
}

/** Where a decision came from, as the row must say it (ux.md: 后者给出决定它
 * 的范围及版本). Harness `null` is the "所有 Harness" layer. */
export function scopeText(scope: { layer: string; scopeId: string | null; harnessId: string | null; revision: number | null }): string {
  const layer = scope.layer === 'user-global' ? '全局默认'
    : scope.layer === 'project' ? `项目 ${scope.scopeId ?? '?'}`
    : scope.layer === 'profile' ? `Profile ${scope.scopeId ?? '?'}`
    : scope.layer === 'session' ? '本次会话'
    : scope.layer === 'mandatory' ? '平台强制规则'
    : '无人决定'
  const harness = scope.harnessId === null ? '所有 Harness' : scope.harnessId
  const revision = scope.revision === null ? '' : ` · r${scope.revision}`
  return `${layer} / ${harness}${revision}`
}

/** Ownership badges (ux.md: 公共/项目/Profile 专用归属清楚标记). */
export function originBadge(origin: 'public' | 'project' | 'profile'): string {
  return origin === 'public' ? '公共库' : origin === 'project' ? '项目专用' : 'Profile 专用'
}

/**
 * 最终结果, worded only from the resolver's own fields.
 *
 * The vocabulary is deliberately not 启用/禁用 (that is a *decision*, the
 * 本层设置 column): here the row says whether it is in the effective set and
 * which scope + revision put it there or took it out. A projection field can
 * never contribute to this sentence.
 */
export function resultText(resolved: { selectedBy: ScopeFields; excludedBy: ScopeFields | null } | null): string {
  if (resolved === null) return '最终结果待解析'
  if (resolved.excludedBy !== null) return `不在有效集合（${scopeText(resolved.excludedBy)} 决定）`
  if (resolved.selectedBy.layer === 'none') return '不在有效集合（无人选择）'
  return `在有效集合（${scopeText(resolved.selectedBy)} 决定）`
}

interface ScopeFields {
  layer: string
  scopeId: string | null
  harnessId: string | null
  revision: number | null
}

export const nativeLocationText: Record<'project' | 'user-global' | 'harness-builtin' | 'unknown', string> = {
  project: '项目目录',
  'user-global': '用户全局目录',
  'harness-builtin': 'Harness 自带',
  unknown: '位置未知',
}

/**
 * What Ordessa can do about a natively discovered item.
 *
 * `null` (the harness never said) is grouped with `false`: an unproven ability
 * is not an ability, and the surface must not offer a switch whose effect it
 * cannot honour (US5, G11). Only a positive `true` may promise masking.
 */
export function nativeMaskText(canBeMasked: boolean | null): string {
  if (canBeMasked === true) return '可由 Ordessa 精确屏蔽'
  if (canBeMasked === false) return '无法由 Ordessa 关闭'
  return '无法由 Ordessa 关闭（该 Harness 未声明可屏蔽能力）'
}
