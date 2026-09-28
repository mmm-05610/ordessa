// Permissions client-side contract for the Chat approval region (T06,
// FR-04/FR-08/FR-09). This module carries types and pure functions only: the
// transport is injected by the host (no fetch/IPC lives here) and the UI is
// never an authority — every displayed state derives from backend facts
// (contracts.md §C1/§C3). The code list and the wire vocabulary mirror the
// Python side (`plugins/permissions/api/.../codes.py` RefusalCode, backend
// plugin.py method registration); tests parse those sources and fail on drift.

// ---------------------------------------------------------------------------
// Stable refusal codes (FR-09) — the TS mirror of codes.py `RefusalCode`
// ---------------------------------------------------------------------------

export const PERMISSIONS_REFUSAL_CODES = [
  'POLICY_CEILING_VIOLATION',
  'POLICY_ADAPTER_MISSING',
  'POLICY_SCOPE_UNVERIFIED',
  'PERMISSION_UNKNOWN_TOOL',
  'APPROVAL_STALE',
  'APPROVAL_NOT_ACTIONABLE',
  'APPROVAL_RESULT_UNKNOWN',
] as const

export type PermissionsRefusalCode = (typeof PERMISSIONS_REFUSAL_CODES)[number]

/** Which layer limits what, per code — the sentence below names the layer so
 * the user can tell ceiling from adapter from receipt (ux.md 文案). */
const CODE_DIAGNOSTICS: Record<PermissionsRefusalCode, { layer: string; explanation: string }> = {
  POLICY_CEILING_VIOLATION: { layer: '组织上限', explanation: '管理员上限拒绝或收窄了该操作，Profile 或会话选择不能放宽它' },
  POLICY_ADAPTER_MISSING: { layer: '策略提供者', explanation: '该 Harness 没有可用的策略适配器给出可信上限，操作维持拒绝' },
  POLICY_SCOPE_UNVERIFIED: { layer: '策略权威', explanation: '该策略记录无法验证来源或作用域，不能作为决策依据' },
  PERMISSION_UNKNOWN_TOOL: { layer: '工具词表', explanation: '该工具不在权限词表内，未知工具不会被当作“无规则”放行' },
  APPROVAL_STALE: { layer: '审批绑定', explanation: '审批已过期或不再对应当前操作，不会对旧操作补授权' },
  APPROVAL_NOT_ACTIONABLE: { layer: '执行生命周期', explanation: '该执行已结束，审批不再可操作，请发起新的操作' },
  APPROVAL_RESULT_UNKNOWN: { layer: '原生回执', explanation: '原生结果无法确认，未确认的结果永不视为允许，请先查询/恢复' },
}

export interface RefusalDisplayFields {
  readonly operationCategory: string
  readonly targetSummary: string
  readonly policySource: string
}

/** Bounded printable single-line text; control characters cannot smuggle a
 * payload into a rendered diagnostic (mirrors codes.py `_SAFE_TEXT`). */
const SINGLE_LINE = /^[^\u0000-\u001f\u007f\u0080-\u009f]{1,512}$/
const CONTROL_CHARS = /[\u0000-\u001f\u007f\u0080-\u009f]/g

export function sanitizeDiagnosticText(value: unknown, max = 512): string {
  if (typeof value !== 'string') return ''
  return value.replace(CONTROL_CHARS, '?').slice(0, max)
}

/** A human sentence naming which target/action is limited by which layer.
 * Only the shared code list and the masked display fields are rendered — the
 * backend's free-form message and any tool arguments never pass through
 * (ux.md: 对路径/参数/秘密脱敏). An unregistered code yields the generic
 * sentence and is never echoed raw. */
export function renderRefusalSentence(code: string, fields: RefusalDisplayFields): string {
  const known = (PERMISSIONS_REFUSAL_CODES as readonly string[]).includes(code)
    ? code as PermissionsRefusalCode : null
  const category = sanitizeDiagnosticText(fields.operationCategory, 128) || '该操作'
  const target = sanitizeDiagnosticText(fields.targetSummary, 128) || '该目标'
  const source = sanitizeDiagnosticText(fields.policySource, 128) || '当前策略来源'
  if (!known) return `操作「${category}」于目标「${target}」被拒绝：原因码未登记（出于安全不显示原文），维持不可操作`
  const { layer, explanation } = CODE_DIAGNOSTICS[known]
  return `操作「${category}」于目标「${target}」（权限来源：${source}）被「${layer}」层限制：${explanation}（${known}）`
}

// ---------------------------------------------------------------------------
// Wire vocabulary — 1:1 with the permissions backend plugin registration
// ---------------------------------------------------------------------------

export const PERMISSIONS_WIRE_METHOD_IDS = {
  /** `permissions.approvals.decide` (plugin.py DECIDE_METHOD). */
  decide: 'permissions.approvals.decide',
  /** `permissions.approvals.query` (plugin.py QUERY_METHOD). */
  query: 'permissions.approvals.query',
  /** `permissions.policy.describe` (describe.py POLICY_DESCRIBE_METHOD,
   * registered through plugin.py). READ-ONLY policy summary — it never
   * grants authority and produces no ruling. */
  describe: 'permissions.policy.describe',
} as const

/** Exactly the `DESCRIBE_REQUIRED_PARAMS` frozenset of the backend (none). */
export const DESCRIBE_REQUIRED_PARAM_NAMES = [] as const
/** Exactly the `DESCRIBE_OPTIONAL_PARAMS` frozenset of the backend. */
export const DESCRIBE_OPTIONAL_PARAM_NAMES = ['principal', 'scope'] as const

/** Exactly the `_DECIDE_REQUIRED` set of the backend method descriptor. */
export const DECIDE_PARAM_NAMES =
  ['requestId', 'approvalId', 'expectedVersion', 'decision', 'scope', 'sessionId'] as const
/** Exactly the `_QUERY_REQUIRED` set of the backend method descriptor. */
export const QUERY_PARAM_NAMES = ['approvalId', 'nativeRequestId'] as const

export type PermissionsDecisionValue = 'allow' | 'deny'

/** Grant scopes in the persisted wire spelling (decisions.py ApprovalScope). */
export type PermissionsApprovalScopeRecord =
  | { readonly kind: 'once' }
  | { readonly kind: 'bounded'; readonly until: 'session_end'; readonly environmentId?: string | null }

export interface PermissionsDecideParams {
  readonly requestId: string
  readonly approvalId: string
  readonly expectedVersion: number
  readonly decision: PermissionsDecisionValue
  readonly scope: PermissionsApprovalScopeRecord
  readonly sessionId: string
}

export interface PermissionsQueryParams {
  readonly approvalId: string
  readonly nativeRequestId: string
}

/** `_decide_body` outcomes of the backend wire (plugin.py). */
export type PermissionsDecideResult =
  | { readonly outcome: 'recorded'; readonly version: number; readonly decision: PermissionsDecisionValue }
  | { readonly outcome: 'already_recorded'; readonly version: number; readonly decision: PermissionsDecisionValue; readonly requestId: string }
  | { readonly outcome: 'invalid'; readonly reason: string }
  | { readonly outcome: 'version_conflict'; readonly version: number; readonly reason: string }
  | { readonly outcome: 'unknown'; readonly reason: string }

/** `_query_body` outcomes; `grantsExecution` never comes from the UI. */
export type PermissionsQueryResult =
  | {
      readonly outcome: 'resolved'
      readonly state: PermissionsApprovalStateRecord
      readonly receipt: PermissionsNativeReceiptRecord | null
      readonly grantsExecution: boolean
    }
  | { readonly outcome: 'unknown'; readonly reason: string; readonly grantsExecution: false }

export interface PermissionsApprovalStateRecord {
  readonly approvalId: string
  readonly sessionId: string
  readonly executionId: string
  readonly version: number
  readonly state: 'open' | 'settled' | 'invalid'
  readonly decision: PermissionsDecisionValue | null
  readonly scope: PermissionsApprovalScopeRecord | null
  readonly requestId: string | null
  readonly nativeRequestId: string
}

export interface PermissionsNativeReceiptRecord {
  readonly nativeRequestId: string
  readonly approvalId: string
  readonly confirmed: boolean
  readonly observedAt: string | null
}

// ---------------------------------------------------------------------------
// Approval view model — masked display facts, never arguments or secrets
// ---------------------------------------------------------------------------

export type PermissionsApprovalStatus = 'open' | 'settled' | 'invalid' | 'unknown'

/** `confirmed` requires the backend's observation time; anything else stays
 * `unknown`, which is never rendered as allowed (ux.md 未知语义). */
export type PermissionsNativeReceiptView =
  | { readonly kind: 'confirmed'; readonly observedAt: string }
  | { readonly kind: 'unknown' }

/** Only the four display-safe fields the approval region may show. */
export interface PermissionsApprovalDisplay {
  readonly operationCategory: string
  readonly targetSummary: string
  readonly policySource: string
  readonly selectableScopes: readonly PermissionsApprovalScopeRecord[]
}

export interface PermissionsRefusalInfo {
  readonly code: string
  readonly message: string
}

export interface PermissionsApprovalView {
  readonly approvalId: string
  readonly sessionId: string
  readonly nativeRequestId: string
  readonly requestId: string | null
  readonly version: number
  readonly status: PermissionsApprovalStatus
  readonly decision: PermissionsDecisionValue | null
  readonly scope: PermissionsApprovalScopeRecord | null
  readonly nativeReceipt: PermissionsNativeReceiptView
  readonly display: PermissionsApprovalDisplay
  readonly refusal: PermissionsRefusalInfo | null
}

/** Injected by the host; the two methods map 1:1 onto the wire method ids
 * above with the exact required param names. There is deliberately no method
 * that produces a ruling locally. */
export interface PermissionsApprovalTransport {
  decide(params: PermissionsDecideParams): Promise<PermissionsDecideResult>
  query(params: PermissionsQueryParams): Promise<PermissionsQueryResult>
}

// ---------------------------------------------------------------------------
// Pure projections
// ---------------------------------------------------------------------------

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const isText = (value: unknown): value is string =>
  typeof value === 'string' && SINGLE_LINE.test(value) && value.trim().length > 0

const isVersion = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 1

function isScopeRecord(value: unknown): value is PermissionsApprovalScopeRecord {
  if (!isRecord(value)) return false
  if (value.kind === 'once') return true
  return value.kind === 'bounded' && value.until === 'session_end'
    && (value.environmentId === undefined || value.environmentId === null || isText(value.environmentId))
}

export function mapNativeReceipt(record: PermissionsNativeReceiptRecord | null | undefined): PermissionsNativeReceiptView {
  if (record && record.confirmed === true && isText(record.observedAt)) {
    return { kind: 'confirmed', observedAt: record.observedAt }
  }
  return { kind: 'unknown' }
}

/** The `content.renderers` decode: a pure whitelist projection. A malformed
 * or unknown-shaped payload yields null (the readable fallback), never a
 * throw and never a carried-through field outside the whitelist. */
export function decodeApprovalPayload(payload: unknown): PermissionsApprovalView | null {
  if (!isRecord(payload)) return null
  const { approvalId, sessionId, nativeRequestId, requestId, version, state, decision, scope, receipt, refusal, display } = payload
  if (!isText(approvalId) || !isText(sessionId) || !isText(nativeRequestId) || !isVersion(version)) return null
  if (!(requestId === null || (typeof requestId === 'string' && isText(requestId)))) return null
  if (state !== 'open' && state !== 'settled' && state !== 'invalid' && state !== 'unknown') return null
  if (!(decision === null || decision === 'allow' || decision === 'deny')) return null
  if (state === 'settled' && decision === null) return null // a settled state must carry its decision fact
  if (!(scope === null || isScopeRecord(scope))) return null
  if (!(receipt === null || isRecord(receipt))) return null
  if (!isRecord(display) || !isText(display.operationCategory) || !isText(display.targetSummary)
    || !isText(display.policySource) || !Array.isArray(display.selectableScopes)
    || !display.selectableScopes.every(isScopeRecord)) return null
  let refusalInfo: PermissionsRefusalInfo | null = null
  if (refusal !== null) {
    if (!isRecord(refusal) || !isText(refusal.code) || !isText(refusal.message)) return null
    refusalInfo = { code: refusal.code, message: refusal.message }
  }
  return {
    approvalId, sessionId, nativeRequestId,
    requestId: (requestId as string | null) ?? null,
    version,
    status: state,
    decision,
    scope: (scope as PermissionsApprovalScopeRecord | null) ?? null,
    nativeReceipt: mapNativeReceipt(receipt as PermissionsNativeReceiptRecord | null),
    display: {
      operationCategory: display.operationCategory,
      targetSummary: display.targetSummary,
      policySource: display.policySource,
      selectableScopes: display.selectableScopes as readonly PermissionsApprovalScopeRecord[],
    },
    refusal: refusalInfo,
  }
}

/** Fold a query result into the view: `resolved` replaces the backend facts,
 * `unknown` fails closed (status unknown, link lost) — never an allow. */
export function applyQueryResult(
  view: PermissionsApprovalView,
  result: PermissionsQueryResult,
): { readonly view: PermissionsApprovalView; readonly linkLost: boolean } {
  if (result.outcome === 'resolved' && isRecord(result.state)) {
    const s = result.state
    if (s.state === 'open' || s.state === 'settled' || s.state === 'invalid') {
      return {
        view: {
          ...view,
          approvalId: s.approvalId, sessionId: s.sessionId, nativeRequestId: s.nativeRequestId,
          requestId: s.requestId ?? view.requestId,
          version: s.version, status: s.state,
          decision: s.decision ?? view.decision,
          scope: s.scope ?? view.scope,
          nativeReceipt: mapNativeReceipt(result.receipt),
        },
        linkLost: false,
      }
    }
  }
  return { view: { ...view, status: 'unknown' }, linkLost: true }
}

/** Extract the leading stable code from a wire `reason` line, if registered;
 * free-form text never reaches the render path unfiltered. */
export function refusalCodeFromReason(reason: string): PermissionsRefusalCode | null {
  const hit = /^([A-Z][A-Z0-9_]+)(?::|\s|$)/.exec(reason)
  if (!hit) return null
  return (PERMISSIONS_REFUSAL_CODES as readonly string[]).includes(hit[1])
    ? hit[1] as PermissionsRefusalCode : null
}

// ---------------------------------------------------------------------------
// Settings-region mirrors (T011) — the ceiling/intent record vocabulary
// Authority: api ceilings.py (_RECORD_FIELDS / ExposureLevel / CeilingSource /
// _TRUSTED_SOURCES / CeilingEntry.of), intents.py (_RECORD_FIELDS),
// rules.py (Scope / RuleAction), backend policies.py (_ceiling_record /
// _intent_record — the stored camelCase JSON the reader hands back).
// tests/contract-consistency.test.ts parses those sources and fails on drift.
// ---------------------------------------------------------------------------

/** `ceilings.py ExposureLevel` values, in declaration order (rank ascends). */
export const PERMISSIONS_EXPOSURE_LEVELS = ['none', 'read', 'write', 'network', 'exec', 'full'] as const
export type PermissionsExposureLevel = (typeof PERMISSIONS_EXPOSURE_LEVELS)[number]

/** `rules.py Scope` values, low trust first — rank is trust, not breadth. */
export const PERMISSIONS_SCOPE_ORDER = ['session', 'project', 'user', 'admin'] as const
/** `rules.py RuleAction` values — the three interpretation results. */
export const INTENT_RULE_ACTIONS = ['allow', 'ask', 'deny'] as const

/** Exactly the `_RECORD_FIELDS` frozenset of ceilings.py. */
export const CEILING_RECORD_FIELDS =
  ['policyId', 'scope', 'revision', 'source', 'signed', 'deny', 'requireApproval',
    'maximumExposure', 'effectiveFrom'] as const
/** Exactly the `_RECORD_FIELDS` frozenset of intents.py. */
export const INTENT_RECORD_FIELDS =
  ['intentId', 'revision', 'harnessId', 'scope', 'rules', 'desiredMode'] as const
/** A ceiling entry may only carry a restriction (`CeilingEntry.of`). */
export const CEILING_ENTRY_ACTIONS = ['deny', 'require-approval'] as const
/** The two members of `ceilings.py _TRUSTED_SOURCES`. */
export const TRUSTED_CEILING_SOURCES = ['signed-admin', 'host-trusted'] as const

export interface PermissionsCeilingEntryRecord {
  readonly key: string
  readonly action: (typeof CEILING_ENTRY_ACTIONS)[number]
  readonly pattern?: string | null
}

/** The stored ceiling JSON (`policies.py _ceiling_record`); rendered read-only. */
export interface PermissionsCeilingRecord {
  readonly policyId: string
  readonly scope: string
  readonly revision: number
  readonly source: string
  readonly signed: boolean
  readonly deny: readonly PermissionsCeilingEntryRecord[]
  readonly requireApproval: readonly PermissionsCeilingEntryRecord[]
  readonly maximumExposure: string
  readonly effectiveFrom: string
}

export interface PermissionsIntentRuleRecord {
  readonly key: string
  readonly action: (typeof INTENT_RULE_ACTIONS)[number]
  readonly priority: number
  readonly scope: string
  readonly pattern?: string | null
}

/** The stored intent JSON (`policies.py _intent_record`); `desiredMode` is a
 * brand-native name (`intents.py BrandMode.declare`) and is only ever rendered
 * bound to its own harnessId — never as a cross-brand synonym (FR-09). */
export interface PermissionsIntentRecord {
  readonly intentId: string
  readonly revision: number
  readonly harnessId: string
  readonly scope: string
  readonly rules: readonly PermissionsIntentRuleRecord[]
  readonly desiredMode?: string
}

/** One legacy-import review finding surfaced by the host (backend
 * `migration.py LegacyRuleImport.needs_review`); flagged entries stay out of
 * the intent and resolve to ask/deny, never to an imported allow. */
export interface PermissionsLegacyReviewRecord {
  readonly intentId: string
  readonly needsReviewCount: number
}

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

function isCeilingEntryRecord(value: unknown): value is PermissionsCeilingEntryRecord {
  if (!isRecord(value)) return false
  if (Object.keys(value).some(k => !['key', 'pattern', 'action'].includes(k))) return false
  if (!isText(value.key)) return false
  if (!(CEILING_ENTRY_ACTIONS as readonly string[]).includes(String(value.action))) return false
  return value.pattern === undefined || value.pattern === null || isText(value.pattern)
}

/** Same closed-shape rule as `PolicyCeiling.from_record`: unknown fields make
 * the whole record unverifiable, they are not ignored. */
export function isPermissionsCeilingRecord(value: unknown): value is PermissionsCeilingRecord {
  if (!isRecord(value)) return false
  const keys = Object.keys(value)
  if (keys.some(k => !(CEILING_RECORD_FIELDS as readonly string[]).includes(k))) return false
  if (!isText(value.policyId) || !isText(value.source) || !isText(value.effectiveFrom)) return false
  if (!(PERMISSIONS_SCOPE_ORDER as readonly string[]).includes(String(value.scope))) return false
  if (!isFiniteNumber(value.revision) || (value.revision as number) < 1) return false
  if (typeof value.signed !== 'boolean') return false
  if (!(PERMISSIONS_EXPOSURE_LEVELS as readonly string[]).includes(String(value.maximumExposure))) return false
  return Array.isArray(value.deny) && value.deny.every(isCeilingEntryRecord)
    && Array.isArray(value.requireApproval) && value.requireApproval.every(isCeilingEntryRecord)
}

/** `PolicyCeiling.is_trusted` in TS: signed + trusted provenance + scope at
 * user level or above. An untrusted record is modelled, never summarized as a
 * bound ("absence of a ceiling is not 'no limit applies'"). Takes the
 * structural triple so both the stored record and the describe row share it. */
export function ceilingRecordIsTrusted(
  record: Pick<PermissionsCeilingRecord, 'signed' | 'source' | 'scope'>,
): boolean {
  return record.signed
    && (TRUSTED_CEILING_SOURCES as readonly string[]).includes(record.source)
    && (PERMISSIONS_SCOPE_ORDER as readonly string[]).indexOf(record.scope)
      >= (PERMISSIONS_SCOPE_ORDER as readonly string[]).indexOf('user')
}

export function isPermissionsIntentRecord(value: unknown): value is PermissionsIntentRecord {
  if (!isRecord(value)) return false
  const keys = Object.keys(value)
  if (keys.some(k => !(INTENT_RECORD_FIELDS as readonly string[]).includes(k))) return false
  if (!isText(value.intentId) || !isText(value.harnessId)) return false
  if (!(PERMISSIONS_SCOPE_ORDER as readonly string[]).includes(String(value.scope))) return false
  if (!isFiniteNumber(value.revision) || (value.revision as number) < 1) return false
  if (!Array.isArray(value.rules)) return false
  const rulesOk = (value.rules as readonly unknown[]).every(rule => {
    if (!isRecord(rule)) return false
    if (Object.keys(rule).some(k => !['key', 'action', 'priority', 'scope', 'pattern', 'authorization'].includes(k))) return false
    if (!isText(rule.key) || typeof rule.priority !== 'number') return false
    if (!(INTENT_RULE_ACTIONS as readonly string[]).includes(String(rule.action))) return false
    if (!(PERMISSIONS_SCOPE_ORDER as readonly string[]).includes(String(rule.scope))) return false
    return rule.pattern === undefined || rule.pattern === null || isText(rule.pattern)
  })
  if (!rulesOk) return false
  return value.desiredMode === undefined || isText(value.desiredMode)
}

export function isPermissionsLegacyReviewRecord(value: unknown): value is PermissionsLegacyReviewRecord {
  if (!isRecord(value)) return false
  if (Object.keys(value).some(k => ['intentId', 'needsReviewCount'].indexOf(k) === -1)) return false
  return isText(value.intentId) && isFiniteNumber(value.needsReviewCount)
}

// ---------------------------------------------------------------------------
// permissions.policy.describe — the closed response mirror and strict decoder
// (T015). Authority: the backend's describe.py (`PolicyDescribe.describe`'s
// dict literals + DESCRIBE_REQUIRED/OPTIONAL_PARAMS) — parsed and asserted
// equal by tests/contract-consistency.test.ts. Chosen decode rule: REFUSE.
// Any unknown/extra key, any missing key, any wrong type fails the whole
// round-trip; partial facts are never rendered (the backend applies the same
// "unknown fields make the record unverifiable" discipline server-side).
// ---------------------------------------------------------------------------

export interface PermissionsDescribeParams {
  readonly principal?: string
  readonly scope?: string
}

/** Closed-shape key mirrors, in declaration order. */
export const DESCRIBE_RESPONSE_KEYS = ['ready', 'ceilings', 'intents', 'needsReview'] as const
export const DESCRIBE_CEILING_ROW_KEYS =
  ['policyId', 'scope', 'revision', 'source', 'signed', 'maximumExposure',
    'effectiveFrom', 'hardDenies', 'requireApproval'] as const
export const DESCRIBE_CEILING_ENTRY_KEYS = ['key', 'pattern', 'action'] as const
export const DESCRIBE_INTENT_ROW_KEYS =
  ['intentId', 'revision', 'harnessId', 'scope', 'rules', 'desiredMode'] as const
export const DESCRIBE_RULE_ROW_KEYS = ['key', 'pattern', 'action', 'priority', 'scope'] as const
export const DESCRIBE_BRAND_MODE_KEYS = ['brand', 'name'] as const
export const DESCRIBE_REVIEW_ROW_KEYS = ['source', 'index', 'reason'] as const

export interface PermissionsDescribeCeilingEntry {
  readonly key: string
  readonly pattern: string | null
  readonly action: (typeof CEILING_ENTRY_ACTIONS)[number]
}

export interface PermissionsDescribeCeiling {
  readonly policyId: string
  readonly scope: string
  readonly revision: number
  readonly source: string
  readonly signed: boolean
  readonly maximumExposure: string
  readonly effectiveFrom: string
  readonly hardDenies: readonly PermissionsDescribeCeilingEntry[]
  readonly requireApproval: readonly PermissionsDescribeCeilingEntry[]
}

export interface PermissionsDescribeIntentRule {
  readonly key: string
  readonly pattern: string | null
  readonly action: (typeof INTENT_RULE_ACTIONS)[number]
  readonly priority: number
  readonly scope: string
}

/** A brand-native mode pair: `desiredMode` is only ever rendered bound to its
 * own brand — it is never translated into a cross-brand label (FR-09). */
export interface PermissionsDescribeBrandMode {
  readonly brand: string
  readonly name: string
}

export interface PermissionsDescribeIntent {
  readonly intentId: string
  readonly revision: number
  readonly harnessId: string
  readonly scope: string
  readonly rules: readonly PermissionsDescribeIntentRule[]
  readonly desiredMode: PermissionsDescribeBrandMode | null
}

/** One 待复核 finding carried from the backend's review rows; it stays out of
 * the intent and resolves on the stricter side — the region can never allow
 * it (ux.md §Settings). */
export interface PermissionsDescribeReview {
  readonly source: string
  readonly index: number | null
  readonly reason: string
}

export interface PermissionsDescribeResult {
  readonly ready: boolean
  readonly ceilings: readonly PermissionsDescribeCeiling[]
  readonly intents: readonly PermissionsDescribeIntent[]
  readonly needsReview: readonly PermissionsDescribeReview[]
}

/** `keySetOk` — a closed literal: the allowed keys and nothing else. Extra
 * keys are refused, not dropped, because a smuggled key must not ride along a
 * read-only summary either way. */
function isClosedRecord(value: unknown, allowed: readonly string[]): value is Record<string, unknown> {
  if (!isRecord(value)) return false
  const keys = Object.keys(value)
  return keys.length === allowed.length && allowed.every(k => keys.includes(k))
}

const isTextOrNull = (value: unknown): value is string | null => value === null || isText(value)

function isDescribeEntryRecord(value: unknown): value is PermissionsDescribeCeilingEntry {
  if (!isClosedRecord(value, DESCRIBE_CEILING_ENTRY_KEYS)) return false
  return isText(value.key) && isTextOrNull(value.pattern)
    && (CEILING_ENTRY_ACTIONS as readonly string[]).includes(String(value.action))
}

function isDescribeCeilingRecord(value: unknown): value is PermissionsDescribeCeiling {
  if (!isClosedRecord(value, DESCRIBE_CEILING_ROW_KEYS)) return false
  if (!isText(value.policyId) || !isText(value.source) || !isText(value.effectiveFrom)) return false
  if (!(PERMISSIONS_SCOPE_ORDER as readonly string[]).includes(String(value.scope))) return false
  if (!isFiniteNumber(value.revision) || (value.revision as number) < 1) return false
  if (typeof value.signed !== 'boolean') return false
  if (!(PERMISSIONS_EXPOSURE_LEVELS as readonly string[]).includes(String(value.maximumExposure))) return false
  return Array.isArray(value.hardDenies) && value.hardDenies.every(isDescribeEntryRecord)
    && Array.isArray(value.requireApproval) && value.requireApproval.every(isDescribeEntryRecord)
}

function isDescribeRuleRecord(value: unknown): value is PermissionsDescribeIntentRule {
  if (!isClosedRecord(value, DESCRIBE_RULE_ROW_KEYS)) return false
  if (!isText(value.key) || !isTextOrNull(value.pattern)) return false
  if (!(INTENT_RULE_ACTIONS as readonly string[]).includes(String(value.action))) return false
  if (!(PERMISSIONS_SCOPE_ORDER as readonly string[]).includes(String(value.scope))) return false
  return isFiniteNumber(value.priority)
}

function isBrandModeRecord(value: unknown): value is PermissionsDescribeBrandMode {
  if (!isClosedRecord(value, DESCRIBE_BRAND_MODE_KEYS)) return false
  return isText(value.brand) && isText(value.name)
}

function isDescribeIntentRecord(value: unknown): value is PermissionsDescribeIntent {
  if (!isClosedRecord(value, DESCRIBE_INTENT_ROW_KEYS)) return false
  if (!isText(value.intentId) || !isText(value.harnessId)) return false
  if (!(PERMISSIONS_SCOPE_ORDER as readonly string[]).includes(String(value.scope))) return false
  if (!isFiniteNumber(value.revision) || (value.revision as number) < 1) return false
  if (!Array.isArray(value.rules) || !(value.rules as readonly unknown[]).every(isDescribeRuleRecord)) return false
  return value.desiredMode === null || isBrandModeRecord(value.desiredMode)
}

function isDescribeReviewRecord(value: unknown): value is PermissionsDescribeReview {
  if (!isClosedRecord(value, DESCRIBE_REVIEW_ROW_KEYS)) return false
  if (!isText(value.source) || !isText(value.reason)) return false
  return value.index === null || isFiniteNumber(value.index)
}

/** The whole-payload strict decode: valid → the closed result with values
 * carried verbatim (desiredMode is never renamed or merged); invalid → null,
 * which the region surfaces as a local alert, never as facts. */
export function decodeDescribeResponse(payload: unknown): PermissionsDescribeResult | null {
  if (!isClosedRecord(payload, DESCRIBE_RESPONSE_KEYS)) return null
  if (typeof payload.ready !== 'boolean') return null
  if (!Array.isArray(payload.ceilings) || !payload.ceilings.every(isDescribeCeilingRecord)) return null
  if (!Array.isArray(payload.intents) || !payload.intents.every(isDescribeIntentRecord)) return null
  if (!Array.isArray(payload.needsReview) || !payload.needsReview.every(isDescribeReviewRecord)) return null
  return {
    ready: payload.ready,
    ceilings: payload.ceilings,
    intents: payload.intents,
    needsReview: payload.needsReview,
  }
}

// ---------------------------------------------------------------------------
// The describe read seam — the injected transport for the region round-trip
// ---------------------------------------------------------------------------

/** One answer from the injected transport. `no-provider` is "this method is
 * not in the composition" (absence hides the region); `error` is a present
 * backend that refused (a local alert, never the uninstalled branch); `ok`
 * carries the RAW wire payload — the region itself runs the strict decoder,
 * so a permissive transport cannot smuggle unproven facts into the render. */
export type PermissionsDescribeAnswer =
  | { readonly status: 'no-provider' }
  | { readonly status: 'error'; readonly code: string; readonly message: string }
  | { readonly status: 'ok'; readonly payload: unknown }

export interface PermissionsDescribeTransport {
  describe(params?: PermissionsDescribeParams): Promise<PermissionsDescribeAnswer>
}

/** Approval-history rows for the 「审批历史过滤」 area. There is deliberately
 * no wire LIST method for approvals (the backend registers only
 * decide/query/describe, and describe's closed answer carries policy facts,
 * not approval rows): the host contributes the same backend approval payloads
 * the Chat renderer receives, and every row still passes the whitelist
 * `decodeApprovalPayload` before display. */
export interface PermissionsApprovalFactsSource {
  load(): Promise<readonly unknown[]>
}

/** The real Settings contribution surface: the `addSettingsSection` member of
 * `WorkbenchComposition.forScope(scope)` (packages/workbench/api/workbench.ts),
 * taken by type so registration cannot go through anything but the platform API. */
export type PermissionsSettingsHostHandle = Pick<
  ReturnType<import('@extensions/ordessa.contracts/contract.js').WorkbenchComposition['forScope']>,
  'addSettingsSection'
>

// ---------------------------------------------------------------------------
// Approval history filtering (pure, over decoded backend facts only)
// ---------------------------------------------------------------------------

export interface PermissionsHistoryFilter {
  readonly status?: 'all' | PermissionsApprovalStatus
  readonly decision?: 'all' | PermissionsDecisionValue
  readonly sessionId?: string
}

export const ALL_HISTORY_FILTER: PermissionsHistoryFilter = { status: 'all', decision: 'all', sessionId: 'all' }

export function filterApprovalHistory(
  views: readonly PermissionsApprovalView[], filter: PermissionsHistoryFilter,
): readonly PermissionsApprovalView[] {
  return views.filter(view =>
    (filter.status === undefined || filter.status === 'all' || view.status === filter.status)
    && (filter.decision === undefined || filter.decision === 'all' || view.decision === filter.decision)
    && (filter.sessionId === undefined || filter.sessionId === 'all' || view.sessionId === filter.sessionId))
}

/** The rule sources the displayed facts actually name: each trusted ceiling,
 * each intent revision and every distinct policy source carried by an
 * approval — derived from the describe round-trip, never typed in. */
export function ruleSourceSummaries(
  ceilings: readonly PermissionsDescribeCeiling[],
  intents: readonly PermissionsDescribeIntent[],
  approvals: readonly PermissionsApprovalView[],
): readonly string[] {
  const sources: string[] = []
  for (const ceiling of ceilings) {
    const trust = ceilingRecordIsTrusted(ceiling) ? '可信来源' : '未通过可信来源校验'
    sources.push(`组织上限 ${ceiling.policyId}@${ceiling.revision}（来源：${ceiling.source}，${trust}）`)
  }
  for (const intent of intents) {
    sources.push(`用户意图 ${intent.intentId}@${intent.revision}（作用域：${intent.scope}）`)
  }
  const seen = new Set(sources)
  for (const approval of approvals) {
    const label = `审批事实声明的权限来源：${approval.display.policySource}`
    if (!seen.has(label)) { sources.push(label); seen.add(label) }
  }
  return sources
}
