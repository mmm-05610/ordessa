// The desktop plugin entry. It requires exactly one platform service —
// WorkbenchToken — and nothing from the Permissions or Chat domains, so
// installing Sandbox alone contributes this region (verification.md gate 2).
//
// The describe transport is *injected*: this package performs no request of its
// own and cannot invent availability, which is what makes the absence/error
// distinction provable rather than implied.
import type { Plugin, PluginContext } from '@ordessa/extension-api'
import { WorkbenchToken, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import type { SandboxDescribeRequest, SandboxDescribeTransport } from './contract'
import { createInMemoryDraftStore, createSandboxSettingsRegion, type SandboxSettingsRegion } from './settings-region'

export interface SandboxSettingsPluginDeps {
  /** Channel to the `sandbox.describe` wire method, supplied by the assembly. */
  transport: SandboxDescribeTransport
  /** Which Harness pin this window is describing; never derived from a brand name. */
  request: SandboxDescribeRequest
}

export function createSandboxSettingsPlugin(deps: SandboxSettingsPluginDeps): Plugin<SandboxSettingsRegion> {
  return {
    id: 'ordessa.sandbox-settings',
    autoStart: true,
    requires: [WorkbenchToken],
    activate: async (context: PluginContext, workbench: Workbench) => {
      const composition = workbench.composition
      if (!composition) throw Error('Workbench composition is unavailable; the Settings region cannot be contributed')
      const region = await createSandboxSettingsRegion({
        host: composition.forScope(context.resources),
        transport: deps.transport,
        request: deps.request,
        drafts: createInMemoryDraftStore(),
      })
      context.resources.add({ isDisposed: false, dispose: () => region.dispose() })
      return region
    },
  }
}
