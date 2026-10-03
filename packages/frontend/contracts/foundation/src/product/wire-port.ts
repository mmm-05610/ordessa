/**
 * C-03 — wire 传输口（WirePort）类型载体。定义方 P-B，消费方插件 / P-A。
 *
 * 契约文本：`specs/013-desktop-product/contracts/C-03-wire-port.md`（冻结，只读）。
 * 本文件**只**把冻结契约落成 TS 类型；方法名、参数由调用方给出，宿主不枚举业务方法
 * （C-03 §2），因此本文件内不得出现任何品牌名、Profile 字段或模型字段。
 */

/** 类型化原因（C-03 §7，可扩展）。 */
export type WireReason =
  | 'host-not-ready'
  | 'port-absent'
  | 'transport-unreachable'
  | 'server-refused'
  | 'result-unknown'
  | 'invalid-method'

/** 三态结果（C-03 §2/§3）。绝不抛裸异常，`Unknown` 不得折叠成 `Refused`。 */
export type WireResult =
  | { readonly kind: 'Accepted'; readonly requestId: string; readonly result: Readonly<Record<string, unknown>> }
  | { readonly kind: 'Refused'; readonly requestId: string; readonly reason: string; readonly retryable: boolean }
  | { readonly kind: 'Unknown'; readonly requestId: string; readonly reason: string }

export interface WirePort {
  /** 宿主是否就绪（Server 未起 / 令牌缺席时为 false）。只读事实。 */
  readonly ready: boolean
  /** 只读的 Server 实例范围（origin|serverId 形态），不含令牌。 */
  readonly scope: string | null
  call(method: string, params: Readonly<Record<string, unknown>>): Promise<WireResult>
}

/**
 * 宿主未提供传输口时的缺席实现（C-03 §6）：`call()` 恒 `Unknown/port-absent`，
 * 不崩、不假绿。它是**类型**层面的缺席，宿主运行时也必须注入同一个行为。
 */
export interface AbsentWirePort extends WirePort {
  readonly ready: false
  readonly scope: null
}
