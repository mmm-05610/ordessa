// Built-in extension `ordessa.ui-components` (contract C7 §1/§3, boundary 5): the
// product enables it by id and hands it a selection through its per-extension
// configuration; nothing here knows a component name.
//
// The Token is taken from the SHARED runtime carrier (same pattern as
// ordessa.connections / ordessa.commands / ordessa.workbench): a plugin that
// resolved a private copy of the api module would carry a second Token instance,
// which is the CN-08 counterexample the product token guard checks. The service
// implementation is bundled into this extension, and it reaches the api module
// through type-only imports plus the Token-free errors leaf — so the only `new
// Token(...)` construction of 'ordessa.ui-components.v1' in a real build stays
// the carrier's.
import type { Plugin } from '@ordessa/extension-api'
import { UiComponentsToken, type UiComponents } from '@extensions/ordessa.contracts/contract.js'
import { createUiComponentsPlugin, parseUiSelection } from '../assembly/entry'

/** `config` is this extension's slice of the product configuration: the selection array. */
export default function createPlugin(_api: unknown, config?: unknown): Plugin<UiComponents> {
  return createUiComponentsPlugin(parseUiSelection(config), UiComponentsToken).plugin
}
