import type { WirePort, WireResult } from '@ordessa/interface-contracts'
export type { WirePort, WireResult } from '@ordessa/interface-contracts'
export { HttpWirePort, AbsentWirePort, PendingWirePort } from './wire-port'
export interface QueryState { readonly result?: WireResult; readonly data?: Readonly<Record<string, unknown>>; readonly lastUpdated?: string; readonly stale: boolean; readonly refreshing: boolean }
/** Explicit read query only. No mutation retries, credentials or business projections. */
export class QueryClient {
  private state: QueryState = { stale: true, refreshing: false }
  private listeners = new Set<() => void>()
  private pending?: Promise<void>
  constructor(private port: Pick<WirePort, 'call'>, private method: string, private params: Readonly<Record<string, unknown>> = {}) {}
  getSnapshot = () => this.state
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  private publish(state: QueryState) { this.state = Object.freeze(state); this.listeners.forEach(fn => fn()) }
  refresh = (): Promise<void> => {
    if (this.pending) return this.pending
    this.publish({ ...this.state, refreshing: true })
    this.pending = (async () => {
      let result: WireResult
      try { result = await this.port.call(this.method, this.params) }
      catch { result = { kind: 'Unknown', requestId: 'client', reason: 'transport-unreachable' } }
      if (result.kind === 'Accepted') this.publish({ result, data: result.result, lastUpdated: new Date().toISOString(), stale: false, refreshing: false })
      else this.publish({ ...this.state, result, stale: true, refreshing: false })
    })().finally(() => { this.pending = undefined })
    return this.pending
  }
}
