// Shared fixtures for the Settings region tests. Everything here is a fake
// of the injected transport/source only — the describe payload builders are
// hand-written in the exact closed camelCase shape of the agreed wire
// contract (`permissions.policy.describe`), and
// tests/contract-consistency.test.ts asserts the TS mirrors equal the
// backend's parsed source, so these fixtures cannot silently drift.
import type { PermissionsDescribeAnswer } from '../src/contract'

export const approvalPayload = (approvalId: string, overrides: Record<string, unknown> = {}) => ({
  approvalId,
  sessionId: 's1',
  nativeRequestId: `native-${approvalId}`,
  requestId: `op-${approvalId}`,
  version: 1,
  state: 'open',
  decision: null,
  scope: null,
  receipt: null,
  refusal: null,
  display: {
    operationCategory: '写入文件',
    targetSummary: '<目标已脱敏>',
    policySource: 'Profile 意图 + 组织上限',
    selectableScopes: [{ kind: 'once' }],
  },
  ...overrides,
})

export const settledPayload = (approvalId: string, decision: 'allow' | 'deny' = 'deny', sessionId = 's2') => ({
  approvalId,
  sessionId,
  nativeRequestId: `native-${approvalId}`,
  requestId: `op-${approvalId}`,
  version: 2,
  state: 'settled',
  decision,
  scope: { kind: 'once' },
  receipt: { nativeRequestId: `native-${approvalId}`, approvalId, confirmed: true, observedAt: '2026-01-02T00:00:00Z' },
  refusal: null,
  display: {
    operationCategory: '执行命令',
    targetSummary: '<目标已脱敏：bash>',
    policySource: '组织上限',
    selectableScopes: [{ kind: 'once' }],
  },
})

export const describeCeilingRow = (overrides: Record<string, unknown> = {}) => ({
  policyId: 'org-ceiling',
  scope: 'admin',
  revision: 3,
  source: 'signed-admin',
  signed: true,
  maximumExposure: 'read',
  effectiveFrom: '2026-01-01T00:00:00+00:00',
  hardDenies: [
    { key: 'bash', pattern: '/etc/**', action: 'deny' },
    { key: 'webfetch', pattern: null, action: 'deny' },
  ],
  requireApproval: [{ key: 'edit', pattern: 'secrets/**', action: 'require-approval' }],
  ...overrides,
})

export const describeIntentRow = (overrides: Record<string, unknown> = {}) => ({
  intentId: 'legacy-profile:p1',
  revision: 1,
  harnessId: 'claude-code',
  scope: 'user',
  rules: [{ key: 'edit', pattern: null, action: 'ask', priority: 0, scope: 'user' }],
  desiredMode: null,
  ...overrides,
})

export const describeReviewRow = (overrides: Record<string, unknown> = {}) => ({
  source: 'legacy-profile:p1',
  index: 2,
  reason: '旧规则语义无法核验',
  ...overrides,
})

export const describePayload = (overrides: Record<string, unknown> = {}): Record<string, unknown> => ({
  ready: true,
  ceilings: [describeCeilingRow()],
  intents: [describeIntentRow()],
  needsReview: [],
  ...overrides,
})

/** Default ready payload with the standard org ceiling + legacy intent. */
export const readyPayload = (overrides: Record<string, unknown> = {}): Record<string, unknown> =>
  describePayload(overrides)

/** A payload with no ceiling rows at all — absence stays modelled, never "no limit". */
export const ceilingAbsentPayload = (): Record<string, unknown> =>
  describePayload({ ceilings: [] })

type ScriptedAnswer = PermissionsDescribeAnswer | { readonly throws: true }

/** Fake `permissions.policy.describe` transport: serves scripted answers in
 * order (the last one repeats), records the exact params object it received,
 * and performs no I/O. */
export class FakeDescribeTransport {
  readonly calls: Record<string, unknown>[] = []
  private index = 0
  constructor(private readonly answers: ScriptedAnswer[]) {}
  async describe(params?: { principal?: string; scope?: string }): Promise<PermissionsDescribeAnswer> {
    this.calls.push({ ...(params ?? {}) })
    const a = this.answers[Math.min(this.index, this.answers.length - 1)]
    this.index += 1
    if ('throws' in a) throw new Error('fake transport refusal')
    return a
  }
}

export const describeTransport = (payload: unknown) =>
  new FakeDescribeTransport([{ status: 'ok', payload }])

export const noProviderTransport = () => new FakeDescribeTransport([{ status: 'no-provider' }])

export const errorTransport = (code = 'POLICY_SCOPE_UNVERIFIED', message = '策略读取未能确认来源') =>
  new FakeDescribeTransport([{ status: 'error', code, message }])

export const approvalsSource = (payloads: readonly unknown[]) => ({
  load: async () => payloads,
})
