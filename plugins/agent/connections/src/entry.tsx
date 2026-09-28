import { Contributions, type IDisposable, type PluginContext, type ResourceScope } from '@ordessa/extension-api'
import { ConnectionsToken, WorkbenchToken, type Connector, type ConnectionHandle, type Connections, type Workbench } from '@extensions/ordessa.contracts/contract.js'
import { AgentClientConnectionKind, AgentConnectionsToken, type AgentConnections, type AgentClient, type AgentConnector } from '@extensions/ordessa.agent-contracts/contract.js'
import { createConnectionWorkspace } from './workspace'
import { ConnectionStatus } from './status'

/** Adapts the frozen adapter shape (`AgentConnector.connect()`) to the platform's
 * `Connector<AgentClient>`, so adapters never have to learn a platform type (contract C6 §1:
 * the Agent facade adapts, the connectors stay as they are).
 *
 * `open` deliberately takes no signal: `AgentConnector.connect()` is the frozen handshake and
 * accepts no parameter, and inventing an adapter-side cancellation API is out of scope. The
 * platform's own invalidation still cancels a not-yet-landed open — the late endpoint is closed
 * exactly once through the `closeLocal` below (§5.3), which is the same local release a delivered
 * handle's close performs. */
function asPlatformConnector(connector: AgentConnector): Connector<AgentClient> {
  return {
    id: connector.id,
    title: connector.title,
    kind: AgentClientConnectionKind,
    open: async () => {
      const client = await connector.connect()
      return {
        value: client,
        /** Releases LOCAL connection ownership only. `AgentClient.dispose()` is synchronous and
         * only STARTS the backend stand-down: it announces in-flight release states whose answers
         * arrive later over the client's own notification channel. Resolving this promise
         * therefore claims NOTHING about the backend having settled — the managed-release lifecycle
         * (seeding before takeover, re-publication on every announced transition, the
         * `releasesSettled` attestation, explicit retry only) stays Agent-side in `workspace.ts`,
         * and no caller may read a resolved close as a backend confirmation (contract §3, CN-07). */
        closeLocal: async () => { client.dispose() },
      }
    },
  }
}

/** The Agent-domain connection facade: an existing business surface, now a CONSUMER of the
 * `@ordessa/connections` platform rather than a second connection manager. `connections` is the
 * platform service resolved through `ConnectionsToken` (the product wires it in `activate`); the
 * facade keeps only what is Agent domain — the connector listing the Agents UI shows, the
 * `AgentClient` handshake, and the release workspace below. */
export function createAgentConnections(lifetime: ResourceScope, connections: Connections): AgentConnections {
  // The Agent-domain listing (which ids/titles are Agent connectors, in the same id order the
  // status bar shows) is a domain view over the platform's registrations, built from the shared
  // extension-api Contributions primitive — not a new generic container. Registration ownership,
  // kind identity, instance records, close and settlement all live in `connections`.
  const listed = lifetime.add(new Contributions<AgentConnector>())
  /** Platform registrations taken over by this facade, keyed by connector id, so the service scope
   * hands every one of them back even when an adapter scope outlives it. */
  const links = new Map<string, IDisposable>()
  /** The platform handle of the current client per connection id: the ONE owner of that client's
   * local release (contract §4), which is why the workspace never adds a client to a scope itself. */
  const handles = new Map<string, ConnectionHandle<AgentClient>>()
  lifetime.add({ isDisposed: false, dispose() { for (const link of [...links.values()]) link.dispose() } })
  let source = listed.getSnapshot()
  let snapshot: readonly Pick<AgentConnector, 'id' | 'title'>[] = source.map(({ id, title }) => ({ id, title }))
  const registryFacade = {
    getSnapshot: () => {
      const current = listed.getSnapshot()
      if (current !== source) {
        source = current
        snapshot = current.map(({ id, title }) => ({ id, title }))
      }
      return snapshot
    },
    subscribe: listed.subscribe,
    connect: async (id: string) => {
      if (!listed.getSnapshot().some(item => item.id === id) || lifetime.isDisposed)
        throw Error(`Agent connection unavailable: ${id}`)
      // The generic half is the platform's: it checks the registration and the kind identity, owns
      // the instance record and the caller-scope ownership, and closes through `closeLocal`.
      const handle = await connections.open(lifetime, id, AgentClientConnectionKind)
      handles.set(id, handle)
      return handle.value
    },
    /** Releases one connection's local ownership through its platform handle. The call is
     * synchronous up to `client.dispose()` (the platform runs `closeLocal` inside `close()`), so the
     * release states the client announces land while the caller is still observing this connection.
     * A refused LOCAL release is re-raised to the Agent caller — the platform reports `close_failed`
     * instead of pretending the connection closed — which is exactly how a throwing `dispose()` used
     * to propagate out of `reconnect`. Either way it is a LOCAL statement only: what the backend
     * stood down is answered solely by the client's release-state channel (§3, CN-07). */
    release: async (id: string) => {
      const handle = handles.get(id)
      if (!handle) throw Error(`Agent connection released without a platform handle: ${id}`)
      handles.delete(id)
      const outcome = await handle.close()
      if (outcome.status === 'close_failed') throw Error(`Agent connection local release failed: ${outcome.error}`)
    },
  }
  const service: AgentConnections = {
    getSnapshot: registryFacade.getSnapshot,
    subscribe: registryFacade.subscribe,
    forScope: scope => ({
      add: connector => {
        if (scope.isDisposed || lifetime.isDisposed) throw Error('Registration scope is closed')
        if (!connector.id.trim()) throw Error('Contribution id is required')
        // The registrant owner scope stays the ADAPTER's own scope: unmounting it removes the
        // registration, invalidates new opens and releases what it had opened (§5.2).
        const registration = connections.forScope(scope).add(asPlatformConnector(connector))
        const contribution = listed.add(Object.freeze({ ...connector }))
        let released = false
        const link: IDisposable = {
          get isDisposed() { return released },
          dispose() {
            if (released) return
            released = true
            links.delete(connector.id)
            contribution.dispose()
            registration.dispose()
          },
        }
        links.set(connector.id, link)
        return scope.add(link)
      },
    }),
    connect: registryFacade.connect,
    // One workspace per service, owned by the service scope; consumers share the same instance.
    workspace: createConnectionWorkspace(lifetime, registryFacade),
  }
  return service
}
export default function createPlugin() {
  return { id: 'ordessa.agent-connections', autoStart: true, requires: [WorkbenchToken, ConnectionsToken], provides: AgentConnectionsToken,
    activate: (context: PluginContext, workbench: Workbench, connections: Connections) => {
      const service = createAgentConnections(context.resources, connections)
      workbench.forScope(context.resources).addUI({ id: 'agent.connections.status', kind: 'component', slot: 'statusbar',
        component: () => <ConnectionStatus workspace={service.workspace} /> })
      return service
    } }
}
