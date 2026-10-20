/**
 * C-08 — Harness 可用性公共类型。品牌差异属于 Harness 适配层；这些
 * contracts 不执行品牌探测，也不依赖 ACP 或其他运行时内部实现。
 */

export type HarnessState =
  | 'available'
  | 'not-installed'
  | 'not-logged-in'
  | 'unsupported'
  | 'failed'
  | 'unknown'

export interface HarnessReport {
  readonly brand: string
  readonly state: HarnessState
  readonly reason?: string
  readonly remedy?: string
  readonly version?: string
  readonly observedAt: string
}

export interface HarnessAvailability {
  /** 缺席与“有提供者但列表为空”必须能由 UI 区分。 */
  readonly provided: boolean
  /** 返回全部已知 Harness 的可用性报告。永不抛异常。 */
  inspect(): Promise<readonly HarnessReport[]>
  inspectOne(brand: string): Promise<HarnessReport>
  subscribe(listener: (report: readonly HarnessReport[]) => void): () => void
}

/** 宿主未就绪或没有提供者时的诚实缺席形状。 */
export interface AbsentHarnessAvailability extends HarnessAvailability {
  readonly provided: false
  inspect(): Promise<readonly HarnessReport[]>
}
