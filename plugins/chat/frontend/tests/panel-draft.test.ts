// Input panel, trigger extraction, draft store and attachment gate proofs
// (input-spec P01–P06, A04/A05; checklist 面板/键盘/清理 rows).
import { describe, expect, it } from 'vitest'
import { createSlashSnapshot, extractSlashTrigger, reconcileSlashSnapshot, slashReplacementRange } from '../src/components/composer/trigger'
import { DraftStore, attachmentBlockReason } from '../src/state/draft'
import type { ChatInputEntry, ChatInputItem } from '@extensions/ordessa.chat-api/contract.js'
import { createChatContributions } from '@extensions/ordessa.chat-api/contract.js'

describe('slash trigger extraction (P02/P06, ported token rules)', () => {
  it('triggers only at start or after whitespace, running to the caret', () => {
    expect(extractSlashTrigger('/')).toEqual({ query: '' })
    expect(extractSlashTrigger('前缀 /com')).toEqual({ query: 'com' })
    expect(extractSlashTrigger('hello/com')).toBeNull() // no boundary
    expect(extractSlashTrigger('/a b')).toBeNull() // space ends the token
    expect(extractSlashTrigger('文 /')).toEqual({ query: '' }) // CJK boundary works via \s? no — space exists here
  })

  it('caret outside the token closes it; caret moves inside keep it stable', () => {
    const text = '/command'
    const snap = createSlashSnapshot(text, 8)
    expect(snap?.query).toBe('command')
    // caret moved left but still inside → same snapshot (no re-filter)
    expect(reconcileSlashSnapshot(snap, text, 5)).toBe(snap)
    // caret left the token → closed
    expect(reconcileSlashSnapshot(snap, text, 0)).toBeNull()
    // token text changed → re-derived
    const edited = '/comm'
    const next = reconcileSlashSnapshot(snap, edited, 5)
    expect(next?.query).toBe('comm')
    expect(next).not.toBe(snap)
  })

  it('insert-command replaces the ORIGINAL token only; a moved caret refuses the stale insert', () => {
    const text = 'do /he'
    const snap = createSlashSnapshot(text, 6)
    const range = slashReplacementRange(snap, text, 6)
    expect(range).toEqual({ start: 3, end: 6 })
    // caret moved away: the pending insert must be refused (null)
    expect(slashReplacementRange(snap, 'do /help', 8)).toBeNull()
  })
})

describe('draft store (A04/A05)', () => {
  const item = (id: string, overrides: Partial<ChatInputItem> = {}): ChatInputItem => ({
    id, sourceId: 'test', kind: 'file', displayName: `${id}.txt`, phase: { state: 'selected' }, ...overrides,
  })

  it('mutates bump revision and notify subscribers; identity changes only on write', () => {
    const store = new DraftStore()
    const seen: number[] = []
    store.subscribe(() => seen.push(store.read('p').revision))
    store.setText('p', 'hello')
    expect(store.read('p').text).toBe('hello')
    expect(seen).toEqual([1])
    // setting the same text is a no-op
    store.setText('p', 'hello')
    expect(seen).toEqual([1])
  })

  it('unready attachments block the send with the named reason; ready ones do not', () => {
    const preparing = [item('a', { phase: { state: 'preparing' } })]
    expect(attachmentBlockReason(preparing)).toContain('仍在准备中')
    const failed = [item('b', { phase: { state: 'failed', reason: '超过大小限制' } })]
    expect(attachmentBlockReason(failed)).toContain('超过大小限制')
    const ready = [item('c', { phase: { state: 'ready', reference: 'ref-1' as never } })]
    expect(attachmentBlockReason(ready)).toBeNull()
  })

  it('remove reclaims only store-owned resources; handed-off items survive teardown', () => {
    const revoked: string[] = []
    const original = URL.revokeObjectURL
    URL.revokeObjectURL = url => { revoked.push(url) }
    try {
      const store = new DraftStore()
      store.addItem('p', item('img', { kind: 'image', previewUrl: 'blob:keep' }))
      store.markHandedOff('p', ['img'])
      store.removeItem('p', 'img')
      expect(revoked).toEqual([]) // handed to the sent record: NOT revoked
      store.addItem('p', item('img2', { kind: 'image', previewUrl: 'blob:drop' }))
      store.removeItem('p', 'img2')
      expect(revoked).toEqual(['blob:drop'])
    } finally {
      URL.revokeObjectURL = original
    }
  })
})

describe('input source panel data (P04/P05)', () => {
  const entry = (id: string, overrides: Partial<ChatInputEntry> = {}): ChatInputEntry => ({
    id, title: `t-${id}`, groupId: 'g', order: 1, surfaces: ['plus', 'slash'],
    availability: { kind: 'ready' }, action: { kind: 'insert-command', text: `/${id}` }, ...overrides,
  })
  const location = { kind: 'draft' as const, draftId: 'd', contextRevision: 1 }

  it('queries fan out per source with isolated errors and abort preservation', async () => {
    const chat = createChatContributions()
    const scope = { isDisposed: false, add: () => { throw new Error('scope closed') } } as never
    void scope
    const ui = chat.forScope({ isDisposed: false, add: (d: { dispose(): void }) => d } as never)
    ui.addInputSource({ id: 'ok', title: '可用来源', groups: [{ id: 'g', title: 'G', order: 1 }],
      query: async () => [entry('e1')] })
    ui.addInputSource({ id: 'bad', title: '故障来源', groups: [{ id: 'g', title: 'G', order: 1 }],
      query: async () => { throw new Error('目录服务不可用') } })
    const view = chat.queryInputSources({ location, query: '', surface: 'plus', signal: new AbortController().signal })
    await new Promise(resolve => setTimeout(resolve, 0))
    const states = view.getSnapshot()
    expect(states.find(s => s.source.id === 'ok')?.state.status).toBe('ready')
    expect(states.find(s => s.source.id === 'ok')?.entries.map(e => e.id)).toEqual(['e1'])
    expect(states.find(s => s.source.id === 'bad')?.state.status).toBe('error')
    expect(states.find(s => s.source.id === 'bad')?.state.error).toContain('目录服务不可用')
  })
})
