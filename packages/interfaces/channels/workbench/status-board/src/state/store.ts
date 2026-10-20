import type { BoardSource, BoardSnapshot } from '../contracts/client'
export interface BoardState { data?: BoardSnapshot; lastUpdated?: string; stale: boolean; busy: boolean; error?: string }
export class BoardStore {
  private state: BoardState = { stale: true, busy: false }
  private listeners = new Set<() => void>()
  private pending?: Promise<void>
  private confirming = false
  constructor(readonly source?: BoardSource) {}
  getSnapshot = () => this.state
  subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn) } }
  private set(s: BoardState) { this.state = Object.freeze(s); this.listeners.forEach(fn => fn()) }
  refresh = (): Promise<void> => {
    if (this.pending) return this.pending
    if (!this.source) { this.set({ ...this.state, stale: true, error: '工作与目标结构查询尚未接通', busy: false }); return Promise.resolve() }
    this.set({ ...this.state, busy: true })
    this.pending = this.source.read().then(data => {
      this.set({ data: structuredClone(data), lastUpdated: new Date().toISOString(), stale: false, busy: false })
    }, () => { this.set({ ...this.state, stale: true, busy: false, error: '连接中断，保留最后读取内容' }) }).finally(() => { this.pending = undefined })
    return this.pending
  }
  async confirm(id: string, version: string, scope: string, revision: string) {
    if (this.confirming) throw Error('确认正在处理，请勿重复操作')
    if (!this.source?.confirm) throw Error('可信确认尚未接通')
    this.confirming = true
    try {
      await this.refresh()
      const s = this.state, work = s.data?.works.find(w => w.id === id)
      if (s.stale || !work || work.version !== version || work.scope !== scope || s.data?.revision !== revision) throw Error('内容或范围已变化，请重新阅读后确认')
      await this.source.confirm({ id, version, scope, snapshotRevision: revision })
      await this.refresh()
    } finally { this.confirming = false }
  }
}
