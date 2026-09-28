/**
 * C-01/C-02/C-03 的**受控 fixture**（PA-21 / PA-22）。
 *
 * ⚠️ 这是 fixture，不是真实现：`packages/desktop-platform/server-bridge` 由 P-B 交付。
 * 它按冻结契约实现三态与缺席语义，且**不 spawn 任何进程、不发任何网络请求**、
 * 不读取也不产生任何令牌。切换点：P-B 交付后，只需把 `createWirePort()` 的
 * 构造换成 server-bridge 的实例，本文件其余部分（渲染进程代理、缺席实现）不变。
 * 登记见 specs/013-desktop-product/dispatch/P-A-report.md §切换点。
 */
import { randomUUID } from 'node:crypto'
import type { AbsentWirePort, WirePort, WireResult } from '@extensions/ordessa.contracts/contract.js'
export type { AbsentWirePort, WirePort, WireResult }

/** C-03 §7 类型化原因。 */
export type WireScenario =
  | { readonly kind: 'ok'; readonly result?: Readonly<Record<string, unknown>> }
  | { readonly kind: 'refused'; readonly reason: string; readonly retryable: boolean }
  | { readonly kind: 'unreachable' }
  | { readonly kind: 'disconnect' }
  | { readonly kind: 'not-ready' }

/** C-03 §7 非法方法名（空/含非法字符）→ `invalid-method`，宿主不枚举业务方法。 */
export const WIRE_METHOD = /^[a-z0-9]+(?:[._-][a-zA-Z0-9]+)*$/

export interface FixtureWireOptions {
  readonly scenario?: WireScenario
  readonly scope?: string | null
  /** 记录调用，用于断言"不自动重发"（C-03 §3）。 */
  readonly calls?: { method: string; params: Readonly<Record<string, unknown>> }[]
}

export function createFixtureWirePort({ scenario = { kind: 'ok' }, scope = 'fixture|server', calls = [] }: FixtureWireOptions = {}): WirePort {
  const port: WirePort = {
    get ready() { return scenario.kind !== 'not-ready' },
    get scope() { return scenario.kind === 'not-ready' ? null : scope },
    async call(method: string, params: Readonly<Record<string, unknown>>): Promise<WireResult> {
      const requestId = randomUUID()
      if (typeof method !== 'string' || !WIRE_METHOD.test(method)) {
        return Object.freeze({ kind: 'Unknown', requestId, reason: 'invalid-method' })
      }
      // 令牌缺席 / Server 未起 / 网络不可达：Unknown，**不**排队、不阻塞 UI（C-03 §5）。
      if (scenario.kind === 'not-ready') return Object.freeze({ kind: 'Unknown', requestId, reason: 'host-not-ready' })
      if (scenario.kind === 'unreachable') return Object.freeze({ kind: 'Unknown', requestId, reason: 'transport-unreachable' })
      calls.push({ method, params }) // 只在真正发出后才记账：断开中途的那次不重发。
      if (scenario.kind === 'disconnect') return Object.freeze({ kind: 'Unknown', requestId, reason: 'result-unknown' })
      if (scenario.kind === 'refused') {
        return Object.freeze({ kind: 'Refused', requestId, reason: scenario.reason, retryable: scenario.retryable })
      }
      return Object.freeze({ kind: 'Accepted', requestId, result: Object.freeze({ ...(scenario.result ?? {}) }) })
    },
  }
  return port
}

/** C-03 §6 缺席传输口：恒 `Unknown/port-absent`，不崩、不假绿。 */
export const createAbsentWirePort = (): AbsentWirePort => Object.freeze({
  ready: false,
  scope: null,
  call: async () => Object.freeze({ kind: 'Unknown', requestId: randomUUID(), reason: 'port-absent' }),
})

/** C-02 的生命周期事实（受控）：宿主据此接线故障 UI，不自己 spawn。 */
export interface ServerLifecycleFact {
  readonly origin: string | null
  readonly ready: boolean
  readonly state: 'absent' | 'starting' | 'ready' | 'failed'
  readonly fault: 'port-conflict' | 'runtime-missing' | 'server-launch-failed' | null
}

export const FIXTURE_LIFECYCLE: ServerLifecycleFact = {
  origin: null, ready: false, state: 'absent', fault: null,
}

export function fixtureLifecycle(fault: ServerLifecycleFact['fault']): ServerLifecycleFact {
  return { origin: null, ready: false, state: fault ? 'failed' : 'absent', fault }
}

/**
 * 渲染进程侧的代理（C-03 §4：令牌只存在于主进程）。
 * 插件与界面拿到的只有 `call/ready/scope` 三个成员，没有 token/tokenFile/origin 字段。
 */
export interface WireBridge { call(method: string, params: Readonly<Record<string, unknown>>): Promise<WireResult>; ready(): Promise<boolean>; scope(): Promise<string | null> }
export function createRendererWirePort(bridge: WireBridge, onError: (error: unknown) => void = () => {}): WirePort {
  return {
    ready: true, // 真实就绪态由 `ready()` 异步给出；同步字段只表示"宿主已提供通道"。
    scope: null,
    async call(method, params) {
      try { return await bridge.call(method, params) }
      catch (error) {
        onError(error)
        return Object.freeze({ kind: 'Unknown', requestId: randomUUID(), reason: 'transport-unreachable' })
      }
    },
  }
}

/** 金丝雀：插件可见面**不得**出现令牌或完整定位符（README §4 / C-03 §4）。 */
export function visibleWireKeys(port: WirePort): string[] { return Object.keys(port).sort() }
