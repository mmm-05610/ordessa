// C7 assembly entry (contract §1/§3, ui-components-platform.md boundary 5): the
// only place that turns a product selection into the ordinary Lumino service
// plugin. Business plugins never call this; the product/extension assembly does.
//
// `token` is a parameter rather than a relative import on purpose: the provider
// and its consumers must hand Lumino the SAME Token object, and Lumino matches
// services by object identity. Consumers get it from the shared carrier module,
// so the assembly has to receive that same instance (see extension/entry.ts).
import type { Plugin, PluginContext, Token } from '@ordessa/extension-api'
import type { UiComponents, UiRequirementDiagnostic, UiSelection } from '../api/ui-components'
import { createUiComponentsService, type UiComponentsService, type UiComponentsServiceOptions } from '../src/index'

/** The plugin object also carries the product-side required-binding check. */
export interface UiComponentsPlugin extends Plugin<UiComponents> {
  inspectRequirements(): readonly UiRequirementDiagnostic[]
}

export interface UiComponentsAssembly {
  plugin: UiComponentsPlugin
  /**
   * Product-side check run after activation: lists only the required bindings
   * that are still missing (component id, major, selected provider, reason).
   * It is deliberately not part of the token-carried consumer surface (§3).
   */
  inspectRequirements(): readonly UiRequirementDiagnostic[]
}

/**
 * Read the selection out of the opaque per-extension configuration the product
 * supplied (see the loader's `config` pass-through). Accepts only generic
 * strings and versions — this platform never learns a component name — and an
 * absent configuration means "no selection", which keeps an empty product empty.
 */
export function parseUiSelection(value: unknown): UiSelection {
  if (value === undefined || value === null) return []
  if (!Array.isArray(value)) throw Error('ui-components configuration must be an array of {componentId, major, providerId}')
  return value.map((entry, index) => {
    if (typeof entry !== 'object' || entry === null) throw Error(`ui-components selection[${index}] is not an object`)
    const { componentId, major, providerId } = entry as Record<string, unknown>
    if (typeof componentId !== 'string' || componentId.length === 0) throw Error(`ui-components selection[${index}].componentId must be a non-empty string`)
    if (typeof providerId !== 'string' || providerId.length === 0) throw Error(`ui-components selection[${index}].providerId must be a non-empty string`)
    if (typeof major !== 'number' || !Number.isInteger(major) || major < 1) throw Error(`ui-components selection[${index}].major must be a positive integer`)
    return { componentId, major, providerId }
  })
}

/** Build the service plugin for one host from the product's selection table. */
export function createUiComponentsPlugin(
  selection: UiSelection, token: Token<UiComponents>, options?: UiComponentsServiceOptions,
): UiComponentsAssembly {
  const service: UiComponentsService = createUiComponentsService(selection, options)
  const inspectRequirements = (): readonly UiRequirementDiagnostic[] => service.inspectRequirements()
  const plugin: UiComponentsPlugin = {
    id: 'ordessa.ui-components',
    autoStart: true,
    provides: token,
    activate: (context: PluginContext): UiComponents => {
      // Ownership follows the host-issued plugin scope: deactivation or a failed
      // activation revokes every registration and binding through the service.
      context.resources.add(service)
      return service.uiComponents
    },
    inspectRequirements,
  }
  return { plugin, inspectRequirements }
}
