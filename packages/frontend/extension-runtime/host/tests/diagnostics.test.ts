import { afterEach, expect, it } from 'vitest'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { inflateRawSync } from 'node:zlib'
import { collectDiagnostics, type DiagnosticsInput } from '../src/services/diagnostics'
import type { DiagnosticProvider } from '@extensions/ordessa.contracts/contract.js'

/** 金丝雀令牌：全包零命中断言（C-06 B1 硬门 / FR-061）。 */
const TOKEN = 'CANARY-0f3a91c7-5d2e-4b18-9c77-1a2b3c4d5e6f'

const roots: string[] = []
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

// --- 最小 ZIP 读回器（不依赖任何解压命令） ------------------------------------

interface Entry { name: string; method: number; text: string }

/** 从中央目录读条目，再按需 inflateRaw 解出正文。 */
function readZip(bytes: Uint8Array): Entry[] {
  const buffer = Buffer.from(bytes)
  let eocd = -1
  for (let index = buffer.length - 22; index >= 0; index -= 1) {
    if (buffer.readUInt32LE(index) === 0x06054b50) { eocd = index; break }
  }
  if (eocd < 0) { throw new Error('EOCD not found') }
  const total = buffer.readUInt16LE(eocd + 10)
  let cursor = buffer.readUInt32LE(eocd + 16)
  const entries: Entry[] = []
  for (let index = 0; index < total; index += 1) {
    if (buffer.readUInt32LE(cursor) !== 0x02014b50) { throw new Error('bad central header') }
    const method = buffer.readUInt16LE(cursor + 10)
    const compressed = buffer.readUInt32LE(cursor + 20)
    const nameLength = buffer.readUInt16LE(cursor + 28)
    const extraLength = buffer.readUInt16LE(cursor + 30)
    const commentLength = buffer.readUInt16LE(cursor + 32)
    const localOffset = buffer.readUInt32LE(cursor + 42)
    const name = buffer.toString('utf8', cursor + 46, cursor + 46 + nameLength)
    const localName = buffer.readUInt16LE(localOffset + 26)
    const localExtra = buffer.readUInt16LE(localOffset + 28)
    const start = localOffset + 30 + localName + localExtra
    const body = buffer.subarray(start, start + compressed)
    entries.push({ name, method, text: method === 8 ? inflateRawSync(body).toString('utf8') : body.toString('utf8') })
    cursor += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

// --- 夹具 ---------------------------------------------------------------------

const META = {
  appVersion: '1.4.2',
  build: '20260928.3',
  builtAt: '2026-09-28T00:00:00.000Z',
  platform: 'linux-x64',
  productManifestSha256: 'a'.repeat(64),
}

interface Fixture { root: string; logsDir: string; secretsDir: string; input: DiagnosticsInput }

async function fixture(options: { token?: string | null } & Partial<DiagnosticsInput> = {}): Promise<Fixture> {
  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-diag-'))
  roots.push(root)
  const secretsDir = path.join(root, 'secrets')
  const logsDir = path.join(root, 'logs')
  await mkdir(secretsDir, { recursive: true })
  await mkdir(logsDir, { recursive: true })
  const token = options.token === undefined ? TOKEN : options.token
  if (token !== null) { await writeFile(path.join(secretsDir, 'http-token'), token) }
  const input: DiagnosticsInput = {
    dataRoot: root,
    secretsDir,
    logsDir,
    meta: META,
    productManifests: { 'extensions.json': '{"extensions":[]}', 'extensions.lock.json': '{"lock":1}' },
    environment: { os: 'linux', arch: 'x64', freeBytes: 1024 },
    ...options,
  }
  return { root, logsDir, secretsDir, input }
}

function provider(id: string, collect: DiagnosticProvider['collect']): DiagnosticProvider {
  return { id, collect }
}

// --- 用例 ---------------------------------------------------------------------

it('lays out the package exactly as C-06 B1 requires', async () => {
  const { input, logsDir } = await fixture()
  await writeFile(path.join(logsDir, 'desktop.log'), '{"ts":"2026-09-28T12:34:56.789Z","level":"info","scope":"host.desktop","msg":"boot"}\n')
  const result = await collectDiagnostics(input)
  expect(result.fileName).toBe('ordessa-diagnostics-1.4.2-20260928.3.zip')
  const names = readZip(result.bytes).map(entry => entry.name)
  expect(names).toEqual([
    'meta.json',
    'environment.json',
    'product-manifest.json',
    'data-root-state.json',
    'logs/desktop.log',
  ])
})

it('produces a readable archive: the reader recovers every entry body', async () => {
  const { input, logsDir } = await fixture()
  await writeFile(path.join(logsDir, 'desktop.log'), '{"ts":"2026-09-28T12:34:56.789Z","level":"info","scope":"host.desktop","msg":"boot"}\n')
  const result = await collectDiagnostics(input)
  const entries = readZip(result.bytes)
  const meta = entries.find(entry => entry.name === 'meta.json')
  expect(JSON.parse(meta?.text ?? '{}')).toMatchObject({ appVersion: '1.4.2', build: '20260928.3' })
  const manifest = entries.find(entry => entry.name === 'product-manifest.json')
  expect(JSON.parse(manifest?.text ?? '{}')).toEqual({
    'extensions.json': '{"extensions":[]}',
    'extensions.lock.json': '{"lock":1}',
  })
})

it('reports only existence, permission and lock facts in data-root-state.json', async () => {
  const { input } = await fixture()
  const entries = readZip((await collectDiagnostics(input)).bytes)
  const state = JSON.parse(entries.find(entry => entry.name === 'data-root-state.json')?.text ?? '{}')
  expect(state.dataRoot).toEqual({ exists: true, writable: true })
  expect(state.secrets).toEqual({ exists: true, collected: false })
  expect(state.lock).toEqual({ markerPresent: false })
  expect(entries.find(entry => entry.name === 'data-root-state.json')?.text).not.toContain(TOKEN)
})

it('keeps unparsable log lines as evidence but never verbatim (C-04 §5)', async () => {
  const { input, logsDir } = await fixture()
  await writeFile(
    path.join(logsDir, 'desktop.log'),
    `{"ts":"2026-09-28T12:34:56.789Z","level":"info","scope":"host.desktop","msg":"boot"}\nBROKEN LINE ${TOKEN}\n`,
  )
  const entries = readZip((await collectDiagnostics(input)).bytes)
  const text = entries.find(entry => entry.name === 'logs/desktop.log')?.text ?? ''
  const records = text.split('\n').filter(Boolean).map(line => JSON.parse(line) as Record<string, unknown>)
  expect(records).toHaveLength(2)
  expect(records[0]?.msg).toBe('boot')
  expect(records[1]?.msg).toBe('parse-failed')
  expect(String(records[1]?.raw)).toContain('[redacted]')
  expect(text).not.toContain(TOKEN)
})

it('turns a throwing provider into an unknown fragment without failing the export (C-06 B2)', async () => {
  const { input } = await fixture({
    providers: [
      provider('sample.healthy', async () => ({ ok: true })),
      provider('sample.broken', async () => { throw new Error('probe exploded') }),
    ],
  })
  const result = await collectDiagnostics(input)
  expect(result.fragments).toEqual([
    { id: 'sample.healthy', state: 'collected', data: { ok: true } },
    { id: 'sample.broken', state: 'unknown', reason: 'probe exploded' },
  ])
  expect(readZip(result.bytes).map(entry => entry.name)).toContain('plugins/sample.broken.json')
})

it('marks a provider that exceeds the 3s timeout as unknown and still exports (C-06 B2)', async () => {
  const { input } = await fixture({
    providers: [provider('sample.slow', () => new Promise<Record<string, unknown>>(() => { /* 永不落地 */ }))],
  })
  const started = Date.now()
  const result = await collectDiagnostics(input)
  expect(Date.now() - started).toBeLessThan(5000)
  expect(result.fragments[0]?.state).toBe('unknown')
  expect(String(result.fragments[0]?.state === 'unknown' ? result.fragments[0].reason : '')).toContain('timeout')
})

it('finishes the whole export within 5s even when a provider would hang for 10s (SC-009)', async () => {
  const { input } = await fixture({
    providers: [
      provider('sample.hang', () => new Promise<Record<string, unknown>>(() => { /* 10s 也不会落地 */ })),
      provider('sample.after', async () => ({ still: 'collected' })),
    ],
  })
  const started = Date.now()
  const result = await collectDiagnostics(input)
  const elapsed = Date.now() - started
  expect(elapsed).toBeLessThan(5000)
  expect(result.elapsedMs).toBeLessThan(5000)
  // 挂住的片段按 3 s 超时记 unknown，其后的片段仍被正常采集。
  expect(result.fragments).toEqual([
    { id: 'sample.hang', state: 'unknown', reason: expect.stringContaining('timeout') },
    { id: 'sample.after', state: 'collected', data: { still: 'collected' } },
  ])
  expect(readZip(result.bytes).length).toBeGreaterThan(0)
})

it('redacts contributed fragment data before it enters the package (C-06 B2)', async () => {
  const { input } = await fixture({
    providers: [provider('sample.leaky', async () => ({ myKey: TOKEN, accessToken: 'x', note: `uses ${TOKEN}` }))],
  })
  const entries = readZip((await collectDiagnostics(input)).bytes)
  const text = entries.find(entry => entry.name === 'plugins/sample.leaky.json')?.text ?? ''
  expect(text).not.toContain(TOKEN)
  expect(JSON.parse(text).data).toEqual({ myKey: '[redacted]', accessToken: '[redacted]', note: 'uses [redacted]' })
})

it('redacts environment and manifest inputs as well', async () => {
  const { input } = await fixture({
    environment: { os: 'linux', note: `key ${TOKEN}` },
    productManifests: { 'extensions.json': `{"token":"${TOKEN}"}` },
  })
  const entries = readZip((await collectDiagnostics(input)).bytes)
  for (const entry of entries) { expect(entry.text).not.toContain(TOKEN) }
  const environment = entries.find(entry => entry.name === 'environment.json')
  expect(JSON.parse(environment?.text ?? '{}')).toEqual({ os: 'linux', note: 'key [redacted]' })
})

it('treats a missing logs directory as absence, not failure (C-06 B1)', async () => {
  const { input, root } = await fixture()
  const result = await collectDiagnostics({ ...input, logsDir: path.join(root, 'nope') })
  const names = readZip(result.bytes).map(entry => entry.name)
  expect(names.some(name => name.startsWith('logs/'))).toBe(false)
  expect(names).toContain('meta.json')
})

it('CANARY: token bytes are absent from the archive and no entry path mentions secrets (FR-061)', async () => {
  const { input, logsDir } = await fixture()
  await writeFile(
    path.join(logsDir, 'desktop.log'),
    `{"ts":"2026-09-28T12:34:56.789Z","level":"info","scope":"host.desktop","msg":"raw","myKey":"${TOKEN}"}\nBROKEN ${TOKEN}\n`,
  )
  const result = await collectDiagnostics({
    ...input,
    providers: [provider('sample.leaky', async () => ({ deep: { value: TOKEN } }))],
  })
  const raw = Buffer.from(result.bytes)
  expect(raw.toString('latin1').split(TOKEN)).toHaveLength(1)
  const names = readZip(result.bytes).map(entry => entry.name)
  expect(names.filter(name => name.includes('secrets'))).toEqual([])
  for (const entry of readZip(result.bytes)) { expect(entry.text).not.toContain(TOKEN) }
})
