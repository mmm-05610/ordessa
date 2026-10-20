/** C-08 host-side absence and controlled-fixture semantics. */
import type { AbsentHarnessAvailability, HarnessAvailability, HarnessReport, HarnessState } from './harness-availability'

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
 * available 不得带 reason；其他状态必须带 reason。矛盾报告降级为
 * unknown/invariant-violation 并保留其余字段。
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
  /** 让探测挂起的毫秒数（> 超时上限即触发 inspect-timeout）。 */
  readonly delayMs?: number
  /** 故意违反不变量（反例注入用）。 */
  readonly breakInvariant?: boolean
}

export interface FixtureHarnessOptions {
  readonly brands: readonly FixtureBrandSpec[]
  readonly timeoutMs?: number
  /** 只报告已安装品牌；未安装的一律 not-installed。 */
  readonly installed?: readonly string[]
  readonly now?: () => Date
}

/**
 * 确定性的本地 fixture，不 spawn 进程，也不探测真实安装；只复刻
 * C-08 可观察状态、不变量和有界语义。
 */
export function createFixtureHarnessAvailability({ brands, timeoutMs = INSPECT_TIMEOUT_MS, installed, now = () => new Date() }: FixtureHarnessOptions): HarnessAvailability {
  const reports = (): HarnessReport[] => brands.map(spec => {
    const isInstalled = installed ? installed.includes(spec.brand) : spec.state !== 'not-installed'
    if ((spec.delayMs ?? 0) > timeoutMs) {
      return { brand: spec.brand, state: 'unknown' as HarnessState, reason: 'inspect-timeout', observedAt: now().toISOString() }
    }
    const state = spec.breakInvariant ? spec.state : (isInstalled ? spec.state : 'not-installed')
    return enforceReportInvariant({
      brand: spec.brand,
      state,
      ...(isInstalled || spec.breakInvariant ? {} : { reason: 'not-installed-on-this-machine' }),
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
      return found ?? { brand, state: 'unknown' as HarnessState, reason: 'unknown-brand', observedAt: now().toISOString() }
    },
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
  }
}

/** 超时返回空结果，绝不把挂起探测冒充为 available。 */
export async function inspectBounded(availability: HarnessAvailability, timeoutMs = INSPECT_TIMEOUT_MS): Promise<readonly HarnessReport[]> {
  return Promise.race([
    availability.inspect(),
    new Promise<readonly HarnessReport[]>(resolve => setTimeout(() => resolve([]), timeoutMs)),
  ])
}
