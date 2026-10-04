import { expect, it } from 'vitest'
import { runtime } from '@ordessa/extension-host'
import { createCommandSource } from '@ordessa/extension-host/platform'
import { CommandsToken, CommandSourceToken, type Commands, type C07 } from '@extensions/ordessa.contracts/contract.js'
import commandsPlugin from '../../../../plugins/commands/src/entry'

it('production requires the existing host owner rather than constructing another bus on absence', async () => {
  const app = runtime([commandsPlugin()])
  await expect(app.activate('ordessa.commands')).rejects.toThrow('No provider for: ordessa.commandSource.v1')
  expect(app.getSnapshot().find(item => item.id === 'ordessa.commands')?.phase).toBe('failed')
})

it('real plugin activation registers into the host instance and unload only revokes its own contribution', async () => {
  const source = createCommandSource({})
  let legacy: Commands | undefined, actual: C07.CommandSource | undefined, effects = 0
  const app = runtime([commandsPlugin(), {
    id: 'neutral.consumer', requires: [CommandsToken, CommandSourceToken],
    activate(context, commands: Commands, owner: C07.CommandSource) {
      legacy = commands; actual = owner
      commands.forScope(context.resources).add({ id: 'neutral.action', title: 'Neutral', execute() { effects++; return 'original-value' } })
    },
  }], { commands: source })
  await app.activate('neutral.consumer')
  expect(actual).toBe(source)
  expect(source.getSnapshot().map(item => item.id)).toEqual(['neutral.action'])
  const snapshot = legacy!.getSnapshot()
  expect(legacy!.getSnapshot()).toBe(snapshot)
  await expect(legacy!.execute('neutral.action')).resolves.toEqual({ ok: true, value: 'original-value' })
  await expect(source.execute('neutral.action')).resolves.toMatchObject({ kind: 'Accepted', value: 'original-value' })
  expect(effects).toBe(2)
  await app.deactivate('neutral.consumer')
  expect(source.getSnapshot()).toEqual([])
  await expect(source.execute('neutral.action')).resolves.toMatchObject({ kind: 'Refused' })
  expect(effects).toBe(2)
  await app.deactivate('ordessa.commands')
})
