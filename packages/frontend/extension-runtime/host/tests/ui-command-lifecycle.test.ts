import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createCommandSource } from '../src/services/commands'

describe('UI01 single command contribution lifecycle', () => {
  it('rejects duplicate live identities without replacing the first handler', async () => {
    const source = createCommandSource({}), a = new OwnedResources(), b = new OwnedResources()
    let first = 0, second = 0
    source.forScope(a).add({ id: 'neutral.edit', title: 'A', run: () => { first++ } })
    expect(() => source.forScope(b).add({ id: 'neutral.edit', title: 'B', run: () => { second++ } })).toThrow()
    await expect(source.execute('neutral.edit')).resolves.toMatchObject({ kind: 'Accepted' })
    expect([first, second]).toEqual([1, 0])
    a.dispose(); b.dispose()
  })

  it('scope exit removes the contribution and rejects registration into a closed scope', async () => {
    const source = createCommandSource({}), scope = new OwnedResources()
    let effects = 0
    const handle = source.forScope(scope).add({ id: 'neutral.edit', title: 'A', run: () => { effects++ } })
    scope.dispose()
    expect(handle.isDisposed).toBe(true)
    expect(source.getSnapshot()).toEqual([])
    await expect(source.execute('neutral.edit')).resolves.toMatchObject({ kind: 'Refused', reason: 'command-absent' })
    expect(() => source.forScope(scope).add({ id: 'neutral.other', title: 'B', run: () => {} })).toThrow()
    expect(effects).toBe(0)
  })

  it('a late old handle cannot retire a replacement contribution', async () => {
    const source = createCommandSource({}), a = new OwnedResources(), b = new OwnedResources()
    let replacement = 0
    const old = source.forScope(a).add({ id: 'neutral.edit', title: 'A', run: () => {} })
    source.unload('neutral.edit')
    const current = source.forScope(b).add({ id: 'neutral.edit', title: 'B', run: () => { replacement++ } })
    old.dispose()
    await expect(source.execute('neutral.edit')).resolves.toMatchObject({ kind: 'Accepted' })
    expect(replacement).toBe(1)
    current.dispose()
    expect(source.getSnapshot()).toEqual([])
    a.dispose(); b.dispose()
  })

  it('captured menus reject replaced identity and recheck current availability', async () => {
    let allowed = true
    const source = createCommandSource({ context: () => ({ allowed }) }), a = new OwnedResources(), b = new OwnedResources()
    let effects = 0
    source.forScope(a).add({ id: 'neutral.edit', title: 'A', when: 'allowed', run: () => { effects++ } })
    const captured = (source as typeof source & { capture(id: string): { execute(): Promise<unknown> } }).capture('neutral.edit')
    allowed = false
    await expect(captured.execute()).resolves.toMatchObject({ kind: 'Refused', reason: 'command-unavailable' })
    allowed = true
    a.dispose()
    source.forScope(b).add({ id: 'neutral.edit', title: 'B', run: () => { effects++ } })
    await expect(captured.execute()).resolves.toMatchObject({ kind: 'Refused', reason: 'command-stale' })
    expect(effects).toBe(0)
    b.dispose()
  })
})
