// migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (contracts/states.ts, verbatim)
/**
 * The Model Provider state vocabulary, frozen (specs/002-model-provider/
 * data-model.md §2). These words travel to the wire and back; the display
 * labels must never upgrade `saved`/`reachable` to "enabled" (US-3).
 */
export type ProviderConfigState = 'saved' | 'reachable'
export type Eligibility = 'ready' | 'unsupported' | 'unknown' | 'error'
export type TurnOutcome = 'pending-next-turn' | 'applied' | 'refused' | 'unknown-outcome'

export const STATE_LABELS: Record<ProviderConfigState, string> = {
  saved: '已保存',
  reachable: '最近探测通过（≠ 当前会话可使用）',
}

export const ELIGIBILITY_LABELS: Record<Eligibility, string> = {
  ready: '可在此会话下轮使用',
  unsupported: '此 Harness 不支持',
  unknown: '证据不足，未知',
  error: '目录查询失败',
}

export const TURN_OUTCOME_LABELS: Record<TurnOutcome, string> = {
  'pending-next-turn': '下轮使用',
  applied: '已应用（读回一致）',
  refused: '已拒绝',
  'unknown-outcome': '结果未知，已阻止发送',
}

/** Glyphs keep state legible without color alone (FR-NFR-3). */
export const STATE_GLYPHS: Record<ProviderConfigState, string> = { saved: '○', reachable: '◐' }
export const ELIGIBILITY_GLYPHS: Record<Eligibility, string> = {
  ready: '●', unsupported: '×', unknown: '?', error: '!',
}
