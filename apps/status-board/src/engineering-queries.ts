import { QueryClient, type WirePort, type WireResult } from '@ordessa/system-access-client'
import type { ExactQueryAccess, ExactQueryDefinition } from '@ordessa/status-board'
const definitions: readonly ExactQueryDefinition[] = [
  { method: 'engineering.capabilities', label: 'Engineering 能力' },
  { method: 'engineering.artifacts.get', label: '材料详情', parameter: { key: 'artifact_id', label: 'Artifact ID' }, fields: [{ key: 'artifact_id', label: '材料 ID' }, { key: 'kind', label: '材料类型' }, { key: 'version', label: '版本' }, { key: 'head_revision_id', label: '当前修订 ID' }] },
  { method: 'engineering.references.resolve', label: '精确引用', parameter: { key: 'ref', label: 'Ref JSON', json: true } },
  { method: 'engineering.proposals.get', label: '提案详情', fields: [{ key: 'proposal_id', label: '提案 ID' }, { key: 'digest', label: '固定内容摘要' }, { key: 'intent', label: '变化意图' }, { key: 'rationale', label: '变化理由' }, { key: 'mutations', label: '变化' }, { key: 'basis_sources', label: '依据' }, { key: 'method_ref', label: '绑定方法引用' }, { key: 'review_requirement_templates', label: '审核要求（不是审核结果）' }, { key: 'evidence_links', label: '证据' }], parameter: { key: 'proposal_ref', label: 'ProposalRef JSON', json: true } },
  { method: 'engineering.proposals.get_control', label: '提案控制记录', parameter: { key: 'proposal_ref', label: 'ProposalRef JSON', json: true } },
  { method: 'engineering.reviews.get_request', label: '原审核请求与计划（只读）', parameter: { key: 'review_id', label: 'Review ID' }, fields: [{ key: 'request', label: '原请求：state / version / fence' }, { key: 'plan', label: '原计划：digest 与完整 CheckKey' }], note: '读取原 request/plan，不创建第二份待办。JEV 或 ManualReviewCapture Artifact 是证据，不等于完整 ReviewRecord 或 Grant；dispatch completed 仅表示 ACP 完成，quarantine 不是 accepted。' },
  { method: 'engineering.changes.get', label: '变更详情', parameter: { key: 'change_id', label: 'Change ID' } },
  { method: 'engineering.notices.get', label: '告知原记录', parameter: { key: 'notice_ref', label: 'NoticeRef JSON', json: true } },
  { method: 'engineering.approvals.get', label: '批准原记录（读取不构成批准）', parameter: { key: 'approval_ref', label: 'ApprovalRef JSON', json: true } },
  { method: 'engineering.approvals.get_control', label: '批准控制原记录', parameter: { key: 'approval_ref', label: 'ApprovalRef JSON', json: true } },
  { method: 'engineering.approvals.get_intent', label: '授权意图原记录', parameter: { key: 'intent_id', label: 'Intent ID' } },
  { method: 'engineering.approvals.get_challenge', label: '确认挑战原记录（只读）', parameter: { key: 'challenge_id', label: 'Challenge ID' } },
  { method: 'engineering.approvals.list_pending', label: '待确认记录（不是 Work 列表）', parameter: { key: 'parameters', label: '分页 JSON: limit / after_challenge_id', json: true } },
  { method: 'engineering.commands.get', label: '原请求结果查询', parameter: { key: 'request_id', label: '原 Request ID' } },
  { method: 'engineering.work.get', label: '方法运行原状态（只读）', parameter: { key: 'run_id', label: 'Run ID' }, note: '读取同一后台的 MethodRun；执行 completed 不构成工程 accepted。' },
  { method: 'engineering.work.current_condition', label: '当前方法条件（只读）', parameter: { key: 'run_id', label: 'Run ID' } },
  { method: 'engineering.runs.get_wait', label: '当前等待原记录（只读）', parameter: { key: 'run_id', label: 'Run ID' } },
]
const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value)
/** Only validate the published wire envelope. Domain records stay owned by the backend. */
export function engineeringQueries(port: Pick<WirePort, 'call'>): ExactQueryAccess {
  return {
    queries: definitions,
    createQuery(method, scope, parameters) {
      const definition = definitions.find(item => item.method === method)
      if (!definition || !scope.realm_id.trim() || !scope.project_id.trim()) throw Error('请选择精确 realm/project 与查询')
      const keys = Object.keys(parameters)
      if (definition.parameter ? keys.length !== 1 || keys[0] !== definition.parameter.key : keys.length !== 0) throw Error('查询参数不匹配')
      const wireParameters = method === 'engineering.approvals.list_pending' ? parameters.parameters : parameters
      if (method === 'engineering.approvals.list_pending' && (!object(wireParameters) || Object.keys(wireParameters).sort().join(',') !== 'after_challenge_id,limit' || !Number.isInteger(wireParameters.limit) || Number(wireParameters.limit) < 1 || Number(wireParameters.limit) > 100 || !(wireParameters.after_challenge_id === null || typeof wireParameters.after_challenge_id === 'string'))) throw Error('分页要求 limit 1–100 与 after_challenge_id（字符串或 null）')
      const requestScope = Object.freeze({ ...scope })
      const args = { scope: requestScope, requestId: `board-query-${crypto.randomUUID()}`, ...(definition.parameter ? { parameters: structuredClone(wireParameters) } : {}) }
      const checked = {
        async call(): Promise<WireResult> {
          const reply = await port.call(method, args)
          if (reply.kind !== 'Accepted') return reply
          const value = reply.result
          const replyScope = value.scope
          let valid = value.contract_version === 'engineering-wire/1' && object(replyScope)
            && replyScope.realm_id === requestScope.realm_id && replyScope.project_id === requestScope.project_id
          if (method === 'engineering.capabilities') valid = valid && Array.isArray(value.queries) && object(value.supports)
          else if (method === 'engineering.commands.get') valid = valid && value.record_type === 'command_result'
            && value.request_id === parameters.request_id && typeof value.authority_id === 'string'
            && typeof value.operation_id === 'string' && typeof value.status === 'string' && 'result' in value && object(value.status_query)
            && value.status_query.method === 'engineering.commands.get' && object(value.status_query.parameters)
            && value.status_query.parameters.request_id === parameters.request_id
          else {
            const expected: Record<string, string> = { 'engineering.artifacts.get': 'Artifact', 'engineering.proposals.get': 'Proposal', 'engineering.proposals.get_control': 'ProposalControl', 'engineering.changes.get': 'Change', 'engineering.reviews.get_request': 'ReviewRequest', 'engineering.notices.get': 'ConversationNotice', 'engineering.approvals.get': 'ApprovalGrant', 'engineering.approvals.get_control': 'ApprovalControl', 'engineering.approvals.get_intent': 'AuthorizationIntent', 'engineering.approvals.get_challenge': 'ApprovalChallenge', 'engineering.approvals.list_pending': 'PendingApprovals', 'engineering.work.get': 'MethodWork', 'engineering.work.current_condition': 'CurrentCondition', 'engineering.runs.get_wait': 'RunWait' }
            valid = valid && value.query === method && typeof value.record_type === 'string' && object(value.data)
              && (!expected[method] || value.record_type === expected[method])
          }
          if (valid && method === 'engineering.reviews.get_request') valid = object(value.data) && object(value.data.request) && object(value.data.plan) && value.data.request.review_id === parameters.review_id && value.data.plan.review_id === parameters.review_id
          if (!valid) return { kind: 'Unknown', requestId: reply.requestId, reason: 'engineering-envelope-mismatch' }
          return reply
        },
      }
      return new QueryClient(checked, method)
    },
  }
}
