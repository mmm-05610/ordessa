/**
 * Generic command registry/execute (T008-10): the ONE runtime home for the
 * command service. Keybindings and panels stay organized by the Workbench;
 * business handlers stay in their owning plugins — only the neutral
 * registry/execute mechanism lives here. The historical `ordessa.commands`
 * entry forwards to this same factory (thin forward, one implementation).
 */
import { Contributions, type ResourceScope, type IDisposable } from '@ordessa/extension-api'
import type { Commands, Command } from '@extensions/ordessa.contracts/contract.js'

/** Internal helper, not another host service or dependency scheduler. */
export function registry<T extends { id: string; order?: number }>(lifetime: ResourceScope) {
  const values = lifetime.add(new Contributions<T>())
  return {
    getSnapshot: values.getSnapshot, subscribe: values.subscribe,
    add(scope: ResourceScope, item: T): IDisposable {
      if (scope.isDisposed || lifetime.isDisposed) throw Error('Registration scope is closed')
      if (!item.id.trim()) throw Error('Contribution id is required')
      return scope.add(values.add(Object.freeze({ ...item })))
    },
  }
}

export function ordered<T extends { id: string; order?: number }>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => (a.order ?? 0) - (b.order ?? 0) || a.id.localeCompare(b.id))
}

export function createCommands(lifetime: ResourceScope): Commands {
  const commands = registry<Command>(lifetime)
  return {
    getSnapshot: commands.getSnapshot, subscribe: commands.subscribe,
    forScope: scope => ({ add: command => commands.add(scope, command) }),
    async execute(id) {
      const command = commands.getSnapshot().find(c => c.id === id)
      if (!command || lifetime.isDisposed) return { ok: false, error: `Command unavailable: ${id}` }
      try { return { ok: true, value: await command.execute() } }
      catch (error) { return { ok: false, error: String(error) } }
    },
  }
}
