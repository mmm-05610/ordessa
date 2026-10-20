/** Real formal Server + original SQLite + production board client; zero model. */
import assert from 'node:assert/strict'
import { test } from 'node:test'
import { spawn, execFileSync, type ChildProcess } from 'node:child_process'
import { once } from 'node:events'
import { mkdtemp, readFile, open } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createInterface } from 'node:readline'
import { HttpWirePort } from '@ordessa/system-access-client'
import { engineeringQueries } from '../../../apps/status-board/src/engineering-queries'

const python = process.env.ORDESSA_FORMAL_SERVER_PYTHON
assert.ok(python, 'Explicit current-worktree formal Server Python is required')
const scope = { realm_id: 'reconnect-realm', project_id: 'reconnect-project' }
function recordData(envelope: Record<string, unknown> | undefined): Record<string, unknown> {
  assert.ok(envelope, 'Original record envelope is required')
  const data = envelope.data
  assert.ok(data !== null && typeof data === 'object' && !Array.isArray(data), 'Original record data must be an object')
  return data as Record<string, unknown>
}

test('one board query retains original data during real outage and rereads a new revision', { timeout: 60000 }, async () => {
  const owned = await mkdtemp(path.join(tmpdir(), 'ordessa-board-reconnect-'))
  const dataRoot = path.join(owned, 'server'), library = path.join(owned, 'engineering.sqlite')
  const log = await open(path.join(owned, 'owned-server.log'), 'a')
  let server: ChildProcess | undefined
  let port = 0, origin = '', firstIdentity: string | undefined
  async function stopOwned() {
    if (!server) return
    const current = server
    if (current.exitCode === null && current.signalCode === null) {
      const exited = once(current, 'exit')
      current.kill('SIGTERM')
      const timer = setTimeout(() => current.kill('SIGKILL'), 10000)
      try { await exited } finally { clearTimeout(timer) }
    }
    server = undefined
  }
  async function startOwned(create: boolean) {
    const args = ['-m', 'ordessa_server', '--data-root', dataRoot, '--port', String(port),
      '--engineering-library', library, '--engineering-library-id', 'reconnect-library',
      '--engineering-realm', scope.realm_id, '--engineering-project', scope.project_id]
    if (create) args.push('--engineering-create-library')
    for (const capability of ['engineering.capabilities', 'engineering.artifacts.create',
      'engineering.artifacts.append_revision', 'engineering.artifacts.get', 'engineering.references.resolve'])
      args.push('--engineering-machine-capability', capability)
    const current = spawn(python!, args, { env: process.env, stdio: ['ignore', 'pipe', log.fd] })
    server = current
    const lines = createInterface({ input: current.stdout! })
    const handshake = await new Promise<{ origin: string; pid: number; serverId: string }>((resolve, reject) => {
      const timer = setTimeout(() => { lines.close(); reject(Error('Formal Server readiness timed out; inspect owned temporary log')) }, 15000)
      current.once('error', error => { clearTimeout(timer); lines.close(); reject(error) })
      current.once('exit', () => { clearTimeout(timer); lines.close(); reject(Error('Formal Server exited before readiness; inspect owned temporary log')) })
      lines.once('line', line => {
        clearTimeout(timer); lines.close()
        try { resolve(JSON.parse(line)) } catch { reject(Error('Formal listening handshake invalid')) }
      })
    })
    assert.equal(handshake.pid, current.pid)
    assert.match(handshake.origin, /^http:\/\/127\.0\.0\.1:\d+$/)
    assert.equal(typeof handshake.serverId, 'string')
    assert.ok(handshake.serverId.length > 0)
    origin = handshake.origin
    port = Number(new URL(origin).port)
    if (firstIdentity) assert.equal(handshake.serverId, firstIdentity)
    else firstIdentity = handshake.serverId
  }
  let readAttempts = 0
  try {
    await startOwned(true)
    // Ask the actual owner for its locator instead of duplicating data-root layout.
    const tokenLocator = execFileSync(python!, ['-c',
      'from pathlib import Path; from ordessa_server.bootstrap.data_root import token_file; import sys; print(token_file(Path(sys.argv[1])))', dataRoot],
      { env: process.env, encoding: 'utf8' }).trim()
    const http = new HttpWirePort({ origin, scope: null, wirePathPrefix: '/wire/v1/',
      readToken: async () => (await readFile(tokenLocator, 'utf8')).trim(), timeoutMs: 3000 })
    async function command(method: string, requestId: string, parameters: Record<string, unknown>) {
      const reply = await http.call(method, { scope, requestId, parameters })
      assert.equal(reply.kind, 'Accepted', 'Original owner did not accept the controlled command')
      if (reply.kind !== 'Accepted') throw Error('Original command refused or unknown')
      assert.equal(reply.result.contract_version, 'engineering-wire/1')
      assert.equal(reply.result.status, 'completed')
      return reply.result.result as Record<string, unknown>
    }
    const made = await command('engineering.artifacts.create', 'reconnect-create', {
      kind: 'other', initial: { media_type: 'application/json', schema_id: 'urn:ordessa:test:reconnect', inline_value: { revision: 1 } } })
    const artifact = made.artifact as Record<string, unknown>
    const artifactId = artifact.artifact_id as string
    const query = engineeringQueries({ call: (method, params) => {
      readAttempts++; return http.call(method, params)
    } }).createQuery('engineering.artifacts.get', scope, { artifact_id: artifactId })
    await query.refresh()
    const first = query.getSnapshot()
    assert.equal(first.stale, false)
    assert.equal(recordData(first.data).version, 1)
    const prior = structuredClone(first.data), updatedAt = first.lastUpdated
    assert.equal(readAttempts, 1)

    await stopOwned() // Only this test's exact subprocess. No existing user service.
    await query.refresh()
    const disconnected = query.getSnapshot()
    assert.equal(disconnected.result?.kind, 'Unknown')
    assert.equal(disconnected.stale, true)
    assert.deepEqual(disconnected.data, prior)
    assert.equal(disconnected.lastUpdated, updatedAt)
    assert.equal(readAttempts, 2)

    await startOwned(false) // Same actual root/library and actual chosen port, no alternate service.
    const appended = await command('engineering.artifacts.append_revision', 'reconnect-append', {
      artifact_id: artifactId, expected_version: 1, parents: [made.revision_ref],
      payload: { media_type: 'application/json', schema_id: 'urn:ordessa:test:reconnect', inline_value: { revision: 2 } } })
    await query.refresh()
    const recovered = query.getSnapshot()
    assert.equal(recovered.stale, false)
    assert.equal(recovered.result?.kind, 'Accepted')
    assert.equal(recordData(recovered.data).artifact_id, artifactId)
    assert.equal(recordData(recovered.data).version, 2)
    // Appending is distinct from selecting a head. Preserve the actual owner rule.
    assert.equal(recordData(recovered.data).head_revision_id, recordData(prior).head_revision_id)
    const revision = await http.call('engineering.references.resolve', {
      scope, requestId: 'reconnect-exact-new-revision', parameters: { ref: appended.revision_ref } })
    assert.equal(revision.kind, 'Accepted')
    if (revision.kind !== 'Accepted') throw Error('Original appended reference unavailable')
    assert.equal(revision.result.record_type, 'ArtifactRevision')
    const value = revision.result.data as Record<string, unknown>
    assert.equal(value.revision_id, (appended.revision_ref as Record<string, unknown>).revision_id)
    assert.deepEqual((value.payload as Record<string, unknown>).inline_value, { revision: 2 })
    assert.ok(Date.parse(recovered.lastUpdated!) > Date.parse(updatedAt!))
    assert.equal(readAttempts, 3) // Explicit rereads only; response loss does not auto-retry.
    console.log(JSON.stringify({ formal_entry: 'python -m ordessa_server', same_instance: true,
      source: 'original Engineering SQLite/UoW', prior_version: 1, recovered_version: 2,
      read_attempts: readAttempts, credential_values_output: false, real_model_calls: 0,
      native_electron_ipc_verified: false, work_acceptance_verified: false }))
  } finally {
    await stopOwned()
    await log.close()
  }
})
