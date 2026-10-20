import type { PluginContext } from '@ordessa/extension-api'
import { AgentConnectionsToken, type AgentConnections } from '@extensions/ordessa.agent-contracts/contract.js'
import { OrdessaClient, ORDESSA_ADAPTER_ID, connectorIdFor, requestServerIdentity, unwrapBridgeError } from './client'

/**
 * The Server instance behind the two host-provided env values is proven here, before any connector
 * exists: `AgentConnections.add` freezes the id, so a later handshake could not rename the connection
 * without orphaning the project selections cached under the old one. A failure therefore registers
 * nothing — the host marks this plugin failed and the renderer shows the alert instead of a fake entry.
 */
export default function createPlugin() {
  return {
    id: ORDESSA_ADAPTER_ID, autoStart: true, requires: [AgentConnectionsToken],
    async activate(context: PluginContext, connections: AgentConnections) {
      const bridge = window.agentNative
      if (!bridge) throw new Error('Ordessa Server needs the desktop native bridge; this build cannot reach the Server token')
      let serverInstanceId: string
      try {
        serverInstanceId = (await requestServerIdentity(bridge)).serverInstanceId
      } catch (error) {
        throw new Error(unwrapBridgeError(error))
      }
      const id = connectorIdFor(serverInstanceId)
      connections.forScope(context.resources).add({
        id, title: 'Ordessa Server',
        connect: () => OrdessaClient.connect(bridge, id, serverInstanceId),
      })
      return id
    },
  }
}
