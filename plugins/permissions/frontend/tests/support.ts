// Shared fixtures: an in-memory fake transport (no network) and sample facts.
import type {
  PermissionsApprovalTransport, PermissionsApprovalView, PermissionsDecideParams, PermissionsDecideResult,
  PermissionsQueryParams, PermissionsQueryResult, PermissionsApprovalStateRecord,
} from '../src/contract'
import type { ChatLocation } from '@extensions/ordessa.chat-api/contract.js'

type Handlers = {
  decide?: (params: PermissionsDecideParams) => PermissionsDecideResult | Promise<PermissionsDecideResult>
  query?: (params: PermissionsQueryParams) => PermissionsQueryResult | Promise<PermissionsQueryResult>
}

export class FakeApprovalTransport implements PermissionsApprovalTransport {
  readonly calls: { method: 'decide' | 'query'; params: Record<string, unknown> }[] = []
  constructor(public script: Handlers = {}) {}
  async decide(params: PermissionsDecideParams): Promise<PermissionsDecideResult> {
    this.calls.push({ method: 'decide', params: { ...params } })
    if (!this.script.decide) return { outcome: 'unknown', reason: 'no scripted decide result' }
    return await this.script.decide(params)
  }
  async query(params: PermissionsQueryParams): Promise<PermissionsQueryResult> {
    this.calls.push({ method: 'query', params: { ...params } })
    if (!this.script.query) return { outcome: 'unknown', reason: 'no scripted query result', grantsExecution: false }
    return await this.script.query(params)
  }
}

export const sessionLocation: ChatLocation = {
  kind: 'session', connectionId: 'c1', sessionId: 's1', contextRevision: 1,
}

export const openView = (overrides: Partial<PermissionsApprovalView> = {}): PermissionsApprovalView => ({
  approvalId: 'approval_abc',
  sessionId: 's1',
  nativeRequestId: 'native-1',
  requestId: 'op-key-1',
  version: 1,
  status: 'open',
  decision: null,
  scope: null,
  nativeReceipt: { kind: 'unknown' },
  display: {
    operationCategory: '写入文件',
    targetSummary: '<目标已脱敏：项目内路径>',
    policySource: 'Profile 意图 + 组织上限',
    selectableScopes: [{ kind: 'once' }, { kind: 'bounded', until: 'session_end', environmentId: null }],
  },
  refusal: null,
  ...overrides,
})

export const stateRecord = (overrides: Partial<PermissionsApprovalStateRecord> = {}): PermissionsApprovalStateRecord => ({
  approvalId: 'approval_abc', sessionId: 's1', executionId: 'e1', version: 2,
  state: 'settled', decision: 'allow', scope: { kind: 'once' },
  requestId: 'op-key-1', nativeRequestId: 'native-1', ...overrides,
})

export const queryResolved = (
  state: Partial<PermissionsApprovalStateRecord>,
  receipt: { nativeRequestId: string; approvalId: string; confirmed: boolean; observedAt: string | null } | null = null,
): PermissionsQueryResult => {
  const full = stateRecord(state)
  return {
    outcome: 'resolved',
    state: full,
    receipt,
    grantsExecution: receipt?.confirmed === true && receipt.observedAt != null,
  }
}
