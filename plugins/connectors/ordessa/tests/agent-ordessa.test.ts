import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { afterEach, expect, it, vi } from 'vitest'
import {
  ServerConfigError, parseOrigin, resolveServerTarget, serverInstanceId,
} from '../../../../plugins/connectors/ordessa/src/target'
import { readRestrictedTokenFile } from '../../../../plugins/connectors/ordessa/src/token-file'
import createTransport, { nativeExecutionProfile } from '../../../../plugins/connectors/ordessa/src/native'

const SECRET = 'a'.repeat(64)
const LOCATOR = '/run/ordessa/data-root/secrets/http-token'
const env = { ORDESSA_SERVER_ORIGIN: 'http://127.0.0.1:41207', ORDESSA_SERVER_TOKEN_FILE: LOCATOR }
const reader = (token: string) => async () => token
// A real reader refuses with ServerConfigError, so the fake must fail the same way.
const unreadable = async () => { throw new ServerConfigError('Ordessa Server token file is unreadable; http-token') }

const refusedMessage = async (run: () => Promise<unknown>) => {
  const failure = await run().then(() => undefined, error => error)
  expect(failure, 'expected a refusal').toBeInstanceOf(ServerConfigError)
  return String((failure as Error).message)
}
const refusedOrigin = (origin: string | undefined) => refusedMessage(() => Promise.resolve().then(() => parseOrigin(origin)))
const refusedTarget = (input: Record<string, string | undefined>, read = reader(SECRET)) =>
  refusedMessage(() => resolveServerTarget(input, read))

it('resolves the two explicit host inputs into a same-origin target', async () => {
  // The privileged reader has already proven and parsed the file, so the target only ever carries a usable bearer.
  const target = await resolveServerTarget(env, reader(SECRET))
  expect(target).toEqual({ origin: 'http://127.0.0.1:41207', socket: 'ws://127.0.0.1:41207', token: SECRET })
  expect(parseOrigin('http://127.0.0.1:41207/')).toBe('http://127.0.0.1:41207')
  expect(parseOrigin('http://LOCALHOST:8080')).toBe('http://localhost:8080')
})

it('refuses when either input is absent instead of guessing a default port', async () => {
  expect(await refusedTarget({})).toContain('ORDESSA_SERVER_ORIGIN')
  expect(await refusedTarget({ ORDESSA_SERVER_ORIGIN: 'http://127.0.0.1:41207' })).toContain('ORDESSA_SERVER_TOKEN_FILE')
  expect(await refusedTarget({ ORDESSA_SERVER_TOKEN_FILE: LOCATOR })).toContain('ORDESSA_SERVER_ORIGIN')
  expect(await refusedOrigin(undefined)).toContain('is not set')
})

it('refuses anything that is not a bare loopback http origin with an explicit port', async () => {
  const rejected = ['http://127.0.0.1', 'http://localhost', 'https://127.0.0.1:41207', 'http://8732',
    'http://10.0.0.5:8732', 'http://ordessa.example:41207', 'http://[::ffff:127.0.0.1]:41207',
    'http://127.0.0.1:41207/api', 'http://127.0.0.1:41207/?token=x', 'http://127.0.0.1:41207#x',
    'http://user:pass@127.0.0.1:41207', 'ws://127.0.0.1:41207', 'not a url']
  for (const origin of rejected) expect(await refusedOrigin(origin), origin).toMatch(/omits the port|not loopback|must use http|origin only|not a URL|credentials/)
})

it('refuses an unusable token locator without echoing the secret or its path', async () => {
  expect(await refusedTarget({ ...env, ORDESSA_SERVER_TOKEN_FILE: 'secrets/http-token' })).toContain('not absolute')
  expect(await refusedTarget(env, unreadable)).toContain('unreadable')
  expect(await refusedTarget(env, reader(''))).toContain('empty')
})

it('scopes one instance identity per Server however its origin is spelled', async () => {
  const normalized = serverInstanceId(parseOrigin('http://LOCALHOST:41207/'), 'server_1')
  expect(normalized).toBe('http://localhost:41207|server_1')
  // A restart of the same data-root keeps the same scope, so a project selection survives it.
  expect(serverInstanceId(parseOrigin('http://localhost:41207'), 'server_1')).toBe(normalized)
  expect(serverInstanceId('http://localhost:41207', 'server_2')).not.toBe(normalized)
  expect(serverInstanceId('http://localhost:41208', 'server_1')).not.toBe(normalized)
})

// ---------------------------------------------------------------------------
// The restricted token file: FC-0036 requires the locator to be proven, not merely readable.

const roots: string[] = []
const dataRoot = () => {
  const root = mkdtempSync(path.join(tmpdir(), 'ordessa-token-'))
  roots.push(root)
  return root
}
const tokenFile = (token = `${SECRET}\n`, mode = 0o600, root = dataRoot(), name = 'http-token') => {
  const secrets = path.join(root, 'secrets')
  mkdirSync(secrets, { recursive: true })
  const file = path.join(secrets, name)
  writeFileSync(file, token, { mode })
  chmodSync(file, mode)
  return { file, root }
}

afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true })
  process.getuid = originalGetuid
})
const originalGetuid = process.getuid

it('accepts only the same data-root secrets token file, at 0600', async () => {
  expect(await readRestrictedTokenFile(tokenFile().file)).toBe(SECRET)
  // Owner-read-only is equally private, so it is not refused for being narrower than 0600.
  expect(await readRestrictedTokenFile(tokenFile(SECRET, 0o400).file)).toBe(SECRET)
})

it('refuses a locator that is not the Server secrets token file', async () => {
  expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile(SECRET, 0o600, dataRoot(), 'token').file)))
    .toContain('not named http-token')
  const outside = path.join(dataRoot(), 'http-token')
  writeFileSync(outside, SECRET, { mode: 0o600 })
  expect(await refusedMessage(() => readRestrictedTokenFile(outside))).toContain('not inside the data-root secrets directory')
})

it('refuses a symlink and any other non-regular file', async () => {
  const { file } = tokenFile()
  const linked = path.join(path.dirname(file), 'real-token')
  writeFileSync(linked, SECRET, { mode: 0o600 })
  rmSync(file)
  symlinkSync(linked, file)
  expect(await refusedMessage(() => readRestrictedTokenFile(file))).toContain('is a symlink')
  const asDirectory = dataRoot()
  mkdirSync(path.join(asDirectory, 'secrets', 'http-token'), { recursive: true })
  expect(await refusedMessage(() => readRestrictedTokenFile(path.join(asDirectory, 'secrets', 'http-token')))).toContain('not a regular file')
})

it('refuses a token file that group, other or somebody else can see', async () => {
  for (const mode of [0o640, 0o604, 0o666]) {
    expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile(SECRET, mode).file)), `mode ${mode.toString(8)}`)
      .toContain('readable by group or other')
  }
  // A root run would open it and fail the owner-read test instead; both are refusals.
  expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile(SECRET, 0o000).file))).toContain('not readable')
  const foreign = tokenFile()
  process.getuid = () => 999_999
  try {
    expect(await refusedMessage(() => readRestrictedTokenFile(foreign.file))).toContain('owned by another user')
  } finally {
    process.getuid = originalGetuid
  }
})

it('refuses where ownership cannot be checked at all', async () => {
  const { file } = tokenFile()
  process.getuid = undefined as unknown as typeof process.getuid
  expect(await refusedMessage(() => readRestrictedTokenFile(file))).toContain('ownership cannot be checked')
})

it('refuses an unusable token body', async () => {
  expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile('').file))).toContain('empty')
  expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile('\n').file))).toContain('empty')
  expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile('first\nsecond\n').file))).toContain('control characters')
  expect(await refusedMessage(() => readRestrictedTokenFile(tokenFile('x'.repeat(8192)).file))).toContain('too large')
})

it('never writes the token or its full locator into a token-file refusal', async () => {
  const missingRoot = dataRoot()
  const missing = path.join(missingRoot, 'secrets', 'http-token')
  mkdirSync(path.join(missingRoot, 'secrets'))
  const linkedRoot = dataRoot()
  const linked = path.join(linkedRoot, 'real-token')
  writeFileSync(linked, SECRET, { mode: 0o600 })
  symlinkSync(linked, missing)
  const cases = [missing, tokenFile(SECRET, 0o644).file, tokenFile('x'.repeat(8192)).file]
  for (const candidate of cases) {
    const message = await refusedMessage(() => readRestrictedTokenFile(candidate))
    expect(message, candidate).not.toContain(SECRET)
    expect(message, candidate).not.toContain(path.dirname(path.dirname(candidate)))
    expect(message).toContain('http-token')
  }
  // The positive case proves the same locator is otherwise readable, so the refusals above are not vacuous.
  expect(await readRestrictedTokenFile(tokenFile(`${SECRET}\n`, 0o600).file)).toBe(SECRET)
})

// FC-0053 / C-0027: the authenticated hello names this Server combination's exact execution identity,
// so `profiles.list` may only confirm that id — never pick, rank, or substitute for a missing one.
// Every refusal below is the pre-request gate: native.ts resolves the identity before a frame goes out.
const refusal = (run: () => unknown): string => {
  try { run() } catch (error) { return String((error as Error).message) }
  throw new Error('expected the profile cross-check to refuse')
}
const profile = (id: string, harness = 'pi', extra: Record<string, unknown> = {}) =>
  ({ id, harness, displayName: `${id} label`, sendability: { state: 'ready' }, ...extra })
const helloFrom = (nativeExecution: unknown, harnesses: string[] = ['pi']) => ({
  serverId: 'srv_1', protocolVersion: 'wire/1', capabilities: [],
  harnesses: harnesses.map(id => ({ id })), ...(nativeExecution === undefined ? {} : { nativeExecution }),
})
const native = { mode: 'native', harness: 'pi', profileId: 'p_pi' }

it('sends under the exact profileId the authenticated hello names', () => {
  expect(nativeExecutionProfile(helloFrom(native), [profile('p_pi')])).toEqual({ id: 'p_pi', harness: 'pi', displayName: 'p_pi label' })
  // Other ready profiles cannot change the answer, whichever way the list is ordered.
  expect(nativeExecutionProfile(helloFrom(native), [profile('a_first'), profile('p_pi'), profile('z_last')]))
    .toEqual({ id: 'p_pi', harness: 'pi', displayName: 'p_pi label' })
  // displayName is Server-owned; an absent one falls back to the id rather than an invented label.
  expect(nativeExecutionProfile(helloFrom(native), [{ id: 'p_pi', harness: 'pi', sendability: { state: 'ready' } }]))
    .toEqual({ id: 'p_pi', harness: 'pi', displayName: 'p_pi' })
  // A reconnect of the same Server must not re-derive the identity from list position.
  const listed = [profile('a_first'), profile('p_pi')]
  expect(nativeExecutionProfile(helloFrom(native), [...listed].reverse())).toEqual(nativeExecutionProfile(helloFrom(native), listed))
})

it('refuses a first send whose hello identity the Server does not confirm', () => {
  // An isolated hello has no nativeExecution and must not fall back to the one ready profile on offer.
  expect(refusal(() => nativeExecutionProfile(helloFrom(undefined), [profile('p_pi')]))).toMatch(/native-execution-missing/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(null), [profile('p_pi')]))).toMatch(/native-execution-missing/)
  expect(refusal(() => nativeExecutionProfile(helloFrom({ mode: 'isolated', harness: 'pi', profileId: 'p_pi' }), [profile('p_pi')]))).toMatch(/native-execution-mode/)
  for (const incomplete of [{ mode: 'native', profileId: 'p_pi' }, { mode: 'native', harness: 'pi' },
    { mode: 'native', harness: '', profileId: 'p_pi' }, { mode: 'native', harness: 'pi', profileId: '' },
    { mode: 'native', harness: 7, profileId: true }]) {
    expect(`${JSON.stringify(incomplete)}: ${refusal(() => nativeExecutionProfile(helloFrom(incomplete), [profile('p_pi')]))}`)
      .toMatch(/native-execution-incomplete/)
  }
  // A harness the Server never registered is not the harness this connection runs under.
  expect(refusal(() => nativeExecutionProfile(helloFrom({ mode: 'native', harness: 'codex', profileId: 'p_codex' }), [profile('p_codex', 'codex')]))).toMatch(/native-harness-unregistered/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(native, []), [profile('p_pi')]))).toMatch(/native-harness-unregistered/)
  // The named profile must exist, be unarchived, belong to that harness, and be able to accept a turn.
  expect(refusal(() => nativeExecutionProfile(helloFrom(native), [profile('p_other')]))).toMatch(/native-profile-unlisted/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(native), []))).toMatch(/native-profile-unlisted/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(native), [profile('p_pi', 'pi', { archivedAt: '2026-09-01T00:00:00Z' })]))).toMatch(/native-profile-archived/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(native), [profile('p_pi', 'codex')]))).toMatch(/native-profile-harness-mismatch/)
  // A Server that cannot read sendability says `unknown`, which is not permission to send.
  for (const state of ['blocked', 'unknown']) expect(`${state}: ${refusal(() => nativeExecutionProfile(helloFrom(native), [profile('p_pi', 'pi', { sendability: { state } })]))}`)
    .toMatch(/native-profile-not-ready/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(native), [{ id: 'p_pi', harness: 'pi' }]))).toMatch(/native-profile-not-ready/)
  expect(refusal(() => nativeExecutionProfile(helloFrom(native), [profile('p_pi', 'pi', { recoveryPending: true })]))).toMatch(/native-profile-recovery-pending/)
})

// ---------------------------------------------------------------------------
// FC-0055 and FC-0057: a deterministic project loss and a provably unsettled send are different answers.
// These drive the real half through its own frames, so the ledger — not a unit call — proves that a
// refusal before the send never reaches `sessions.createAndSend` and never queries an outcome for it.

const REQUEST_ID = 'draft_11111111-1111-4111-8111-111111111111'
const HELLO_FRAME = {
  serverId: 'server_1', protocolVersion: 'wire/1',
  capabilities: ['workspaces.list', 'workspaces.open', 'profiles.list', 'sessions.createAndSend', 'sessions.send', 'sendOutcome.query']
    .map(id => ({ id, supported: true })),
  harnesses: [{ id: 'pi' }], nativeExecution: { mode: 'native', harness: 'pi', profileId: 'p_pi' },
}
const DEFAULT_RESULTS: Record<string, Record<string, unknown>> = {
  'server.hello': HELLO_FRAME,
  'workspaces.list': { items: [{ id: 'W1', normalizedPath: '/repo/app', environment: { kind: 'local' }, archivedAt: null }] },
  'workspaces.open': { workspace: { id: 'W1', normalizedPath: '/repo/app', archivedAt: null } },
  'profiles.list': { items: [{ id: 'p_pi', harness: 'pi', displayName: 'Pi', sendability: { state: 'ready' }, recoveryPending: false }] },
  'sessions.createAndSend': { session: { id: 'session_7' }, outcome: 'accepted' },
  'sendOutcome.query': { outcome: 'unknown' },
}
/** A Server refusal, or `down` for a request that never reached the Server at all. */
type Reply = { result?: Record<string, unknown> } | { refuse: Record<string, unknown> } | 'down'
const refuse = (code: string, message: string, internalCode?: string): Reply =>
  ({ refuse: { code, message, ...(internalCode === undefined ? {} : { details: { internalCode } }) } })

const stubbed: string[] = []
afterEach(() => {
  for (const key of stubbed.splice(0)) delete process.env[key]
  vi.unstubAllGlobals()
})

const nativeHalf = async (replies: Record<string, Reply> = {}) => {
  const calls: { method: string; params: Record<string, unknown> }[] = []
  const fetchImpl = async (url: string, init: { body: string }) => {
    const method = url.slice(url.lastIndexOf('/') + 1)
    const body = JSON.parse(init.body) as { id: string; params: Record<string, unknown> }
    calls.push({ method, params: body.params })
    const reply: Reply = replies[method] ?? { result: DEFAULT_RESULTS[method] ?? {} }
    if (reply === 'down') throw new TypeError('connection refused')
    const envelope = 'refuse' in reply ? { id: body.id, error: reply.refuse } : { id: body.id, result: reply.result }
    return { ok: true, status: 200, json: async () => envelope } as unknown as Response
  }
  process.env.ORDESSA_SERVER_ORIGIN = 'http://127.0.0.1:41207'
  process.env.ORDESSA_SERVER_TOKEN_FILE = tokenFile().file
  stubbed.push('ORDESSA_SERVER_ORIGIN', 'ORDESSA_SERVER_TOKEN_FILE')
  vi.stubGlobal('fetch', fetchImpl)
  const connection = await createTransport().open(() => {})
  const failureOf = async (run: Promise<unknown>) => await run.then(() => undefined, error => error)
  const firstSend = () => connection.send({ method: 'createAndSend', params: { workspaceId: 'W1', text: 'fix the flaky parser spec', requestId: REQUEST_ID } })
  return { connection, calls, firstSend, failureOf, methods: () => calls.map(call => call.method) }
}

it('stops a first send whose project is already gone, before any send frame exists', async () => {
  const half = await nativeHalf({ 'workspaces.open': refuse('NOT_FOUND', 'the directory /home/maoqh/private/app is missing', 'LOCAL_PATH_MISSING') })
  const failure = await half.failureOf(half.firstSend())
  expect((failure as Error).message).toMatch(/^project-invalid: /)
  // The refusal carries the closed family and the typed code, never the Server text that quoted a host path.
  expect((failure as Error).message).toContain('LOCAL_PATH_MISSING')
  expect((failure as Error).message).not.toMatch(/home|private/)
  expect(half.methods()).toEqual(['server.hello', 'profiles.list', 'workspaces.list', 'workspaces.open'])
  await half.connection.close()
})

it('registers a picked local folder through the Server and requires it in the returned project list', async () => {
  const half = await nativeHalf()
  expect(await half.connection.send({ method: 'addProject', params: { path: '/repo/app' } }))
    .toEqual({ id: 'W1', normalizedPath: '/repo/app' })
  const opened = half.calls.find(call => call.method === 'workspaces.open')!
  expect(opened.params.path).toBe('/repo/app')
  expect(opened.params.environment).toEqual({ kind: 'local', host: null, user: null })
  expect(half.methods().slice(-2)).toEqual(['workspaces.open', 'workspaces.list'])
  await half.connection.close()
})

it('keeps a typed send-period project loss deterministic instead of asking the Server what it accepted', async () => {
  const half = await nativeHalf({ 'sessions.createAndSend': refuse('NOT_FOUND', 'the workspace is gone', 'NATIVE_PROJECT_CHANGED') })
  const failure = await half.failureOf(half.firstSend())
  expect((failure as Error).message).toMatch(/^project-invalid: /)
  expect(half.methods()).toEqual(['server.hello', 'profiles.list', 'workspaces.list', 'workspaces.open', 'sessions.createAndSend'])
  expect(half.calls.some(call => call.method === 'sendOutcome.query')).toBe(false)
  await half.connection.close()
})

it('leaves a settled send refusal exactly as the Server answered it', async () => {
  for (const code of ['NOT_FOUND', 'FORBIDDEN', 'CONFLICT_VERSION', 'INVALID_REQUEST', 'APPROVAL_INVALID']) {
    const half = await nativeHalf({ 'sessions.createAndSend': refuse(code, `${code} from the Server`) })
    const failure = await half.failureOf(half.firstSend()) as { code?: string; message?: string }
    expect(`${code}: ${failure?.code}`).toBe(`${code}: ${code}`)
    expect(`${code}: ${failure?.message}`).toContain(`${code} from the Server`)
    // One send frame, no outcome query: an answered refusal has no unknown to reserve.
    expect(`${code}: ${half.methods().filter(method => method === 'sessions.createAndSend').length}`).toBe(`${code}: 1`)
    expect(`${code}: ${half.methods().filter(method => method === 'sendOutcome.query').length}`).toBe(`${code}: 0`)
    await half.connection.close()
  }
})

it('queries only a genuinely unsettled send, and settles it under the caller’s own request id', async () => {
  const half = await nativeHalf({ 'sessions.createAndSend': refuse('UNAVAILABLE', 'the worker did not answer') })
  const failure = await half.failureOf(half.firstSend()) as { code?: string; message?: string }
  expect(failure?.code).toBe('OUTCOME_UNKNOWN')
  expect(failure?.message).toMatch(/stays reserved/)
  const sent = half.calls.filter(call => call.method === 'sessions.createAndSend')
  const queried = half.calls.filter(call => call.method === 'sendOutcome.query')
  expect(sent).toHaveLength(1)
  expect(queried).toHaveLength(1)
  // No second identity: the query is about the request the Server may already hold.
  expect(sent[0].params.requestId).toBe(REQUEST_ID)
  expect(queried[0].params.requestId).toBe(REQUEST_ID)
  await half.connection.close()
})

it('takes a real session from the outcome query when the accepted response was lost', async () => {
  const half = await nativeHalf({ 'sessions.createAndSend': 'down', 'sendOutcome.query': { result: { outcome: 'accepted', sessionId: 'session_7' } } })
  expect(await half.firstSend()).toEqual({ sessionId: 'session_7', profileId: 'p_pi' })
  expect(half.calls.filter(call => call.method === 'sessions.createAndSend')[0].params.requestId).toBe(REQUEST_ID)
  expect(half.calls.filter(call => call.method === 'sendOutcome.query')[0].params.requestId).toBe(REQUEST_ID)
  await half.connection.close()
})

it('never spends an outcome query on a first send the Server answered directly', async () => {
  const half = await nativeHalf()
  expect(await half.firstSend()).toEqual({ sessionId: 'session_7', profileId: 'p_pi' })
  expect(half.methods()).not.toContain('sendOutcome.query')
  await half.connection.close()
})

it('does not call a lost conversation with the Server a lost project', async () => {
  const half = await nativeHalf({ 'workspaces.list': 'down' })
  const failure = await half.failureOf(half.firstSend()) as { code?: string; message?: string }
  // Availability proves nothing about the pick, so the selection stays and no re-selection is demanded.
  expect(failure?.code).toBe('UNAVAILABLE')
  expect(failure?.message).not.toMatch(/project-invalid/)
  expect(half.methods()).toEqual(['server.hello', 'profiles.list', 'workspaces.list'])
  await half.connection.close()
})

it('keeps a server-authored reason out of both the code and the message', async () => {
  const half = await nativeHalf({ 'sessions.createAndSend': refuse('NOT_FOUND', 'refused', '/home/maoqh/.config/secret') })
  const failure = await half.failureOf(half.firstSend()) as { code?: string; internalCode?: string; message?: string }
  expect(failure?.code).toBe('NOT_FOUND')
  expect(failure?.internalCode).toBeUndefined()
  expect(`${failure?.message}`).not.toMatch(/home|secret/)
  await half.connection.close()
})
