// The Sandbox domain's own Settings region ("Harness 原生隔离"), contributed
// through the platform's real contribution seam:
//   packages/workbench/api/workbench.ts:41  WorkbenchComposition.forScope(...).addSettingsSection
//   packages/workbench/src/model.ts:124     the scoped registry behind it (scope-owned, auto-released)
//
// The region renders `sandbox.describe@1` facts and nothing else. Its whole
// safety argument is the state machine below: absence hides the section, a
// present-but-broken provider says "unavailable", an unproven pin contributes no
// menu, and a selection is refused with a stable code instead of being applied
// or silently downgraded (contracts.md §C2/§C4, spec FR-05/FR-06/FR-08/FR-09).
import { createElement } from 'react'
import type { IDisposable } from '@ordessa/extension-api'
import type { WorkbenchSettingsSection } from '@extensions/ordessa.contracts/contract.js'
import {
  sandboxMenuOptions,
  type SandboxDescribeRequest,
  type SandboxDescribeResult,
  type SandboxDescribeTransport,
  type SandboxErrorCode,
  type SandboxOption,
  type SandboxSettingsHost,
} from './contract'
import { SandboxSettingsSectionView } from './views/settings-section-view'

export const SANDBOX_SETTINGS_SECTION_ID = 'ordessa.sandbox-settings.region'
export const SANDBOX_SETTINGS_SECTION_TITLE = 'Harness 原生隔离'

/** The identity of the pin the menu was read for; a stale click names it. */
export interface SandboxPin {
  readonly harnessId: string
  readonly nativeVersion: string
}

export type SandboxRegionState =
  /** Nothing to show: no provider, or an uninstalled facet. The section stays out. */
  | { readonly kind: 'absent'; readonly pin: SandboxPin }
  /** The provider exists and refused. Local error wording — never "not installed". */
  | {
      readonly kind: 'provider-error'
      readonly pin: SandboxPin
      readonly code: SandboxErrorCode
      readonly message: string
    }
  /** Describe answered, but this pin has no proven options: no menu is invented. */
  | { readonly kind: 'unknown-pin'; readonly pin: SandboxPin; readonly reason: string; readonly menu: readonly SandboxOption[] }
  | {
      readonly kind: 'ready'
      readonly pin: SandboxPin
      readonly nativeVersion: string
      readonly result: SandboxDescribeResult
      readonly menu: readonly SandboxOption[]
    }

export function isSandboxRegionVisible(state: SandboxRegionState): boolean {
  return state.kind !== 'absent'
}

/**
 * Ask the backend what it contributes. Every branch here is a different user
 * answer, so the three "nothing to show" shapes stay distinct: no provider /
 * uninstalled facet hide the region, a refusing provider shows an error.
 */
export async function resolveSandboxRegionState(
  transport: SandboxDescribeTransport,
  request: SandboxDescribeRequest,
): Promise<SandboxRegionState> {
  const fallbackPin: SandboxPin = { harnessId: request.harnessId, nativeVersion: request.nativeVersion ?? '' }
  const answer = await transport.describe(request)
  if (answer.status === 'no-provider') return { kind: 'absent', pin: fallbackPin }
  if (answer.status === 'error') return { kind: 'provider-error', pin: fallbackPin, code: answer.code, message: answer.message }

  const result = answer.result
  const pin: SandboxPin = { harnessId: result.harnessId, nativeVersion: result.nativeVersion }
  // An uninstalled facet hides its configuration items while stored values stay
  // in the repository (FR-08); that is the backend's call, not this layer's.
  if (!result.visible || result.status === 'uninstalled') return { kind: 'absent', pin }
  if (result.status === 'unknown' || result.options.length === 0) {
    return { kind: 'unknown-pin', pin, reason: result.reason, menu: [] }
  }
  return {
    kind: 'ready', pin, nativeVersion: result.nativeVersion, result,
    menu: sandboxMenuOptions(result),
  }
}

/** Draft persistence seam. Hiding never writes here, and nothing deletes. */
export interface SandboxDraftStore {
  read(harnessId: string): { optionId: string } | undefined
  write(harnessId: string, draft: { optionId: string }): void
}

export function createInMemoryDraftStore(): SandboxDraftStore {
  const stored = new Map<string, { optionId: string }>()
  return {
    read: harnessId => stored.get(harnessId),
    write: (harnessId, draft) => { stored.set(harnessId, draft) },
  }
}

export type SandboxSelectionOutcome =
  | { readonly status: 'applied'; readonly optionId: string }
  | { readonly status: 'refused'; readonly code: SandboxErrorCode; readonly message: string; readonly suggestion: string }

/**
 * The refusal table, mirroring `describe.py:SandboxDescription.select` plus
 * `ceiling.py:check_within_ceiling`. `unsupported` and `unknown` stay separate
 * codes (contracts.md §C4): the first is a proven negative, the second means
 * nothing in this tree proves the effect, and a click must not settle either.
 */
export function evaluateSandboxSelection(state: SandboxRegionState, optionId: string): SandboxSelectionOutcome {
  if (state.kind === 'absent') {
    return {
      status: 'refused', code: 'PROVIDER_BUSY',
      message: '该 Harness 当前没有可用的原生隔离提供者，选择未生效',
      suggestion: '等待原生隔离提供者就绪后重试',
    }
  }
  if (state.kind === 'provider-error') {
    return {
      status: 'refused', code: state.code,
      message: `原生隔离服务未能确认该选择（${state.code}）：${state.message}`,
      suggestion: '修复原生隔离提供者后再试；界面不会代替后端确认',
    }
  }
  if (state.kind === 'unknown-pin') {
    return {
      status: 'refused', code: 'SANDBOX_NATIVE_UNSUPPORTED',
      message: `该 pin 没有任何已登记的原生隔离选项，选择“${optionId}”等于凭空猜一个菜单`,
      suggestion: '先为当前 pin 完成 describe/T05 取证，未证实的选项永不被提供',
    }
  }
  const { result } = state
  const option = result.options.find(item => item.optionId === optionId)
  if (option === undefined) {
    return {
      status: 'refused', code: 'SANDBOX_NATIVE_UNSUPPORTED',
      message: `“${optionId}”不在 ${result.harnessId} 当前 pin 的描述结果中`,
      suggestion: '只为该 pin 重新调用 sandbox.describe；未出现的选项不受支持',
    }
  }
  if (option.status === 'unsupported') {
    return {
      status: 'refused', code: 'SANDBOX_NATIVE_UNSUPPORTED',
      message: `该 Harness 的原生配置面无法表达“${option.optionId}”：${option.source}`,
      suggestion: '把这条要求留给 Permissions 域，不要在此近似',
    }
  }
  if (option.status === 'unknown') {
    return {
      status: 'refused', code: 'SANDBOX_EFFECT_UNKNOWN',
      message: `“${option.optionId}”的生效范围尚未被证明，选择它就是猜测`,
      suggestion: '完成受控探针（T05）取证后再启用该选项',
    }
  }
  // describe.py marks an option locked when its strictness reaches the admin
  // minimum, so every *unlocked* option is strictly looser. Choosing one while
  // the administrator enforces a ceiling is therefore provably a widening, and
  // nothing the user stores here may loosen the ceiling (FR-01 boundary).
  if (result.lockedByAdministrator && !option.lockedByAdministrator) {
    return {
      status: 'refused', code: 'SANDBOX_CONFIG_CONFLICT',
      message: `“${option.optionId}”比管理员锁定的“${lockedOptionLabel(result)}”更宽松，普通设置页不能放宽`,
      suggestion: '保持或收紧当前意图；放宽只能由管理员受控入口发起',
    }
  }
  return { status: 'applied', optionId: option.optionId }
}

function lockedOptionLabel(result: SandboxDescribeResult): string {
  return result.options.find(option => option.lockedByAdministrator)?.optionId ?? '管理员上限'
}

/** Whether a row is read-only, and the single announced reason for it. */
export function sandboxRowDisablement(
  state: SandboxRegionState, option: SandboxOption,
): { readonly disabled: boolean; readonly reason: string } {
  if (state.kind !== 'ready') return { disabled: true, reason: sandboxRegionUnavailableReason(state) }
  if (option.status === 'unsupported') return { disabled: true, reason: `原生配置面不支持：${option.source}` }
  if (option.status === 'unknown') return { disabled: true, reason: `无法证明生效：${option.source}` }
  if (option.lockedByAdministrator) return { disabled: true, reason: '该项由组织/宿主限制，只能在管理员受控入口修改' }
  if (state.result.lockedByAdministrator) {
    return { disabled: true, reason: '比管理员锁定项更宽松，放宽会被拒绝（该项由组织/宿主限制）' }
  }
  return { disabled: false, reason: '' }
}

export function sandboxRegionUnavailableReason(state: SandboxRegionState): string {
  if (state.kind === 'provider-error') return sandboxCopy.providerError(state.code)
  if (state.kind === 'unknown-pin') return sandboxCopy.unknownPin
  return '原生隔离当前没有可显示的选项'
}

/**
 * Coverage wording. A verified cell is shown as the *measured* categories only;
 * the sentence never widens to "all tools" / "fully isolated", which is the
 * Bash-only counter-example in verification.md gate 6.
 */
export function sandboxCoverageText(option: SandboxOption): string {
  if (option.coverage.length === 0) return '无实测覆盖：未证实任何工具类别被原生隔离'
  return `仅覆盖已实测的工具类别：${option.coverage.join('、')}；未列出的类别不在该原生隔离范围内`
}

/** Wording lives in one place so the copy rules are checkable, not implied. */
export const sandboxCopy = {
  /** Present but failing: a local error. The wording never speaks of
   * installation at all, because this branch is not the "not installed" one. */
  providerError: (code: SandboxErrorCode) =>
    `Harness 原生隔离当前不可用（${code}）：后端服务在场，但本次读取该 Harness 的原生能力时失败。`,
  unknownPin: '后端未提供该 Harness pin 的原生隔离选项：此处不提供任何候选，也不回退到其他品牌的菜单。',
  regionDescription: '以下选项与覆盖范围只来自后端对该 Harness 当前 pin 的实测描述，不代表跨品牌等价。',
  applied: (optionId: string) => `已记录意图：${optionId}（仍需后端在下一提交闸门重新验证）`,
  refused: (outcome: Extract<SandboxSelectionOutcome, { status: 'refused' }>) =>
    `拒绝：${outcome.message}（${outcome.code}）建议：${outcome.suggestion}`,
} as const

export interface SandboxSettingsSnapshot {
  readonly state: SandboxRegionState
  /** Bumped by every describe; a click carrying an older generation is stale. */
  readonly generation: number
  readonly draft: { optionId: string } | undefined
  readonly lastOutcome: SandboxSelectionOutcome | undefined
  readonly registered: boolean
}

export interface SandboxSettingsRegion extends IDisposable {
  readonly sectionId: string
  readonly drafts: SandboxDraftStore
  /** The exact object handed to `addSettingsSection`; tests read the view off it. */
  readonly section: WorkbenchSettingsSection
  readonly registered: boolean
  getSnapshot(): SandboxSettingsSnapshot
  subscribe(listener: () => void): () => void
  select(optionId: string, observedGeneration?: number): Promise<SandboxSelectionOutcome>
  refresh(): Promise<SandboxRegionState>
  /** UI-level hide: drops the contribution only; drafts are untouched. */
  hide(): void
  /** Re-show: re-reads the backend rather than trusting cached availability. */
  show(): Promise<SandboxRegionState>
}

export interface SandboxSettingsRegionDeps {
  host: SandboxSettingsHost
  transport: SandboxDescribeTransport
  request: SandboxDescribeRequest
  drafts: SandboxDraftStore
  order?: number
}

/**
 * Register the region against the real composition seam. The section is added
 * only after describe says there is something to show, so an absent provider
 * leaves no broken placeholder in the Settings page.
 */
export async function createSandboxSettingsRegion(
  deps: SandboxSettingsRegionDeps,
): Promise<SandboxSettingsRegion> {
  const { host, transport, request, drafts } = deps
  let state = await resolveSandboxRegionState(transport, request)
  let generation = 1
  let lastOutcome: SandboxSelectionOutcome | undefined
  let registration: IDisposable | undefined
  let disposed = false
  const listeners = new Set<() => void>()

  const detach = () => { registration?.dispose(); registration = undefined }
  const buildSnapshot = (): SandboxSettingsSnapshot => ({
    state, generation, draft: drafts.read(request.harnessId), lastOutcome, registered: registration !== undefined,
  })
  // useSyncExternalStore compares by identity, so the snapshot is rebuilt only
  // when something actually changed.
  let snapshot = buildSnapshot()
  const publish = () => {
    snapshot = buildSnapshot()
    for (const listener of [...listeners]) listener()
  }
  const attach = () => {
    if (registration !== undefined || !isSandboxRegionVisible(state)) return
    registration = host.addSettingsSection(region.section)
  }
  const reload = async (): Promise<SandboxRegionState> => {
    state = await resolveSandboxRegionState(transport, request)
    generation += 1
    if (isSandboxRegionVisible(state)) attach()
    else detach()
    publish()
    return state
  }

  const region: SandboxSettingsRegion = {
    sectionId: SANDBOX_SETTINGS_SECTION_ID,
    drafts,
    section: {
      id: SANDBOX_SETTINGS_SECTION_ID,
      title: SANDBOX_SETTINGS_SECTION_TITLE,
      order: deps.order ?? 30,
      component: () => createElement(SandboxSettingsSectionView, { region }),
    },
    get registered() { return registration !== undefined },
    getSnapshot: () => snapshot,
    subscribe(listener) {
      listeners.add(listener)
      return () => { listeners.delete(listener) }
    },
    async select(optionId, observedGeneration) {
      if (observedGeneration !== undefined && observedGeneration !== generation) {
        lastOutcome = {
          status: 'refused', code: 'PROVIDER_BUSY',
          message: `这次点击针对的是第 ${observedGeneration} 次描述结果，当前已是第 ${generation} 次，未落到新状态`,
          suggestion: '请按当前显示的内容重新确认',
        }
      } else {
        lastOutcome = evaluateSandboxSelection(state, optionId)
      }
      // A refusal stores nothing: no silent downgrade to the locked value, and
      // no draft written from an answer the backend never gave.
      if (lastOutcome.status === 'applied') drafts.write(request.harnessId, { optionId: lastOutcome.optionId })
      publish()
      return lastOutcome
    },
    refresh: reload,
    hide() { detach(); publish() },
    show: reload,
    dispose() {
      detach()
      listeners.clear()
      disposed = true
    },
    get isDisposed() { return disposed },
  }
  attach()
  publish()
  return region
}
