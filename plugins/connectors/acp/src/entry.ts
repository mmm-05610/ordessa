import type { PluginContext } from '@ordessa/extension-api'
import { AgentConnectionsToken, type AgentConnections } from '@extensions/ordessa.agent-contracts/contract.js'
import type { AgentConnector } from '@extensions/ordessa.agent-contracts/contract.js'
import { AcpClient } from './client'
import type { AcpChannelSpec } from './channel'
import { hostChannelSpec, requestAcpOrchestration } from './host'
export { hasNativeCommandReader } from './commands'
export type { NativeCommand, NativeCommandCatalog, NativeCommandReader } from './commands'

export const ACP_ADAPTER_ID = 'ordessa.agent-acp'
export const connectorIdFor = (serverInstanceId: string) => `acp:${serverInstanceId}`

/**
 * The reviewed test seam: a host-orchestrated spec (server instance, harness, project list and
 * channel acquisition) is turned into one connector per Server|Harness pair. Choosing the
 * connector never acquires a channel; the client acquires one per bound project on demand.
 */
export function createConnector(spec: AcpChannelSpec): AgentConnector {
  const id = connectorIdFor(spec.serverInstanceId)
  return { id, title: `ACP · ${spec.harness.title}`, connect: () => AcpClient.connect(spec, id) }
}

/**
 * Registration goes through the native bridge: one instance answers for the Server, and its
 * authenticated `acp/identity` names the Server|Harness pairs the ACP channel API is offered for.
 * A pair the Server does not offer registers nothing — an honest empty state, never a fake entry
 * and never a channel this side invented. Connector ids freeze from that identity before
 * `AgentConnections.add`, exactly like the Ordessa Server connector.
 */
export default function createPlugin() {
  return {
    id: ACP_ADAPTER_ID, autoStart: true, requires: [AgentConnectionsToken],
    async activate(context: PluginContext, connections: AgentConnections) {
      const bridge = window.agentNative
      if (!bridge) throw new Error('ACP connector needs the desktop native bridge; this build cannot reach the Server')
      const { instanceId, orchestration } = await requestAcpOrchestration(ACP_ADAPTER_ID, bridge)
      if (!orchestration.offered) {
        await bridge.close(instanceId).catch(() => undefined)
        return 'not-offered'
      }
      const instanceLease = { isDisposed: false, dispose: () => { instanceLease.isDisposed = true; void bridge.close(instanceId).catch(() => undefined) } }
      context.resources.add(instanceLease)
      for (const entry of orchestration.entries) {
        connections.forScope(context.resources).add(
          createConnector(hostChannelSpec(ACP_ADAPTER_ID, bridge, instanceId, entry)))
      }
      return orchestration.entries.map(entry => connectorIdFor(entry.serverInstanceId))
    },
  }
}
