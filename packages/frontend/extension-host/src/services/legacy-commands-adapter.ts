import type { Commands, Command, CommandResult } from '@extensions/ordessa.contracts/contract.js'
import type { C07 } from '@extensions/ordessa.contracts/contract.js'

/** Compatibility facade over the C07 command owner. This adapter keeps no command registry. */
export function createLegacyCommandsAdapter(source: C07.CommandSource): Commands {
  let observed = source.getSnapshot()
  let snapshot: readonly Pick<Command, 'id' | 'title'>[] = observed.map(({ id, title }) => ({ id, title }))
  const refresh = () => {
    const current = source.getSnapshot()
    if (current !== observed) {
      observed = current
      snapshot = current.map(({ id, title }) => ({ id, title }))
    }
  }

  return {
    getSnapshot() {
      refresh()
      return snapshot
    },
    subscribe(listener) {
      return source.subscribe(() => {
        refresh()
        listener()
      })
    },
    forScope(scope) {
      return {
        add(command: Command) {
          // The legacy API carries the handler's value through execute(). C07's
          // declaration is narrower (`void`), but its runtime outcome preserves
          // the actual return value, so adapt the function without wrapping away
          // that value.
          const run = (() => command.execute()) as C07.Command['run']
          return source.forScope(scope).add({ id: command.id, title: command.title, run })
        },
      }
    },
    async execute(id): Promise<CommandResult> {
      const outcome = await source.execute(id)
      if (outcome.kind === 'Accepted') return { ok: true, value: outcome.value }
      if (outcome.kind === 'Refused' && outcome.reason === 'command-absent') return { ok: false, error: `Command unavailable: ${id}` }
      return { ok: false, error: outcome.reason }
    },
  }
}
