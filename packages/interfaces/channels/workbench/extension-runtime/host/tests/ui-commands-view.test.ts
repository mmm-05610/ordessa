import { afterEach, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import { createCommandSource } from '../src/services/commands'
import { createCommandsView } from '@ordessa/extension-runtime/commands-view'

const scopes: OwnedResources[] = []
afterEach(() => { for (const scope of scopes.splice(0).reverse()) scope.dispose() })

function ownedScope() {
  const scope = new OwnedResources()
  scopes.push(scope)
  return scope
}

it('routes legacy and C07 registration/execution through one source and preserves handler values', async () => {
  const source = createCommandSource({})
  const legacy = createCommandsView(source)
  const scope = ownedScope()
  const returned = Object.freeze({ answer: 42 })
  let calls = 0
  const changes: string[][] = []
  const unsubscribe = legacy.subscribe(() => changes.push(legacy.getSnapshot().map(command => command.id)))

  legacy.forScope(scope).add({ id: 'shared.action', title: 'Shared action', execute() { calls += 1; return returned } })
  expect(source.getSnapshot().map(command => command.id)).toEqual(['shared.action'])
  expect(legacy.getSnapshot()).toEqual([{ id: 'shared.action', title: 'Shared action' }])
  expect(changes).toEqual([['shared.action']])

  const legacyResult = await legacy.execute('shared.action')
  const c07Result = await source.execute('shared.action')
  expect(legacyResult).toEqual({ ok: true, value: returned })
  expect(c07Result).toEqual({ kind: 'Accepted', commandId: 'shared.action', value: returned })
  expect(calls).toBe(2)
  unsubscribe()
})

it('uses the source registration handle for exact scope revocation', () => {
  const source = createCommandSource({})
  const legacy = createCommandsView(source)
  const scope = ownedScope()
  legacy.forScope(scope).add({ id: 'scope.action', title: 'Scoped', execute() {} })
  expect(source.getSnapshot().map(command => command.id)).toEqual(['scope.action'])

  scope.dispose()
  expect(source.getSnapshot()).toEqual([])
  expect(legacy.getSnapshot()).toEqual([])
})

it('lets the single C07 owner reject duplicate ids across both entry surfaces', () => {
  const source = createCommandSource({})
  const legacy = createCommandsView(source)
  const first = ownedScope(), second = ownedScope()
  source.forScope(first).add({ id: 'duplicate.action', title: 'First', run() {} })
  expect(() => legacy.forScope(second).add({ id: 'duplicate.action', title: 'Second', execute() {} }))
    .toThrow(/duplicate/i)
  expect(source.getSnapshot().map(command => command.title)).toEqual(['First'])
})

it('maps C07 Unknown into a legacy error result without inventing success', async () => {
  const source = createCommandSource({ context: () => ({ hostReady: false }) })
  const legacy = createCommandsView(source)
  expect(await legacy.execute('not.ready')).toEqual({ ok: false, error: 'host-not-ready' })
})
