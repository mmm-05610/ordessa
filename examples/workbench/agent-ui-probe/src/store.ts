// Controlled service fixture, NOT a production session protocol or agent runner.
// No assistant-ui types escape into the service-facing data.
export type Message = {
  id: string; role: 'user' | 'assistant'; text: string;
  state?: 'running' | 'done' | 'cancelled' | 'error';
  tool?: { id: string; name: string; args: Record<string, string>; result?: string };
}
export type Snapshot = { session: string; messages: readonly Message[]; running: boolean }
export function createFixture() {
  const history = (): Message[] => [
    { id: 'old-user', role: 'user', text: '历史问题' },
    { id: 'old-agent', role: 'assistant', text: '恢复的历史回答', state: 'done' },
  ]
  let snapshot: Snapshot = { session: 'A', messages: history(), running: false }
  const sessions = new Map<string, readonly Message[]>([['A', snapshot.messages], ['B', []]])
  const listeners = new Set<() => void>()
  let generation = 0, active: { generation: number; session: string; id: string } | undefined
  let disposed = false
  const publish = (next: Snapshot) => {
    if (disposed) return
    snapshot = next; sessions.set(next.session, next.messages); listeners.forEach(fn => fn())
  }
  const begin = async (text: string) => {
    if (disposed || active || !text.trim()) return
    const id = `reply-${++generation}`
    active = { generation, session: snapshot.session, id }
    publish({ ...snapshot, running: true, messages: [...snapshot.messages,
      { id: `user-${generation}`, role: 'user', text }, { id, role: 'assistant', text: '', state: 'running' }] })
  }
  const receive = (token: number, patch: Partial<Pick<Message, 'text' | 'tool' | 'state'>>) => {
    if (disposed || !active || active.generation !== token || active.session !== snapshot.session) return false
    const id = active.id
    const terminal = patch.state && patch.state !== 'running'
    if (terminal) active = undefined
    publish({ ...snapshot, running: !terminal, messages: snapshot.messages.map(m => m.id === id ? { ...m, ...patch } : m) })
    return true
  }
  const cancel = async () => { if (active) receive(active.generation, { state: 'cancelled' }) }
  return {
    get isDisposed() { return disposed },
    subscribe: (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn) } },
    getSnapshot: () => snapshot,
    begin, cancel, receive,
    token: () => active?.generation ?? generation,
    switchSession: (session: string) => {
      if (disposed || session === snapshot.session) return
      // Fixture acknowledges cancellation synchronously. Real transports must not assume that.
      void cancel(); generation++
      publish({ session, messages: sessions.get(session) ?? [], running: false })
    },
    dispose: () => { disposed = true; active = undefined; listeners.clear() },
  }
}
export type Fixture = ReturnType<typeof createFixture>
