// Built-in extension `ordessa.connections` (contract C6 §1/§3): provides the
// ConnectionsToken service built by the platform core in src/index.ts. Kept
// OUTSIDE src/ so the platform core import wall (api + src/**) stays literal.
//
// The token here is the SHARED runtime copy carried by the contracts foundation
// bundle (the same pattern as ordessa.commands / ordessa.workbench): a consumer
// that resolved a private copy of the api module would hold a second Token
// instance, which is the CN-08 counterexample the product token guard checks.
import type { PluginContext } from '@ordessa/extension-api'
import { ConnectionsToken, type Connections } from '@extensions/ordessa.contracts/contract.js'
import { createConnections } from '../src/index'

export default function createPlugin() {
  return {
    id: 'ordessa.connections',
    autoStart: true,
    provides: ConnectionsToken,
    activate: (context: PluginContext): Connections => createConnections(context.resources),
  }
}
