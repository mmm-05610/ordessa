/**
 * Shared fixtures for the Settings definition-library tests.
 *
 * `createFakePort` is a *test double for the port*, not a production client:
 * every response is deferred so a test can decide the arrival order and prove
 * the per-target stamping drop for real (§C2 / G15).
 */
import type {
  AssignmentView, DefinitionDetail, DefinitionSummary, EffectiveSet, ImportPlanResult, ImportPreview,
  NativeInspection, NativeObservation, ServiceResult, SubagentDefinitionServicePort, TargetStamp,
} from '../src/contract'
import { fail, ok } from '../src/contract'
import type { SettingsState } from '../src/model'
import { initialState } from '../src/model'

export const TARGET: TargetStamp = {
  serverId: 'srv-a',
  projectId: 'proj-a',
  profileId: 'prof-a',
  sessionId: 'sess-a',
  revision: 1,
  providerGeneration: 'gen-1',
}

export const OTHER_TARGET: TargetStamp = {
  serverId: 'srv-b',
  projectId: 'proj-b',
  profileId: 'prof-b',
  sessionId: 'sess-b',
  revision: 7,
  providerGeneration: 'gen-9',
}

export function summaryOf(overrides: Partial<DefinitionSummary> = {}): DefinitionSummary {
  return {
    serverScope: 'srv-a',
    definitionId: 'def-1',
    slug: 'code-reviewer',
    displayName: '只读代码审阅者',
    description: '只读审阅，不写文件',
    originScope: 'public',
    originOwner: 'principal-1',
    latestRevision: 2,
    archived: false,
    rowVersion: 3,
    lastApprovedSource: {
      origin: 'user-upload', originRef: 'local:reviewer.md',
      contentDigest: 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      approvedByPrincipal: 'principal-1', approvedAt: '2026-09-28T00:00:00Z',
    },
    capabilities: [
      {
        harnessId: 'claude', targetVersion: '0.81.2', support: 'native',
        facts: { stored: true, selected: 'unknown', projected: 'unknown', loaded: 'unknown', invokable: 'unknown', used: 'unknown' },
        evidence: ['capability-matrix.md#claude'],
      },
      {
        harnessId: 'pi', targetVersion: '0.5.0', support: 'extension-backed',
        facts: { stored: true, selected: false, projected: 'unknown', loaded: 'unknown', invokable: 'unknown', used: 'unknown' },
      },
      { harnessId: 'codex', targetVersion: '1.1.14', support: 'unsupported', facts: { stored: true } },
    ],
    ...overrides,
  }
}

export function detailOf(overrides: Partial<DefinitionDetail> = {}): DefinitionDetail {
  const v1 = {
    definitionId: 'def-1', revision: 1,
    contentDigest: 'sha256:1111111111111111111111111111111111111111111111111111111111111111',
    roleBody: '你是只读审阅者。\n不要写文件。',
    toolRefs: [] as const,
  }
  const v2 = {
    definitionId: 'def-1', revision: 2,
    contentDigest: 'sha256:2222222222222222222222222222222222222222222222222222222222222222',
    roleBody: '你是只读审阅者。\n不要写文件。\n输出差异清单。',
    toolRefs: [{ ownerId: 'Bash' }],
    declaredModelRef: { ownerId: 'model-x', revision: 'r1' },
    capabilityDeclarations: [
      { kind: 'tool' as const, name: 'Read', granted: true as const },
      { kind: 'tool' as const, name: 'Bash', granted: 'unknown' as const, refusal: { code: 'PERMISSION_EXCEEDS_CEILING' as const, detail: '当前上限未授予 Bash', source: 'ceiling（SR-6 缺席）' } },
      { kind: 'permission-mode' as const, name: 'bypassPermissions', granted: false as const, refusal: { code: 'PERMISSION_EXCEEDS_CEILING' as const, detail: '审批姿势放宽的字段一律拒绝', source: 'capability-matrix.md' } },
    ],
  }
  return {
    ...summaryOf(),
    revisions: [v1, v2],
    latestContent: v2,
    pinnedAssignments: [
      { serverScope: 'srv-a', principal: 'principal-1', scopeKind: 'project-generic', scopeId: 'proj-a', harnessId: 'any', definitionId: 'def-1', decision: 'enable', revision: 1, rowVersion: 4 },
    ],
    ...overrides,
  }
}

export function assignmentOf(overrides: Partial<AssignmentView> = {}): AssignmentView {
  return {
    serverScope: 'srv-a', principal: 'principal-1', scopeKind: 'user-global-generic', scopeId: null,
    harnessId: 'any', definitionId: 'def-1', decision: 'enable', revision: 1, rowVersion: 1, ...overrides,
  }
}

// ---------------------------------------------------------------------------
// Hand-resolvable port double
// ---------------------------------------------------------------------------

export interface Deferred<T> {
  readonly promise: Promise<ServiceResult<T>>
  resolve: (value: ServiceResult<T>) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: ServiceResult<T>) => void
  const promise = new Promise<ServiceResult<T>>(r => { resolve = r })
  return { promise, resolve }
}

export interface FakePort extends SubagentDefinitionServicePort {
  readonly calls: { method: string; stamp: TargetStamp }[]
  readonly listD: Deferred<readonly DefinitionSummary[]>
  readonly detailD: Deferred<DefinitionDetail>
  readonly nativeD: Deferred<NativeInspection>
  readonly effectiveD: Deferred<EffectiveSet>
  readonly assignmentsD: Deferred<readonly AssignmentView[]>
  readonly mutationD: Deferred<DefinitionSummary>
  readonly assignmentD: Deferred<AssignmentView>
  readonly previewD: Deferred<ImportPreview>
  readonly approveD: Deferred<ImportPlanResult>
  /** Resolve every outstanding request with a success carrying its own stamp. */
  settleAll(stamp: TargetStamp): Promise<void>
}

export function createFakePort(): FakePort {
  const calls: { method: string; stamp: TargetStamp }[] = []
  const listD = deferred<readonly DefinitionSummary[]>()
  const detailD = deferred<DefinitionDetail>()
  const nativeD = deferred<NativeInspection>()
  const effectiveD = deferred<EffectiveSet>()
  const assignmentsD = deferred<readonly AssignmentView[]>()
  const mutationD = deferred<DefinitionSummary>()
  const assignmentD = deferred<AssignmentView>()
  const previewD = deferred<ImportPreview>()
  const approveD = deferred<ImportPlanResult>()
  const outstanding = new Set<Promise<unknown>>()
  const track = <T,>(p: Promise<T>): Promise<T> => {
    outstanding.add(p)
    void p.finally(() => { outstanding.delete(p) })
    return p
  }
  const port: FakePort = {
    calls,
    listD, detailD, nativeD, effectiveD, assignmentsD, mutationD, assignmentD, previewD, approveD,
    settleAll(stamp) {
      listD.resolve(ok(stamp, []))
      detailD.resolve(ok(stamp, detailOf()))
      nativeD.resolve(ok(stamp, { state: 'unknown', reason: '无观测机制' }))
      effectiveD.resolve(ok(stamp, { resolved: [], excluded: [] }))
      assignmentsD.resolve(ok(stamp, []))
      mutationD.resolve(ok(stamp, summaryOf()))
      assignmentD.resolve(ok(stamp, assignmentOf()))
      previewD.resolve(ok(stamp, IMPORT_PREVIEW))
      approveD.resolve(ok(stamp, { previewId: 'prev-1', definitions: [] }))
      return Promise.all([...outstanding]).then(() => undefined)
    },
    listDefinitions(stamp, _query) { calls.push({ method: 'listDefinitions', stamp }); return track(listD.promise) },
    getDefinition(stamp, _definitionId) { calls.push({ method: 'getDefinition', stamp }); return track(detailD.promise) },
    inspectNative(stamp) { calls.push({ method: 'inspectNative', stamp }); return track(nativeD.promise) },
    resolvePreview(stamp, _expectedRevisions) { calls.push({ method: 'resolvePreview', stamp }); return track(effectiveD.promise) },
    listAssignments(stamp, _scope) { calls.push({ method: 'listAssignments', stamp }); return track(assignmentsD.promise) },
    createDefinition(input) { calls.push({ method: 'createDefinition', stamp: input.stamp }); return track(mutationD.promise) },
    saveRevision(input) { calls.push({ method: 'saveRevision', stamp: input.stamp }); return track(mutationD.promise) },
    archive(input) { calls.push({ method: 'archive', stamp: input.stamp }); return track(mutationD.promise) },
    restore(input) { calls.push({ method: 'restore', stamp: input.stamp }); return track(mutationD.promise) },
    clone(input) { calls.push({ method: 'clone', stamp: input.stamp }); return track(mutationD.promise) },
    importPreview(input) { calls.push({ method: 'importPreview', stamp: input.stamp }); return track(previewD.promise) },
    approveImport(input) { calls.push({ method: 'approveImport', stamp: input.stamp }); return track(approveD.promise) },
    approveAssignmentUpdate(input) { calls.push({ method: 'approveAssignmentUpdate', stamp: input.stamp }); return track(assignmentD.promise) },
  }
  return port
}

export const IMPORT_PREVIEW: ImportPreview = {
  previewId: 'prev-1',
  sourceName: 'team-agents',
  sourceRef: 'git:rev-abc123',
  sourceDigest: 'sha256:3333333333333333333333333333333333333333333333333333333333333333',
  files: [
    { relativePath: 'reviewer.md', sizeBytes: 120, contentDigest: 'sha256:4444', diagnostics: [], selectable: true, declaredSlug: 'reviewer' },
    { relativePath: 'dangerous.md', sizeBytes: 40, contentDigest: 'sha256:5555', diagnostics: ['含 shell 模板，已拒绝'], selectable: false },
  ],
  diagnostics: ['引用 MCP 未部署：仅声明，不自动安装'],
  futurePermissions: [
    { kind: 'tool', name: 'Read', granted: 'unknown' },
    { kind: 'mcp', name: 'github', granted: false, refusal: { code: 'REFERENCE_UNRESOLVED', detail: 'MCP 服务未部署', source: '引用解析' } },
  ],
}

export function nativeOf(overrides: Partial<NativeObservation> = {}): NativeObservation {
  return { nativeName: 'project-reviewer', scope: 'project', sourceCategory: 'native-settings-file', targetGeneration: 'tg-1', evidence: 'settingSources=["user","project","local"]', ...overrides }
}

// ---------------------------------------------------------------------------
// State builders
// ---------------------------------------------------------------------------

export function readyState(target: TargetStamp = TARGET): SettingsState {
  return initialState({ target, viewerPrincipal: 'principal-1', serviceAvailable: true })
}

export function stateWithRows(rows: readonly DefinitionSummary[], target: TargetStamp = TARGET): SettingsState {
  return { ...readyState(target), list: { status: 'ready', data: rows, failure: null, requestStamp: target, absence: null } }
}

export function stateWithNative(observations: readonly NativeObservation[], target: TargetStamp = TARGET): SettingsState {
  return {
    ...stateWithRows([], target),
    native: { status: 'ready', data: { state: 'observed', observations }, failure: null, requestStamp: target, absence: null },
  }
}

export function stateWithDetail(definition: DefinitionDetail, target: TargetStamp = TARGET): SettingsState {
  return {
    ...stateWithRows([definition], target),
    selection: definition.definitionId,
    detail: { status: 'ready', data: definition, failure: null, requestStamp: target, absence: null },
  }
}

export function okList(stamp: TargetStamp, rows: readonly DefinitionSummary[]): ServiceResult<readonly DefinitionSummary[]> {
  return ok(stamp, rows)
}

export function failedResult<T>(stamp: TargetStamp, code: Parameters<typeof fail>[1]['code'], detailText: string): ServiceResult<T> {
  return fail(stamp, { code, detail: detailText })
}
