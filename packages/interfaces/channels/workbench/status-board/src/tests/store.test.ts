import { describe, it, expect } from 'vitest'
import { BoardStore } from '../state/store'
import { QueryClient } from '@ordessa/system-access-client'
import type { BoardSnapshot } from '../contracts/client'
const snapshot = (): BoardSnapshot => ({ revision: 'r1', scope: 'project', works: [{ id: 'w1', version: 'v1', scope: 'cross-directory', title: '工作', phase: 'result', status: '执行结束，待验收', change: '变化', basis: [], review: [], approval: [], execution: [], evidence: [] }], structure: [] })
describe('authority and transport lifecycle', () => {
  it('does not turn unavailable queries into empty success', async () => {
    const store = new BoardStore(); await store.refresh()
    expect(store.getSnapshot().data).toBeUndefined(); expect(store.getSnapshot().stale).toBe(true)
    await expect(store.confirm('w1','v1','project','r1')).rejects.toThrow('尚未接通')
  })
  it('preserves data and last update on disconnect and recovers', async () => {
    let offline = false
    const store = new BoardStore({ read: async () => { if (offline) throw Error('disconnect'); return snapshot() } })
    await store.refresh(); const time = store.getSnapshot().lastUpdated
    offline = true; await store.refresh()
    expect(store.getSnapshot().data?.works[0].status).toContain('待验收'); expect(store.getSnapshot().lastUpdated).toBe(time); expect(store.getSnapshot().stale).toBe(true)
    offline = false; await store.refresh(); expect(store.getSnapshot().stale).toBe(false)
  })
  it('coalesces repeated refreshes and reports subscription updates', async () => {
    let count = 0, finish!: (s: BoardSnapshot) => void, notifications = 0
    const store = new BoardStore({ read: () => { count++; return new Promise(resolve => { finish = resolve }) } })
    const off = store.subscribe(() => notifications++)
    const a = store.refresh(), b = store.refresh(); expect(a).toBe(b); expect(count).toBe(1)
    finish(snapshot()); await a; expect(notifications).toBe(2); off()
  })
  it('rejects stale versions, scopes and revisions before invoking confirmation', async () => {
    let data = snapshot(), calls = 0
    const store = new BoardStore({ read: async () => data, confirm: async () => { calls++ } })
    await store.refresh(); data = { ...data, revision: 'r2' }
    await expect(store.confirm('w1','v1','cross-directory','r1')).rejects.toThrow('已变化')
    await expect(store.confirm('w1','v0','cross-directory','r2')).rejects.toThrow('已变化')
    await expect(store.confirm('w1','v1','wrong-scope','r2')).rejects.toThrow('已变化')
    expect(calls).toBe(0)
  })
  it('refuses confirmation when refresh loses connectivity', async () => {
    let offline = false, calls = 0
    const store = new BoardStore({ read: async () => { if (offline) throw Error(); return snapshot() }, confirm: async () => { calls++ } })
    await store.refresh(); offline = true
    await expect(store.confirm('w1','v1','cross-directory','r1')).rejects.toThrow('已变化'); expect(calls).toBe(0)
  })
  it('blocks duplicate confirmation and sends the exact version and scope', async () => {
    let finish!: () => void, sent: unknown
    const store = new BoardStore({ read: async () => snapshot(), confirm: request => { sent = request; return new Promise<void>(resolve => { finish = resolve }) } })
    await store.refresh(); const first = store.confirm('w1','v1','cross-directory','r1')
    await expect(store.confirm('w1','v1','cross-directory','r1')).rejects.toThrow('重复')
    await Promise.resolve(); expect(sent).toEqual({ id: 'w1', version: 'v1', scope: 'cross-directory', snapshotRevision: 'r1' }); finish(); await first
  })
  it('query client preserves accepted reply through unknown and recovers', async () => {
    let offline = false
    const client = new QueryClient({ call: async () => offline ? { kind: 'Unknown', requestId: '2', reason: 'result-unknown' } : { kind: 'Accepted', requestId: '1', result: { serverId: 'real-server', capabilities: [] } } }, 'server.hello')
    await client.refresh(); const time = client.getSnapshot().lastUpdated; offline = true; await client.refresh()
    expect(client.getSnapshot().data?.serverId).toBe('real-server'); expect(client.getSnapshot().lastUpdated).toBe(time); expect(client.getSnapshot().stale).toBe(true)
    offline = false; await client.refresh(); expect(client.getSnapshot().stale).toBe(false)
  })
})
