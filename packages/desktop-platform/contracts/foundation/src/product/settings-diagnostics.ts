/**
 * C-06 — 设置分区与诊断贡献类型载体。定义方 P-A，消费方插件。
 * 契约文本：`specs/013-desktop-product/contracts/C-06-settings-diagnostics.md`（冻结，只读）。
 */

import type { ComponentType } from 'react'

// --- A. 设置分区 ------------------------------------------------------------

export type SettingsItemKind = 'string' | 'number' | 'boolean' | 'enum' | 'secret-ref'

export interface SettingsItemDescriptor {
  readonly id: string
  readonly kind: SettingsItemKind
  readonly label: string
  readonly description?: string
  readonly default?: unknown
  readonly enumValues?: readonly string[]
}

export interface SettingsSection {
  /** 稳定 id，如 "ordessa.model-provider"。 */
  readonly id: string
  readonly title: string
  readonly order?: number
  /** 渲染入口：由平台 UI 服务登记（C-05 tokens 可用）。 */
  readonly component: ComponentType
  readonly items?: readonly SettingsItemDescriptor[]
}

export interface SettingsContribution {
  register(section: SettingsSection): () => void
}

// --- B. 诊断贡献 ------------------------------------------------------------

export interface DiagnosticProvider {
  readonly id: string
  /** 纯 JSON 可序列化片段；超时/异常 → 记为 unknown，不阻塞导出。 */
  collect(): Promise<Readonly<Record<string, unknown>>>
}

export interface DiagnosticsContribution {
  register(provider: DiagnosticProvider): () => void
}

/** 片段采集结果的三态（README §1）：provider 缺席/超时不得冒充成功。 */
export type DiagnosticFragment =
  | { readonly id: string; readonly state: 'collected'; readonly data: Readonly<Record<string, unknown>> }
  | { readonly id: string; readonly state: 'unknown'; readonly reason: string }

// --- C. 故障 UI -------------------------------------------------------------

export type FaultKind =
  | 'data-root-missing'
  | 'port-conflict'
  | 'runtime-missing'
  | 'data-root-locked'
  | 'update-source-unreachable'
  | 'update-failed'   // 下载/校验/安装/自检失败：当前版本与数据均未改动（C-09 §C3）
  | 'server-launch-failed'

export interface Fault {
  readonly kind: FaultKind
  /** 人话原因。 */
  readonly reason: string
  /** 可执行下一步。 */
  readonly remedy: string
  /** 指向日志的稳定引用（文件名 + 行号范围，不含完整路径）。 */
  readonly logRef: string
  /** 令牌缺席等 C-01 类型化错误码，仅作稳定标识展示。 */
  readonly code?: string
}
