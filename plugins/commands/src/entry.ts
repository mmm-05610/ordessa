/**
 * Thin forward (T008-10): the generic command registry/execute mechanism now
 * lives in the extension runtime; this entry keeps the `ordessa.commands`
 * identity and forwards to the SAME factory (no second implementation).
 * Keybindings/panels are organized by the Workbench; business handlers stay
 * in their owning plugins; native slash commands are never converted into
 * platform commands.
 */
import type { PluginContext, ResourceScope } from '@ordessa/extension-api'
import { CommandsToken, type Commands } from '@extensions/ordessa.contracts/contract.js'
import { createCommands, ordered, registry } from '@ordessa/extension-runtime/host/services/command-registry'

export { createCommands, ordered, registry }

export default function createPlugin() {
  return { id: 'ordessa.commands', provides: CommandsToken, activate: (context: PluginContext) => createCommands(context.resources) }
}
