/**
 * 更新客户端对接面（PA-13）。**更新引擎归 P-C**：清单 / 签名 / 下载 / 校验 / 备份 /
 * 故障门 / `pkexec dpkg -i` 一律不在本文件。本文件只有两件事：
 *   1. `UpdateClient` 接口——P-C 交付的可调用入口形状（设置页 UI 与主进程按它接线）；
 *   2. 一个**明确标注的受控 fixture**，用于在 P-C 交付前开发与测试。
 * 切换点：主进程构造处换成 P-C 的实现即可，UI 与 IPC 不变。
 */
import type { Fault } from '@extensions/ordessa.contracts/contract.js'

export type UpdateState =
  | { readonly state: 'idle' }
  | { readonly state: 'checking' }
  | { readonly state: 'up-to-date'; readonly current: string }
  | { readonly state: 'available'; readonly version: string; readonly notes?: string }
  | { readonly state: 'downloading'; readonly version: string; readonly received: number; readonly total: number }
  | { readonly state: 'ready-to-install'; readonly version: string }
  | { readonly state: 'failed'; readonly reason: string; readonly fault?: Fault }
  | { readonly state: 'restart-required'; readonly version: string }

export interface UpdateClient {
  /** 检查更新。源不可达必须失败，**不得**静默当成"已是最新"（FR-075）。 */
  check(): Promise<UpdateState>
  /** 下载 + 校验（引擎在 P-C）；进度经 subscribe 汇报。 */
  download(): Promise<UpdateState>
  /** 安装并返回是否需要重启；重启由主进程生命周期执行。 */
  apply(): Promise<UpdateState>
  /** 主进程在退出前调用：落盘 `backups/update-state.json` 的阶段推进。 */
  snapshot(): UpdateState
  subscribe(listener: (state: UpdateState) => void): () => void
  dispose(): void
}

/**
 * 受控 fixture：确定性的状态机，**不联网、不下载、不提权**。
 * 它复刻的是 P-C 入口的**可观察语义**，不是引擎本身。
 */
export function createFixtureUpdateClient({
  available = '0.2.0', current = '0.1.0', sourceReachable = true, failAt = null as null | 'download' | 'apply',
}: { available?: string; current?: string; sourceReachable?: boolean; failAt?: 'download' | 'apply' | null } = {}): UpdateClient {
  let state: UpdateState = { state: 'idle' }
  const listeners = new Set<(state: UpdateState) => void>()
  const publish = (next: UpdateState) => { state = next; listeners.forEach(listener => listener(next)) }
  return {
    async check() {
      publish({ state: 'checking' })
      if (!sourceReachable) {
        publish({ state: 'failed', reason: '更新源不可达', fault: { kind: 'update-source-unreachable', reason: '无法连接更新源，已保留当前版本', remedy: '检查网络后重试', logRef: 'update:check' } })
        return state
      }
      publish(available === current ? { state: 'up-to-date', current } : { state: 'available', version: available })
      return state
    },
    async download() {
      if (state.state !== 'available') return state
      publish({ state: 'downloading', version: available, received: 0, total: 100 })
      if (failAt === 'download') { publish({ state: 'failed', reason: '下载校验失败，旧版本已保留' }); return state }
      publish({ state: 'ready-to-install', version: available })
      return state
    },
    async apply() {
      if (state.state !== 'ready-to-install') return state
      if (failAt === 'apply') { publish({ state: 'failed', reason: '安装失败，已回退到旧版本' }); return state }
      publish({ state: 'restart-required', version: available })
      return state
    },
    snapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    dispose() { listeners.clear() },
  }
}
