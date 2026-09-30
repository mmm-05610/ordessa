import { spawn } from 'node:child_process'
import { mkdtempSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'

// No auth, provider writes, session/new or prompt. This proves only that the
// enhanced real upstream process registers the bounded evidence requests.
const root = process.argv[2]
if (!root || !path.isAbsolute(root)) throw new Error('Expected absolute candidate asset root')
for (const [brand, relative] of [
  ['codex', 'codex-runtime/node_modules/@agentclientprotocol/codex-acp/dist/index.js'],
  ['claude-code', 'claude-runtime/node_modules/@agentclientprotocol/claude-agent-acp/dist/index.js'],
]) {
  const home = mkdtempSync(path.join(tmpdir(), 'ordessa-native-registration-'))
  const instance = path.join(home, 'instance'); mkdirSync(instance, { mode: 0o700 })
  const child = spawn(process.execPath, [path.join(root, relative)], {
    env: { PATH: process.env.PATH, HOME: home, CODEX_HOME: instance,
      CLAUDE_CONFIG_DIR: instance, XDG_CONFIG_HOME: instance, NO_COLOR: '1' },
    stdio: ['pipe', 'pipe', 'pipe'], detached: true,
  })
  let next = 0
  const pending = new Map()
  const lines = createInterface({ input: child.stdout })
  lines.on('line', line => {
    let reply
    try { reply = JSON.parse(line) } catch { return }
    if (reply.method && reply.id != null) {
      child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: reply.id,
        error: { code: -32601, message: 'Probe does not provide client operations' } }) + '\n')
    } else if (pending.has(reply.id)) { pending.get(reply.id)(reply); pending.delete(reply.id) }
  })
  child.stderr.resume() // Never print potentially sensitive upstream diagnostics.
  const request = (method, params) => new Promise((resolve, reject) => {
    const id = ++next
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${brand} registration request timed out: ${method}`)) }, 20000)
    pending.set(id, reply => { clearTimeout(timer); resolve(reply) })
    child.stdin.write(JSON.stringify({ jsonrpc: '2.0', id, method, params }) + '\n')
  })
  try {
    const initialized = await request('initialize', { protocolVersion: 1, clientCapabilities: {},
      clientInfo: { name: 'ordessa-no-model-registration', version: '1' } })
    if (initialized.error) throw new Error(`${brand} initialize refused: ${initialized.error.code}`)
    if (initialized.result?._meta?.ordessaConfiguration?.version !== 1)
      throw new Error(`${brand} did not declare configuration evidence version`)
    const reply = await request('_ordessa/session/configuration', { sessionId: 'not-created-by-probe' })
    if (!reply.error || reply.error.code === -32601
        || !JSON.stringify(reply.error).includes('Session is not live'))
      throw new Error(`${brand} evidence request did not reach the live-instance reader`)
    console.log(JSON.stringify({ brand, initialize: true, liveReaderRegistered: true,
      unknownSessionRejected: true, sessionNew: 0, prompt: 0, scope: 'registration-only' }))
  } finally {
    lines.close()
    child.stdin.end()
    // This process group was created by this probe, not a user-facing service.
    try { process.kill(-child.pid, 'SIGTERM') } catch {}
    await new Promise(resolve => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve()
      const timer = setTimeout(() => { try { process.kill(-child.pid, 'SIGKILL') } catch {} }, 5000)
      child.once('exit', () => { clearTimeout(timer); resolve() })
    })
  }
}
