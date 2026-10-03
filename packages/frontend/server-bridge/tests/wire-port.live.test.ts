/**
 * EA-1 (D-021-7) — the live wire/1 round trip.
 *
 * The envelope fix in `wire-port.ts` was invisible to every mocked test: the
 * fake transports answered whatever shape the port asked for, while the real
 * Server (`ordessa_server/wire/envelope.py`) refuses a non-JSON-RPC body with
 * 400. This file starts the REAL Server (the trunk venv's `ordessa_server`),
 * reads the REAL token it mints into the data root, and drives `HttpWirePort`
 * against it — the same path a desktop session takes.
 *
 * No skip: an environment that cannot start the Server fails loudly with the
 * server's own log tail and the manual reproduction command. A silent skip
 * here would re-open the exact hole EA-1 found.
 */
import { spawn } from 'node:child_process'
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

import { tokenFileOf } from '../src/data-root.js'
import { HttpWirePort, tokenReaderFor } from '../src/wire-port.js'

const REPO_ROOT = path.resolve(import.meta.dirname, '..', '..', '..', '..')
/** The trunk venv (see specs/021 worktree convention: `.venv` is the shared interpreter). */
const PYTHON = process.env.ORDESSA_WIRE_LIVE_PYTHON ?? path.join(REPO_ROOT, '.venv', 'bin', 'python')
const DATA_ROOT_ENV = 'ORDESSA_DATA_ROOT'

const MANUAL_REPRO = [
  'manual reproduction:',
  `  mkdir -p /tmp/i001-data && printf 'agentbox-server-r1\\n' > /tmp/i001-data/.agentbox-server-root`,
  `  ${PYTHON} -m ordessa_server --data-root /tmp/i001-data --port 0`,
  `  TOKEN=$(cat /tmp/i001-data/secrets/http-token)`,
  `  curl -s -X POST http://127.0.0.1:<port>/wire/v1/workspaces.list \\`,
  `    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \\`,
  `    -d '{"jsonrpc":"2.0","id":"m1","method":"workspaces.list","params":{"includeArchived":false}}'`,
].join('\n')

/** The composition imports two plugin packages the venv does not carry as
 * editable installs; their sources are on the same baseline, so the subprocess
 * reads them from this tree's src dirs (environment fixup, not a code path). */
const PYTHONPATH_EXTRA = [
  path.join(REPO_ROOT, 'plugins/model-provider/server/src'),
  path.join(REPO_ROOT, 'plugins/permissions/backend/src'),
].join(':')

interface LiveServer {
  origin: string
  dataRoot: string
  stop(): Promise<void>
}

async function startServer(): Promise<LiveServer> {
  if (!existsSync(PYTHON)) {
    throw Error(`wire live test: the Server interpreter is missing at ${PYTHON}. ${MANUAL_REPRO}`)
  }
  const dataRoot = await mkdtemp(path.join(path.sep, 'tmp', 'i001-wire-live-'))
  await mkdir(dataRoot, { recursive: true })
  // B-005's data-root marker (registered known issue, fix not merged yet):
  // pre-seed exactly what the Server checks, byte for byte.
  await writeFile(path.join(dataRoot, '.agentbox-server-root'), 'agentbox-server-r1\n')

  const child = spawn(PYTHON, ['-m', 'ordessa_server', '--data-root', dataRoot, '--port', '0'], {
    env: { ...process.env, [DATA_ROOT_ENV]: dataRoot, PYTHONPATH: PYTHONPATH_EXTRA },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  child.stdout.on('data', chunk => { output += String(chunk) })
  child.stderr.on('data', chunk => { output += String(chunk) })

  const deadline = Date.now() + 60_000
  const origin = await new Promise<string>((resolve, fail) => {
    const poll = setInterval(() => {
      // The host's real launch contract: the Server announces itself with one
      // `listening` JSON line on stdout (data_root_layout.json handshakeEvent).
      const line = output.split('\n').find(candidate => candidate.includes('"listening"'))
      if (line !== undefined) {
        clearInterval(poll)
        try {
          const event = JSON.parse(line.slice(line.indexOf('{'))) as { origin?: string }
          if (typeof event.origin === 'string') resolve(event.origin)
          else fail(Error(`listening event carries no origin: ${line}`))
        } catch (error) {
          fail(error as Error)
        }
      } else if (child.exitCode !== null) {
        clearInterval(poll)
        fail(Error(`the Server exited with ${child.exitCode} before listening:\n${output}\n${MANUAL_REPRO}`))
      } else if (Date.now() > deadline) {
        clearInterval(poll)
        fail(Error(`the Server did not announce itself within 60s:\n${output}\n${MANUAL_REPRO}`))
      }
    }, 250)
  })

  // The token lands in the data root during bootstrap; by `listening` it is
  // there, but poll briefly so a reordering cannot flake the test.
  const tokenFile = tokenFileOf(dataRoot)
  const tokenDeadline = Date.now() + 10_000
  while (!existsSync(tokenFile)) {
    if (Date.now() > tokenDeadline) {
      await stop()
      throw Error(`the Server never wrote ${tokenFile}. ${MANUAL_REPRO}`)
    }
    await new Promise(resolve => setTimeout(resolve, 200))
  }

  let stopping = false
  async function stop(): Promise<void> {
    if (stopping) return
    stopping = true
    child.kill('SIGTERM')
    const exited = new Promise<void>(resolve => child.once('exit', () => resolve()))
    await Promise.race([exited, new Promise<void>(resolve => setTimeout(resolve, 5000))])
    if (child.exitCode === null) child.kill('SIGKILL')
    await rm(dataRoot, { recursive: true, force: true })
  }
  child.once('exit', () => { void stop() })
  return { origin, dataRoot, stop }
}

let server: LiveServer

beforeAll(async () => {
  server = await startServer()
}, 90_000)

afterAll(async () => {
  await server?.stop()
})

function livePort(): HttpWirePort {
  return new HttpWirePort({
    origin: server.origin,
    scope: `${server.origin}|live`,
    readToken: tokenReaderFor(server.dataRoot, file => readFile(file, 'utf8')),
    timeoutMs: 10_000,
  })
}

describe('EA-1 — HttpWirePort against the real Server (live)', () => {
  it('carries a workspaces.list call to a real result, not a 400', async () => {
    const result = await livePort().call('workspaces.list', { includeArchived: false })
    // The old flat body made this exact call a 400 on every invocation; the
    // JSON-RPC envelope must come back Accepted with the contract's members.
    expect(result).toMatchObject({ kind: 'Accepted' })
    if (result.kind !== 'Accepted') return
    expect(typeof result.requestId).toBe('string')
    expect(result.requestId.length).toBeGreaterThan(0)
    expect(Array.isArray(result.result['items'])).toBe(true)
    expect(result.result['nextCursor']).toBeNull()
  })

  it('surfaces a live wire refusal as Refused with the server message', async () => {
    // The descriptor requires `includeArchived`; omitting it is refused
    // upstream of the handler — this exercises the live error envelope.
    const result = await livePort().call('workspaces.list', {})
    expect(result).toMatchObject({ kind: 'Refused', retryable: false })
    if (result.kind !== 'Refused') return
    expect(result.reason.length).toBeGreaterThan(0)
  })

  it('answers Unknown for a dead origin and does not resend', async () => {
    let calls = 0
    const port = new HttpWirePort({
      origin: 'http://127.0.0.1:1', // nothing listens on port 1
      scope: 'http://127.0.0.1:1|dead',
      readToken: async () => 'not-a-real-token-but-present',
      fetchImpl: (async (...args: Parameters<typeof fetch>) => {
        calls += 1
        return fetch(...args)
      }) as typeof fetch,
      timeoutMs: 2000,
    })
    const result = await port.call('workspaces.list', { includeArchived: false })
    expect(result).toMatchObject({ kind: 'Unknown', reason: 'result-unknown' })
    expect(calls).toBe(1)
  })
})
