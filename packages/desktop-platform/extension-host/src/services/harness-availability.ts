/**
 * C-08 — Harness 可用性：**类型之外的宿主侧语义**（类型与缺席语义归 P-A/core）。
 *
 * 契约文本：`specs/013-desktop-product/contracts/C-08-harness-availability.md`（冻结，只读）。
 * 实现方（插件/Harness 适配层）**不在本期**：本文件提供
 *   1. 不变量校验（C-08 §1：`state` 与 `reason` 必须一致）；
 *   2. 缺席实现（C-08 §4：无提供者 / 宿主未就绪 → 诚实缺席，不假绿）；
 *   3. 一个**受控 fixture 提供者**，用于在插件线交付前验证 6 态渲染与有界探测。
 *
 * 边界：本文件**不得**出现任何品牌名（C-08 §6.6 / constitution 1）——品牌探测属于适配层。
 */
import type { AbsentHarnessAvailability, HarnessAvailability, HarnessReport, HarnessState } from '@extensions/ordessa.contracts/contract.js'

/** 有界探测的默认上限（C-08 §2）。 */
export const INSPECT_TIMEOUT_MS = 3000

/** 宿主未就绪 / 未提供提供者时的缺席实现（C-08 §4）。 */
export function createAbsentHarnessAvailability(reason = 'host-not-ready'): AbsentHarnessAvailability {
  const observedAt = new Date().toISOString()
  return Object.freeze({
    provided: false,
    inspect: async () => Object.freeze([] as readonly HarnessReport[]),
    inspectOne: async (brand: string) => Object.freeze({ brand, state: 'unknown' as HarnessState, reason, observedAt }),
    subscribe: () => () => undefined,
  })
}

/**
 * 不变量校验：`available` 不得带 `reason`；非 `available` 必须带 `reason`（C-08 §1）。
 * 违反的报告**降级**为 `unknown/invariant-violation` 并保留原值——既不崩，也不假装可用。
 */
export function enforceReportInvariant(report: HarnessReport): { report: HarnessReport; violated: boolean } {
  const reasonPresent = typeof report.reason === 'string' && report.reason.length > 0
  const violated = report.state === 'available' ? reasonPresent : !reasonPresent
  if (!violated) return { report, violated: false }
  return {
    violated: true,
    report: Object.freeze({
      ...report,
      state: 'unknown' as HarnessState,
      reason: `invariant-violation: ${report.state}${reasonPresent ? ' with reason' : ' without reason'}`,
    }),
  }
}

export interface FixtureBrandSpec {
  readonly brand: string
  readonly state: HarnessState
  readonly reason?: string
  readonly remedy?: string
  readonly version?: string
  /** 让探测挂起的毫秒数（> 超时上限即触发 `inspect-timeout`）。 */
  readonly delayMs?: number
  /** 故意违反不变量（反例注入用）。 */
  readonly breakInvariant?: boolean
}

export interface FixtureHarnessOptions {
  readonly brands: readonly FixtureBrandSpec[]
  readonly timeoutMs?: number
  /** 只报告**已安装**的品牌；未安装的一律 `not-installed`（不编造可用）。 */
  readonly installed?: readonly string[]
  readonly now?: () => Date
}

/**
 * 受控 fixture 提供者：**确定性的本地状态机**，不 spawn 任何进程、不探测任何真实安装、
 * 不含任何品牌名。它复刻的是契约的**可观察语义**（6 态 + 不变量 + 有界），不是真实可用性。
 */
export function createFixtureHarnessAvailability({ brands, timeoutMs = INSPECT_TIMEOUT_MS, installed, now = () => new Date() }: FixtureHarnessOptions): HarnessAvailability {
  const reports = (): HarnessReport[] => brands.map(spec => {
    const isInstalled = installed ? installed.includes(spec.brand) : spec.state !== 'not-installed'
    // 有界探测：超过上限的探测一律 `unknown` + `inspect-timeout`，**不**冒充 available。
    if ((spec.delayMs ?? 0) > timeoutMs) {
      return { brand: spec.brand, state: 'unknown' as HarnessState, reason: 'inspect-timeout', observedAt: now().toISOString() }
    }
    const state = spec.breakInvariant ? spec.state : (isInstalled ? spec.state : 'not-installed')
    return enforceReportInvariant({
      brand: spec.brand,
      state,
      ...(isInstalled || spec.breakInvariant ? {} : { reason: 'not-installed-on-this-machine' }),
      // `breakInvariant` 注入的是**真矛盾**：available 硬塞 reason，其余态抹掉 reason。
      ...(spec.breakInvariant ? (state === 'available' ? { reason: 'contradiction-injected' } : { reason: undefined }) : {}),
      ...(spec.reason ? { reason: spec.reason } : {}),
      ...(spec.remedy ? { remedy: spec.remedy } : {}),
      ...(spec.version ? { version: spec.version } : {}),
      observedAt: now().toISOString(),
    } as HarnessReport).report
  })
  const listeners = new Set<(report: readonly HarnessReport[]) => void>()
  return {
    provided: true,
    inspect: async () => reports(),
    inspectOne: async (brand: string) => {
      const found = reports().find(report => report.brand === brand)
      // 未知品牌不得冒充 available：显式 unknown（C-08 §2）。
      return found ?? { brand, state: 'unknown' as HarnessState, reason: 'unknown-brand', observedAt: now().toISOString() }
    },
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
  }
}

/** 有界探测：超时 → `unknown` + `inspect-timeout`，**不**冒充 `available`（C-08 §2）。 */
export async function inspectBounded(availability: HarnessAvailability, timeoutMs = INSPECT_TIMEOUT_MS): Promise<readonly HarnessReport[]> {
  return Promise.race([
    availability.inspect(),
    new Promise<readonly HarnessReport[]>(resolve => setTimeout(() => resolve([]), timeoutMs)),
  ])
}
