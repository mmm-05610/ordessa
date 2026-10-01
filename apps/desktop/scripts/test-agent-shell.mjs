import assert from 'node:assert/strict'
import { mkdir, mkdtemp, readFile, writeFile, rm } from 'node:fs/promises'
import { createServer } from 'node:http'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchSmoke } from './launch-smoke.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const home = await mkdtemp(path.join(tmpdir(), 'ordessa-agent-shell-'))
try {
  // Focused shell/connector fixture, not full-product acceptance: a hello-only
  // peer cannot truthfully serve Skills/Profile/ModelProvider business methods.
  // Full shipping assembly is separately verified by probe-native-installed.
  const shipping = JSON.parse(await readFile(path.join(root, 'products/desktop/extensions.json'), 'utf8'))
  const shellIds = ['ordessa.contracts', 'ordessa.agent-contracts', 'ordessa.commands', 'ordessa.workbench',
    'ordessa.ui-components', 'ordessa.connections', 'ordessa.agent-connections', 'ordessa.agent-sessions',
    'ordessa.agent-server', 'ordessa.agent-acp', 'ordessa.chat-api', 'ordessa.chat']
  for (const id of shellIds) assert.ok(shipping.enabled.includes(id), `${id} must be in the shipping product`)
  await writeFile(path.join(home, 'extensions.json'), JSON.stringify({ enabled: shellIds }))
  // Deliberately absent runtime: the host cannot produce a handoff. Empty
  // origin alone no longer simulates absence, since the host now fills it.
  const result = await launchSmoke(home, { ORDESSA_EMPTY_HOST: '0', MODULAR_AGENT_SHELL_SMOKE: '1',
    ORDESSA_BUNDLED_ROOT: path.join(home, 'deliberately-missing-runtime'),
    ORDESSA_SERVER_ORIGIN: '', ORDESSA_SERVER_TOKEN_FILE: '' })
  assert.equal(result.ready, true)
  assert.equal(result.rootMounted, true)
  assert.equal(result.nodeAbsent, true)
  assert.ok(result.errors.some(error => error.includes('ordessa.agent-server') && error.includes('ORDESSA_SERVER_ORIGIN is not set')))
  // A sole main view has no tab strip: assert the actual current Chat body.
  assert.equal(result.agentShell.chatMounted, true)
  assert.ok(result.pages.includes('Sessions'))
  assert.ok(!result.pages.includes('Requests'))
  assert.deepEqual(result.agentShell, {
    navigation: true, statusbarToggle: true, popover: true,
    codexVisible: false, piVisible: false, serverVisible: false,
    emptyConversation: true, chatMounted: true,
    newSessionEntry: true, panelOwnConnectionUi: false,
    projectPicker: false,
    rightRequests: false, rightTab: false,
  })
  // A loopback fake only answers authenticated hello. It proves the installed native entry can
  // register this one Server connector before any project, profile, session or model call occurs.
  const secrets = path.join(home, 'secrets')
  await mkdir(secrets)
  const token = 'candidate-fixture-token'
  const tokenFile = path.join(secrets, 'http-token')
  await writeFile(tokenFile, token, { mode: 0o600 })
  const calls = []
  const server = createServer(async (request, response) => {
    const chunks = []
    for await (const chunk of request) chunks.push(chunk)
    const frame = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    calls.push(frame.method)
    assert.equal(request.headers.authorization, `Bearer ${token}`)
    response.setHeader('content-type', 'application/json')
    response.end(JSON.stringify({ jsonrpc: '2.0', id: frame.id, result: {
      serverId: 'candidate-fake-server', protocolVersion: 'wire/1', capabilities: [],
      harnesses: [{ id: 'pi' }], nativeExecution: { mode: 'native', harness: 'pi', profileId: 'profile_fixture' },
    } }))
  })
  try {
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
    const address = server.address()
    if (!address || typeof address === 'string') throw Error('No loopback fixture address')
    const connected = await launchSmoke(home, { ORDESSA_EMPTY_HOST: '0', MODULAR_AGENT_SHELL_SMOKE: '1',
      ORDESSA_SERVER_ORIGIN: `http://127.0.0.1:${address.port}`, ORDESSA_SERVER_TOKEN_FILE: tokenFile })
    assert.equal(connected.ready, true)
    assert.deepEqual(connected.errors, [])
    assert.equal(connected.agentShell.serverVisible, true)
    assert.equal(connected.agentShell.codexVisible, false)
    assert.equal(connected.agentShell.piVisible, false)
    // Both native entries prove their own hello exactly once: the Server connector registers the
  // pair behind it, and the ACP connector reads its (here: absent) acp.* capabilities and stays
  // honestly unregistered. No other wire traffic may happen against this hello-only fake.
  assert.deepEqual(calls, ['server.hello', 'server.hello'])
    console.log(JSON.stringify({ noHandoff: result.agentShell, authenticatedHello: connected.agentShell,
      calls, nodeAbsent: connected.nodeAbsent }))
  } finally { await new Promise(resolve => server.close(resolve)) }
} finally { await rm(home, { recursive: true, force: true }) }
