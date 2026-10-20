// T015 red-first: the `permissions.policy.describe` client mirror and its
// strict decoder. Written against the agreed wire contract (closed camelCase
// shape; required params none, optional principal/scope; READ-ONLY, never an
// authority). Namespace imports keep each unbuilt symbol a named failing test
// in the red run instead of a file-level import error.
import { describe, expect, it } from 'vitest'
import * as contract from '../src/contract'
import { describePayload, describeCeilingRow, describeIntentRow } from './settings-fixtures'

const exported = (name: string): unknown => (contract as Record<string, unknown>)[name]

describe('describe wire mirror (T015)', () => {
  it('exposes the permissions.policy.describe method id on the wire vocabulary', () => {
    const ids = contract.PERMISSIONS_WIRE_METHOD_IDS as Record<string, string>
    expect(ids.describe).toBe('permissions.policy.describe')
  })

  it('mirrors the exact describe parameter names: required none, optional principal/scope', () => {
    expect(exported('DESCRIBE_REQUIRED_PARAM_NAMES')).toEqual([])
    expect([...(exported('DESCRIBE_OPTIONAL_PARAM_NAMES') as string[]).slice().sort()]).toEqual(['principal', 'scope'])
  })

  it('declares the closed response-shape key sets used by the decoder', () => {
    expect([...(exported('DESCRIBE_RESPONSE_KEYS') as readonly string[])].sort())
      .toEqual(['ceilings', 'intents', 'needsReview', 'ready'])
    expect([...(exported('DESCRIBE_CEILING_ROW_KEYS') as readonly string[])].sort())
      .toEqual(['effectiveFrom', 'hardDenies', 'maximumExposure', 'policyId', 'requireApproval', 'revision', 'scope', 'signed', 'source'])
    expect([...(exported('DESCRIBE_INTENT_ROW_KEYS') as readonly string[])].sort())
      .toEqual(['desiredMode', 'harnessId', 'intentId', 'revision', 'rules', 'scope'])
    expect([...(exported('DESCRIBE_REVIEW_ROW_KEYS') as readonly string[])].sort())
      .toEqual(['index', 'reason', 'source'])
    expect([...(exported('DESCRIBE_CEILING_ENTRY_KEYS') as readonly string[])].sort())
      .toEqual(['action', 'key', 'pattern'])
    expect([...(exported('DESCRIBE_RULE_ROW_KEYS') as readonly string[])].sort())
      .toEqual(['action', 'key', 'pattern', 'priority', 'scope'])
    expect([...(exported('DESCRIBE_BRAND_MODE_KEYS') as readonly string[])].sort())
      .toEqual(['brand', 'name'])
  })
})

describe('decodeDescribeResponse: strict closed-shape decode (T015)', () => {
  const decode = (payload: unknown) => {
    const fn = exported('decodeDescribeResponse')
    expect(typeof fn).toBe('function')
    return (fn as (p: unknown) => unknown)(payload)
  }

  it('accepts the exact closed shape and keeps every fact byte-identical', () => {
    const payload = describePayload()
    const decoded = decode(payload) as any
    expect(decoded).not.toBeNull()
    expect(decoded.ready).toBe(true)
    expect(decoded.ceilings[0].policyId).toBe('org-ceiling')
    expect(decoded.ceilings[0].hardDenies[0]).toEqual({ key: 'bash', pattern: '/etc/**', action: 'deny' })
    expect(decoded.intents[0].rules[0]).toEqual({ key: 'edit', pattern: null, action: 'ask', priority: 0, scope: 'user' })
    expect(decoded.intents[0].desiredMode).toBeNull()
    expect(decoded.needsReview).toEqual([])
  })

  it('refuses unknown extra keys anywhere in the response (chosen rule: refuse, not drop)', () => {
    expect(decode({ ...describePayload(), grantsExecution: true })).toBeNull()
    expect(decode({ ...describePayload(), approvals: [] })).toBeNull()
    expect(decode(describePayload({ ceilings: [describeCeilingRow({ allowAll: true })] }))).toBeNull()
    expect(decode(describePayload({
      intents: [describeIntentRow({ rules: [{ key: 'edit', pattern: null, action: 'ask', priority: 0, scope: 'user', authorization: 'auto' }] })],
    }))).toBeNull()
    expect(decode(describePayload({ needsReview: [{ source: 's', index: 0, reason: 'r', bypass: true }] }))).toBeNull()
  })

  it('refuses missing keys, wrong types and forged authority fields', () => {
    const { ready: _ready, ...noReady } = describePayload()
    expect(decode(noReady)).toBeNull()
    expect(decode(describePayload({ ready: 'true' }))).toBeNull()
    expect(decode(describePayload({ ceilings: [describeCeilingRow({ revision: 'three' })] }))).toBeNull()
    expect(decode(describePayload({ ceilings: [describeCeilingRow({ signed: 'yes' })] }))).toBeNull()
    expect(decode(describePayload({ ceilings: [describeCeilingRow({ maximumExposure: 'yolo-mode' })] }))).toBeNull()
    expect(decode(describePayload({ ceilings: [describeCeilingRow({ hardDenies: [{ key: 'bash', pattern: null, action: 'allow' }] })] }))).toBeNull()
    expect(decode(describePayload({ ceilings: 'not-a-list' }))).toBeNull()
  })

  it('keeps desiredMode brand-scoped: null or {brand,name} only, never a bare string or a merged label', () => {
    expect(decode(describePayload({
      intents: [describeIntentRow({ desiredMode: 'plan' })],
    }))).toBeNull()
    expect(decode(describePayload({
      intents: [describeIntentRow({ desiredMode: { brand: 'claude-code', name: 'plan' } })],
    }))).not.toBeNull()
    const decoded = decode(describePayload({
      intents: [describeIntentRow({ desiredMode: { brand: 'codex', name: 'full-access' } })],
    })) as any
    // the brand-native pair is carried verbatim for the row's own brand — it is
    // never translated, and never dropped into a cross-brand vocabulary.
    expect(decoded.intents[0].desiredMode).toEqual({ brand: 'codex', name: 'full-access' })
    expect(decode(describePayload({
      intents: [describeIntentRow({ desiredMode: { brand: 'claude-code' } })],
    }))).toBeNull()
  })

  it('decodes ready:false as a fact of an unproven policy state, not as an absence', () => {
    const decoded = decode(describePayload({ ready: false })) as any
    expect(decoded).not.toBeNull()
    expect(decoded.ready).toBe(false)
  })

  it('decodes needsReview rows with their source, index and bounded single-line reason', () => {
    const decoded = decode(describePayload({
      needsReview: [{ source: 'legacy-profile:p1', index: 0, reason: '旧规则语义无法核验' }],
    })) as any
    expect(decoded.needsReview).toEqual([{ source: 'legacy-profile:p1', index: 0, reason: '旧规则语义无法核验' }])
    // a multi-line or control-character reason is a shape violation, not sanitized through
    expect(decode(describePayload({ needsReview: [{ source: 's', index: 0, reason: 'line1\nline2' }] }))).toBeNull()
    expect(decode(describePayload({ needsReview: [{ source: 's', index: -1, reason: 'r' }] }))).toBeNull()
  })
})
