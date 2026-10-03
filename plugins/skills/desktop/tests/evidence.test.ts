import { describe, expect, it } from 'vitest'
import {
  EVIDENCE_LADDER, EVIDENCE_LEVELS, PROOF_REQUIREMENTS, attest, highest,
} from '../../contracts/src/evidence'
import { effectText, provableLevel, resultText } from '../src/effect-text'

/**
 * G16 as a front-end gate: the ladder has six distinct levels and every label
 * goes through the grader, so a view cannot out-claim its proofs. The names are
 * the mirror of `src/ordessa_skills/api/evidence.py` (LEVELS/LADDER/
 * PROOF_REQUIREMENTS); the Python suite owns the backend half of the mirror.
 */
describe('evidence ladder mirrors the six-level contract', () => {
  it('keeps the six levels distinct, with no USED=UNKNOWN alias', () => {
    expect(EVIDENCE_LEVELS).toEqual(['used', 'loaded', 'projected', 'selected', 'stored', 'unknown'])
    expect(EVIDENCE_LADDER).toEqual(['used', 'loaded', 'projected', 'selected', 'stored'])
    expect(new Set(EVIDENCE_LEVELS).size).toBe(6)
    expect(Object.keys(PROOF_REQUIREMENTS).sort()).toEqual(['loaded', 'projected', 'selected', 'stored', 'used'])
    expect(PROOF_REQUIREMENTS.projected).toBe('projection_digest')
    expect(PROOF_REQUIREMENTS.loaded).toBe('load_observation')
    expect(PROOF_REQUIREMENTS.used).toBe('invocation_event')
  })

  it('highest() picks the strongest provable level and defaults to unknown', () => {
    expect(highest('stored', 'projected', 'loaded')).toBe('loaded')
    expect(highest('stored', 'selected')).toBe('selected')
    expect(highest('nonsense')).toBe('unknown')
    expect(highest()).toBe('unknown')
  })

  it('attest() degrades a borrowed claim instead of honouring it', () => {
    expect(attest('projected', ['projection_digest'])).toBe('projected')
    // A projection digest is not a load observation: the claim collapses.
    expect(attest('loaded', ['projection_digest'])).toBe('unknown')
    expect(attest('used', ['projection_digest', 'load_observation'])).toBe('unknown')
    expect(attest('loaded', ['projection_digest', 'load_observation'])).toBe('loaded')
    expect(attest('used', ['invocation_event'])).toBe('used')
    expect(attest('stored', [])).toBe('unknown')
    expect(attest('unknown', ['invocation_event'])).toBe('unknown')
    expect(attest(undefined, ['content_digest'])).toBe('unknown')
  })
})

/** The wording funnel: which sentence each graded level is allowed to say. */
describe('effect wording', () => {
  it('words a projection as delivered-but-unconfirmed, never as loaded', () => {
    expect(effectText({ evidence: 'projected', proofs: ['projection_digest'] })).toBe('已投放，未确认装载')
    const words = effectText({ evidence: 'projected', proofs: ['projection_digest'] })
    expect(words).not.toContain('已装载')
    expect(words).not.toContain('已启用')
    expect(words).not.toContain('已调用')
  })

  it('refuses to say 已装载 when only the projection field is filled in', () => {
    // The whole point of grading in the view: even a backend that overclaims
    // `loaded` without the observation is displayed as unknown.
    const overclaiming = { evidence: 'loaded', proofs: ['projection_digest'] }
    expect(provableLevel(overclaiming)).toBe('unknown')
    expect(effectText(overclaiming)).toBe('装载状态未知')
    expect(effectText(overclaiming)).not.toContain('已装载')
    // ...and the honest pair does say it.
    expect(effectText({ evidence: 'loaded', proofs: ['load_observation'] })).toContain('已装载')
  })

  it('never words an effect as an enable switch', () => {
    for (const fields of [
      { evidence: 'stored', proofs: ['content_digest'] },
      { evidence: 'selected', proofs: ['assignment_decision'] },
      { evidence: 'projected', proofs: ['projection_digest'] },
      { evidence: 'loaded', proofs: ['load_observation'] },
      { evidence: 'used', proofs: ['invocation_event'] },
      { evidence: 'used', proofs: [] },
    ]) expect(effectText(fields)).not.toContain('已启用')
  })

  it('resultText reads only the resolver fields', () => {
    expect(resultText(null)).toBe('最终结果待解析')
    expect(resultText({ selectedBy: { layer: 'none', scopeId: null, harnessId: null, revision: null }, excludedBy: null }))
      .toBe('不在有效集合（无人选择）')
    expect(resultText({
      selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 3 }, excludedBy: null,
    })).toBe('在有效集合（全局默认 / 所有 Harness · r3 决定）')
    expect(resultText({
      selectedBy: { layer: 'user-global', scopeId: null, harnessId: null, revision: 3 },
      excludedBy: { layer: 'project', scopeId: 'ordessa', harnessId: 'codex', revision: null },
    })).toBe('不在有效集合（项目 ordessa / codex 决定）')
  })
})
