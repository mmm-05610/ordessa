/**
 * C-08 — Harness 可用性类型载体。定义方 P-B（契约）/ Harness 插件（实现），消费方 P-A（渲染）。
 * 契约文本：`specs/013-desktop-product/contracts/C-08-harness-availability.md`（冻结，只读）。
 *
 * 品牌差异属 Harness 适配层：本文件**不得**出现任何品牌名（constitution 1 / C-08 §6.6）。
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
  /**
   * 是否**真的有提供者**。C-08 §3/§4：缺席与"有提供者但列表为空"必须能被 UI 区分，
   * 空列表不得冒充"没有 Harness"。
   */
  readonly provided: boolean
  /** 返回全部已知 Harness 的可用性报告。永不抛异常。 */
  inspect(): Promise<readonly HarnessReport[]>
  inspectOne(brand: string): Promise<HarnessReport>
  subscribe(listener: (report: readonly HarnessReport[]) => void): () => void
}

/** 宿主未就绪 / 无 Harness 插件时的缺席呈现（C-08 §4）：不假定全部可用。 */
export interface AbsentHarnessAvailability extends HarnessAvailability {
  readonly provided: false
  inspect(): Promise<readonly HarnessReport[]>
}
