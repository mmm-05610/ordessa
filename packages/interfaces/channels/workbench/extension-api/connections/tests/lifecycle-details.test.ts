// T027 review follow-ups — two §5 rules whose wording is broader than the CN
// table's dedicated tests, pinned here so the implementation cannot narrow them:
// (a) §5.5 records EVERY failed local release in the cumulative settlement
// report, including one the caller triggered with an explicit close();
// (b) §5.2/§5.3 aborts the platform-owned connector signal when a caller scope
// closes or a registrant unmounts, also for an already-connected instance.
// Same discipline as tests-first T026: controlled in-memory fakes only, no
// Electron, no real transport, no Agent / Workbench / ACP involvement.

import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  createConnectionKind,
  type ConnectionEndpoint,
  type ConnectionKind,
  type Connections,
  type Connector,
} from '@ordessa/connections/api'
import { createConnections } from '../src/index'

interface FakeValue { label: string }

class FakeEndpoint implements ConnectionEndpoint<FakeValue> {
  closeLocalCalls = 0
  closeLocalResult: Promise<void> = Promise.resolve()
  constructor(readonly value: FakeValue) {}
  closeLocal(): Promise<void> {
    this.closeLocalCalls += 1
    return this.closeLocalResult
  }
}

/** Records the signal handed to every open so the test can observe aborts after delivery. */
class FakeConnector implements Connector<FakeValue> {
  readonly signals: AbortSignal[] = []
  readonly endpoints: FakeEndpoint[] = []
  constructor(readonly id: string, readonly title: string, readonly kind: ConnectionKind<FakeValue>) {}
  open(signal: AbortSignal): Promise<ConnectionEndpoint<FakeValue>> {
    this.signals.push(signal)
    const endpoint = new FakeEndpoint({ label: `${this.id}#${this.endpoints.length}` })
    this.endpoints.push(endpoint)
    return Promise.resolve(endpoint)
  }
}

const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))

function newConnections(): { lifetime: OwnedResources; connections: Connections } {
  const lifetime = new OwnedResources()
  return { lifetime, connections: createConnections(lifetime) }
}

describe('§5.5 settlement report completeness', () => {
  it('an explicit handle.close() that fails is returned to the awaiter AND recorded in the cumulative report', async () => {
    // Counterexample sensitivity: a report that only collects dispose-started
    // cleanups leaves `closeFailures` empty here even though a local release
    // failed and nobody but the platform is watching the record.
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.explicit-fail', 'Explicit fail', kind)
    connections.forScope(owner).add(connector)
    const handle = await connections.open(caller, 'fake.explicit-fail', kind)

    connector.endpoints[0]!.closeLocalResult = Promise.reject(new Error('explicit release boom'))
    const outcome = await handle.close()
    expect(outcome.status).toBe('close_failed')
    if (outcome.status === 'close_failed') expect(outcome.error).toContain('explicit release boom')

    const report = await connections.whenSettled()
    expect(report.closeFailures)
      .toContainEqual(expect.objectContaining({
        connectorId: 'fake.explicit-fail', instanceId: handle.instanceId,
      }))
    expect(report.closeFailures[0]!.error).toContain('explicit release boom')
    // §5.6: the unconfirmed record is still available for host diagnosis.
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handle.instanceId, state: 'close_failed' }))

    caller.dispose()
    owner.dispose()
    lifetime.dispose()
  })
})

describe('§5.2/§5.3 signal ownership after delivery', () => {
  it('aborts the connector signal when the caller scope closes on a connected instance', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.caller-signal', 'Caller signal', kind)
    connections.forScope(owner).add(connector)
    const handle = await connections.open(caller, 'fake.caller-signal', kind)
    expect(connector.signals[0]!.aborted).toBe(false)

    caller.dispose()
    // Counterexample sensitivity: a platform that only wired the signal to the
    // open phase leaves it un-aborted, and a connector that parks background
    // work on it never learns the connection is going away.
    expect(connector.signals[0]!.aborted).toBe(true)
    await flush()
    expect(connector.endpoints[0]!.closeLocalCalls).toBe(1)
    const report = await connections.whenSettled()
    expect(report.closeFailures).toEqual([])

    owner.dispose()
    lifetime.dispose()
  })

  it('aborts the connector signal when the registrant scope unmounts on a connected instance', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.owner-signal', 'Owner signal', kind)
    connections.forScope(owner).add(connector)
    const handle = await connections.open(caller, 'fake.owner-signal', kind)
    expect(connector.signals[0]!.aborted).toBe(false)

    owner.dispose()
    expect(connector.signals[0]!.aborted).toBe(true)
    await flush()
    expect(connector.endpoints[0]!.closeLocalCalls).toBe(1)
    expect(handle.getSnapshot().state).not.toBe('opening')

    caller.dispose()
    lifetime.dispose()
  })
})
