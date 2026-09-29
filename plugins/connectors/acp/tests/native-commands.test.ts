import { expect, it } from 'vitest'
import type * as acp from '@agentclientprotocol/sdk'
import { AcpClient } from '../src/client'
import type { AcpChannelHandle, AcpChannelSpec } from '../src/channel'
import { HarnessPeer } from '../../../../tests/integration/acp-connector/fixtures/acp-peer'
import { hostChannelSpec } from '../src/host'
import { parseNativeCommands } from '../src/commands'
import type { AgentNativeBridge } from '../../../../apps/desktop/renderer/agent-native'

const nextTick = async () => new Promise(resolve => setTimeout(resolve, 0))

it('rejects incomplete or ambiguous lists but accepts Go omitempty fields', () => {
  const update = (availableCommands: unknown) => ({ sessionUpdate: 'available_commands_update', availableCommands })
  expect(parseNativeCommands(update([{ name: 'go', input: {} }]))).toEqual([{ name: 'go', description: '' }])
  for (const commands of [null, [{ name: 'x', description: 3 }],
    [{ name: 'x', description: '', input: { hint: 3 } }],
    [{ name: 'x', description: '' }, { name: 'x', description: '' }]])
    expect(parseNativeCommands(update(commands))).toBeNull()
})
async function until(check: () => boolean) {
  for (let attempt = 0; attempt < 100; attempt++) {
    if (check()) return
    await nextTick()
  }
  throw new Error('native command event did not arrive')
}
function available(client: AcpClient, key: string) {
  const value = client.getNativeCommands(key)
  if (value.kind !== 'available') throw new Error(`native command catalog ${value.kind}`)
  return value
}

function fixture() {
  const peers = new Map<string, HarnessPeer>()
  const handles = new Map<string, AcpChannelHandle>()
  const down = new Map<string, (reason: string) => void>()
  const binding = (id: string) => ({ id, normalizedPath: `/private/${id}` })
  const spec: AcpChannelSpec = {
    serverInstanceId: 'server-commands', harness: { id: 'pi', title: 'Pi' },
    listProjects: async () => [binding('one'), binding('two')],
    openProject: async id => binding(id),
    acquireChannel: async projectId => {
      const peer = new HarnessPeer()
      const handle: AcpChannelHandle = {
        connectionId: `connection-${projectId}`, binding: binding(projectId), stream: peer.stream,
        subscribeDown: listener => { down.set(projectId, listener); return () => { down.delete(projectId) } },
        release: async () => { down.get(projectId)?.('released'); peer.close() },
      }
      peers.set(projectId, peer); handles.set(projectId, handle)
      return handle
    },
  }
  return { spec, peers, handles, down }
}

function rawInject(peer: HarnessPeer, beforeSessionNew?: (inject: (message: acp.AnyMessage) => void) => void) {
  const source = peer.stream.readable
  let inject!: (message: acp.AnyMessage) => void
  const readable = new ReadableStream<acp.AnyMessage>({
    start(controller) {
      inject = frame => controller.enqueue(frame)
      const reader = source.getReader()
      void (async () => {
        try {
          for (;;) {
            const { value, done } = await reader.read()
            if (done) break
            controller.enqueue(value)
          }
          controller.close()
        } catch (error) { controller.error(error) }
      })()
    },
  })
  const writer = peer.stream.writable.getWriter()
  const writable = new WritableStream<acp.AnyMessage>({
    write: async message => {
      if ((message as { method?: string }).method === 'session/new') beforeSessionNew?.(inject)
      await writer.write(message)
    },
    close: () => writer.close(),
    abort: reason => writer.abort(reason),
  })
  return { stream: { readable, writable }, inject }
}

it('projects native command refreshes as immutable same-channel, same-session data', async () => {
  const { spec, peers, down } = fixture()
  const client = await AcpClient.connect(spec, 'acp:commands')
  try {
    await client.openWorkspace('one')
    const first = await client.newSession()
    expect(client.getNativeCommands(first)).toEqual({ kind: 'absent' })
    await peers.get('one')!.update('acp-session-1', { sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: '/create_plan', description: 'Create a plan', input: { hint: 'topic' } }] })
    await until(() => client.getNativeCommands(first).kind === 'available')
    const catalog = client.getNativeCommands(first)
    expect(catalog).toEqual({ kind: 'available', connectionId: 'connection-one',
      nativeSessionId: 'acp-session-1', commands: [{ name: '/create_plan', description: 'Create a plan', inputHint: 'topic' }] })
    expect(Object.isFrozen(catalog)).toBe(true)
    if (catalog.kind === 'available') expect(Object.isFrozen(catalog.commands[0])).toBe(true)
    expect(peers.get('one')!.recorded('session/prompt')).toHaveLength(0)
    await peers.get('one')!.update('acp-session-1', { sessionUpdate: 'available_commands_update', availableCommands: [] })
    await until(() => client.getNativeCommands(first).kind === 'available'
      && available(client, first).commands.length === 0)
    expect(client.getNativeCommands(first)).toEqual({ kind: 'available', connectionId: 'connection-one',
      nativeSessionId: 'acp-session-1', commands: [] })
    down.get('one')?.('socket closed')
    expect(client.getNativeCommands(first)).toEqual({ kind: 'unknown', reason: 'channel-down' })
  } finally { client.dispose() }
  expect(client.getNativeCommands('acp-session-1')).toEqual({ kind: 'unknown', reason: 'channel-down' })
})

it('isolates identical native ids by connection and retires the old session', async () => {
  const { spec, peers } = fixture()
  const client = await AcpClient.connect(spec, 'acp:commands')
  try {
    await client.openWorkspace('one'); const one = await client.newSession()
    await client.openWorkspace('two'); const two = await client.newSession()
    expect(one).not.toBe(two)
    await peers.get('one')!.update('acp-session-1', { sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: 'alpha', description: 'One' }] })
    await peers.get('two')!.update('acp-session-1', { sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: 'beta', description: 'Two' }] })
    await until(() => client.getNativeCommands(one).kind === 'available'
      && client.getNativeCommands(two).kind === 'available')
    expect(available(client, one).commands).toEqual([{ name: 'alpha', description: 'One' }])
    expect(available(client, two).commands).toEqual([{ name: 'beta', description: 'Two' }])
    await client.openWorkspace('one')
    const next = await client.newSession()
    expect(client.getNativeCommands(one)).toEqual({ kind: 'unknown', reason: 'stale-session' })
    await peers.get('one')!.update('acp-session-1', { sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: 'late', description: 'Old session' }] })
    expect(client.getNativeCommands(one)).toEqual({ kind: 'unknown', reason: 'stale-session' })
    expect(client.getNativeCommands(next)).toEqual({ kind: 'absent' })
    expect(client.getNativeCommands(two).kind).toBe('available')
  } finally { client.dispose() }
})

it('invalid raw command updates clear prior availability before SDK filtering', async () => {
  const { spec, peers, handles } = fixture()
  const original = spec.acquireChannel
  let inject!: (message: acp.AnyMessage) => void
  spec.acquireChannel = async projectId => {
    const handle = await original(projectId)
    const wrapped = rawInject(peers.get(projectId)!)
    inject = wrapped.inject
    const replacement = { ...handle, stream: wrapped.stream }
    handles.set(projectId, replacement)
    return replacement
  }
  const client = await AcpClient.connect(spec, 'acp:commands')
  try {
    await client.openWorkspace('one'); const key = await client.newSession()
    await peers.get('one')!.update('acp-session-1', { sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: 'safe', description: 'Known' }] })
    await until(() => client.getNativeCommands(key).kind === 'available')
    inject({ jsonrpc: '2.0', method: 'session/update', params: { sessionId: 'acp-session-1',
      update: { sessionUpdate: 'available_commands_update', availableCommands: [
        { name: 'half', description: 'Valid' }, { name: 7, description: 'Invalid' },
      ] } } } as unknown as acp.AnyMessage)
    await until(() => client.getNativeCommands(key).kind === 'unknown')
    expect(client.getNativeCommands(key)).toEqual({ kind: 'unknown', reason: 'malformed' })
    inject({ jsonrpc: '2.0', method: 'session/update', params: { sessionId: 'acp-session-1',
      update: { sessionUpdate: 'available_commands_update', availableCommands: [
        { name: 'go-command', input: {} },
      ] } } } as unknown as acp.AnyMessage)
    await until(() => client.getNativeCommands(key).kind === 'available')
    expect(available(client, key).commands).toEqual([{ name: 'go-command', description: '' }])
    inject({ jsonrpc: '2.0', method: 'session/update', params: { sessionId: 'acp-session-1',
      update: { sessionUpdate: 'future_command_variant' } } } as unknown as acp.AnyMessage)
    await until(() => client.getNativeCommands(key).kind === 'unknown')
    expect(client.getNativeCommands(key)).toEqual({ kind: 'unknown', reason: 'malformed' })
  } finally { client.dispose() }
})

it('keeps an early same-channel command refresh until session/new returns its native id', async () => {
  const { spec, peers } = fixture()
  const original = spec.acquireChannel
  spec.acquireChannel = async projectId => {
    const handle = await original(projectId)
    return { ...handle, stream: rawInject(peers.get(projectId)!, inject => {
      inject({ jsonrpc: '2.0', method: 'session/update', params: { sessionId: 'acp-session-1',
        update: { sessionUpdate: 'available_commands_update', availableCommands: [
          { name: 'early', description: 'Before new reply' },
        ] } } } as unknown as acp.AnyMessage)
    }).stream }
  }
  const client = await AcpClient.connect(spec, 'acp:commands')
  try {
    await client.openWorkspace('one')
    const key = await client.newSession()
    expect(client.getNativeCommands(key)).toEqual({ kind: 'available', connectionId: 'connection-one',
      nativeSessionId: 'acp-session-1', commands: [{ name: 'early', description: 'Before new reply' }] })
  } finally { client.dispose() }
})

it('with no owner down observation, a catalog remains unknown even after a valid update', async () => {
  const { spec, peers } = fixture()
  const original = spec.acquireChannel
  spec.acquireChannel = async id => {
    const handle = await original(id)
    return { ...handle, subscribeDown: undefined }
  }
  const client = await AcpClient.connect(spec, 'acp:commands')
  try {
    await client.openWorkspace('one'); const key = await client.newSession()
    await peers.get('one')!.update('acp-session-1', { sessionUpdate: 'available_commands_update',
      availableCommands: [{ name: 'hidden', description: 'Cannot prove liveness' }] })
    expect(client.getNativeCommands(key)).toEqual({ kind: 'unknown', reason: 'unobservable' })
  } finally { client.dispose() }
})

it('the production host maps a connection-scoped acp/down into the handle terminal fact', async () => {
  let deliver!: (event: { instanceId: string; frame: unknown }) => void
  const bridge = {
    subscribe(listener: typeof deliver) { deliver = listener; return () => undefined },
    async send(_instanceId: string, frame: { method: string }) {
      if (frame.method === 'acp/channel/open') return { connectionId: 'connection-one',
        binding: { id: 'one', normalizedPath: '/private/one' } }
      if (frame.method === 'acp/channel/release') return { released: true }
      throw new Error('unexpected host call')
    },
  } as unknown as AgentNativeBridge
  const spec = hostChannelSpec('ordessa.agent-acp', bridge, 'instance-one', {
    serverInstanceId: 'server-one', harness: { id: 'pi', title: 'Pi' },
  })
  const handle = await spec.acquireChannel('one')
  const reasons: string[] = []
  handle.subscribeDown?.(reason => { reasons.push(reason) })
  deliver({ instanceId: 'other-instance', frame: { method: 'acp/down', connectionId: 'connection-one',
    params: { reason: 'foreign' } } })
  deliver({ instanceId: 'instance-one', frame: { method: 'acp/down', connectionId: 'other-connection',
    params: { reason: 'foreign' } } })
  expect(reasons).toEqual([])
  deliver({ instanceId: 'instance-one', frame: { method: 'acp/down', connectionId: 'connection-one',
    params: { reason: 'socket closed' } } })
  expect(reasons).toEqual(['socket closed'])
  handle.subscribeDown?.(reason => { reasons.push(`late:${reason}`) })
  expect(reasons).toEqual(['socket closed', 'late:socket closed'])
})
