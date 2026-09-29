// The desktop plugin entry. It requires exactly two platform services —
// WorkbenchToken and the C-03 WirePortToken — and nothing from the Permissions
// or Chat domains, so installing Sandbox alone contributes this region
// (verification.md gate 2).
//
// The describe transport is the platform's ONE wire port adapted below: this
// package still performs no request of its own and cannot invent availability,
// which is what makes the absence/error distinction provable rather than
// implied.
import type { Plugin, PluginContext } from '@ordessa/extension-api'
import { WirePortToken, WorkbenchToken, type Workbench, type WirePort } from '@extensions/ordessa.contracts/contract.js'
import type { SandboxDescribeRequest, SandboxDescribeResponse, SandboxDescribeResult, SandboxDescribeTransport } from './contract'
import { SANDBOX_DESCRIBE_METHOD } from './contract'
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

/** WireResult 三态 → describe 传输的适配（包内私用）：`Accepted` 即后端事实；
 * "is not a wire/1 method" 是宿主没有组合沙箱后端——transport 自己的
 * no-provider 答案；其余非答案一律抛出，绝不装扮成平台/覆盖裁决。 */
function wireTransportOf(wire: WirePort): SandboxDescribeTransport {
  return {
    async describe(request) {
      const answer = await wire.call(SANDBOX_DESCRIBE_METHOD, { ...request })
      if (answer.kind === 'Accepted') return { status: 'ok', result: answer.result as unknown as SandboxDescribeResult }
      if (answer.kind === 'Refused' && answer.reason.endsWith('is not a wire/1 method')) {
        return { status: 'no-provider' } satisfies SandboxDescribeResponse
      }
      throw Error(`sandbox.describe ${answer.kind}: ${answer.reason}`)
    },
  }
}

/** The loadable product entry: the loader's only seam. The harness pin is
 * product configuration (`config.request`), never derived here; the transport
 * is the resolved wire port. */
export default function createPlugin(_api?: unknown, config?: { request?: SandboxDescribeRequest }): Plugin<SandboxSettingsRegion> {
  const request = config?.request
  if (request === undefined || typeof request.harnessId !== 'string' || request.harnessId.length === 0) {
    throw Error('ordessa.sandbox-settings needs the product config to carry the describe pin '
      + '{ request: { harnessId } }: which Harness this window describes is an assembly fact, not a guess')
  }
  return {
    id: 'ordessa.sandbox-settings',
    autoStart: true,
    requires: [WorkbenchToken, WirePortToken],
    activate: async (context: PluginContext, workbench: Workbench, wire: WirePort) =>
      createSandboxSettingsPlugin({ transport: wireTransportOf(wire), request }).activate(context, workbench),
  }
}
