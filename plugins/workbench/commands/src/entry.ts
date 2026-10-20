/** The stable ordessa.commands plugin consumes the C07 CommandSource as a UI view. */
import type { PluginContext } from '@ordessa/extension-api'
import { CommandsToken, CommandSourceToken, type C07 } from '@extensions/ordessa.contracts/contract.js'
import { createCommandsView } from '@ordessa/extension-runtime/commands-view'

export default function createPlugin() {
  return {
    id: 'ordessa.commands',
    provides: CommandsToken,
    requires: [CommandSourceToken],
    activate: (_context: PluginContext, source: C07.CommandSource) => createCommandsView(source),
  }
}
