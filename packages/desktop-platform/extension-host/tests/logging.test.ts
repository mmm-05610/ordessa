import { afterEach, expect, it } from 'vitest'
import { mkdtemp, mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { createLogService, redactValue, type LogService } from '../src/services/logging'
import type { LogHealth, LogLevel } from '@extensions/ordessa.contracts/contract.js'

/** 金丝雀令牌：distinctive 字节，断言全链路零命中。 */
const TOKEN = 'CANARY-0f3a91c7-5d2e-4b18-9c77-1a2b3c4d5e6f'

const roots: string[] = []
const services: LogService[] = []

afterEach(async () => {
  await Promise.all(services.splice(0).map(entry => entry.close()))
  await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true })))
})

interface Fixture { root: string; logsDir: string; secretsDir: string; file: string }

/** 建一个带 secrets 目录（可选哨兵令牌）的临时数据根。 */
async function dataRoot(token: string | null = TOKEN): Promise<Fixture> {
  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-log-'))
  roots.push(root)
  const secretsDir = path.join(root, 'secrets')
  const logsDir = path.join(root, 'logs')
  await mkdir(secretsDir, { recursive: true })
  await mkdir(logsDir, { recursive: true })
  if (token !== null) { await writeFile(path.join(secretsDir, 'http-token'), token) }
  return { root, logsDir, secretsDir, file: path.join(logsDir, 'desktop.log') }
}

function service(
  file: string,
  secretsDir?: string,
  overrides: Partial<Parameters<typeof createLogService>[0]> = {},
): LogService {
  const log = createLogService({ file, secretsDir, now: () => new Date('2026-09-28T12:34:56.789Z'), ...overrides })
  services.push(log)
  return log
}

async function lines(file: string): Promise<unknown[]> {
  const content = await readFile(file, 'utf8')
  return content.split('\n').filter(line => line !== '').map(line => JSON.parse(line) as unknown)
}

it('writes JSON Lines with the field order ts/level/scope/msg then extra fields (C-04 §2)', async () => {
  const { file, secretsDir } = await dataRoot(null)
  service(file, secretsDir).info('session started', { sessionId: 'abc' })
  const raw = (await readFile(file, 'utf8')).trim()
  expect(Object.keys(JSON.parse(raw) as object)).toEqual(['ts', 'level', 'scope', 'msg', 'sessionId'])
  const [record] = await lines(file) as { ts: string; scope: string }[]
  expect(record.ts).toBe('2026-09-28T12:34:56.789Z')
  expect(record.scope).toBe('host.desktop')
})

it('nests child scopes joined by a dot and never throws (C-04 §1)', async () => {
  const { file, secretsDir } = await dataRoot(null)
  const log = service(file, secretsDir)
  log.child('plugin.demo').child('inner').warn('nested')
  expect(() => { log.child(undefined as unknown as string).info('degraded child') }).not.toThrow()
  const scopes = (await lines(file)).map(record => (record as { scope: string }).scope)
  expect(scopes).toEqual(['host.desktop.plugin.demo.inner', 'host.desktop'])
})

it('applies the field-name rule case-insensitively through nested objects and arrays (C-04 §4.1)', async () => {
  const { file, secretsDir } = await dataRoot(null)
  service(file, secretsDir).info('fields', {
    Authorization: 'Basic zzz',
    apiKey: 'k',
    nested: { userPassword: 'p', keep: 'visible' },
    list: [{ bearerToken: 't' }, 'plain'],
  })
  const [record] = await lines(file) as Record<string, unknown>[]
  expect(record.Authorization).toBe('[redacted]')
  expect(record.apiKey).toBe('[redacted]')
  expect(record.nested).toEqual({ userPassword: '[redacted]', keep: 'visible' })
  expect(record.list).toEqual([{ bearerToken: '[redacted]' }, 'plain'])
})

it('redacts sentinel bytes under any key, in msg text and inside embedded URLs (C-04 §4.2)', async () => {
  const { file, secretsDir } = await dataRoot()
  const log = service(file, secretsDir)
  log.info('plain', { myKey: TOKEN })
  log.info(`connecting to https://127.0.0.1:1/?t=${TOKEN} done`)
  const raw = await readFile(file, 'utf8')
  expect(raw.split(TOKEN)).toHaveLength(1)
  expect(raw).toContain('[redacted]')
})

it('replaces a value that points into the secrets dir entirely and never echoes it (C-04 §4.3)', async () => {
  const { root, file, secretsDir } = await dataRoot()
  service(file, secretsDir).info('locator', { credentialFile: path.join(secretsDir, 'http-token') })
  const raw = await readFile(file, 'utf8')
  expect(raw).not.toContain(root)
  expect(raw).toContain('[redacted]')
})

it('reduces path-shaped values to their basename with a truncation marker (C-04 §4.4)', async () => {
  const { file, secretsDir } = await dataRoot(null)
  service(file, secretsDir).info('paths', {
    logPath: '/var/home/user/data/logs/desktop.log',
    configFile: 'C:\\Users\\u\\app.json',
  })
  const [record] = await lines(file) as Record<string, string>[]
  expect(record.logPath).toBe('…/desktop.log')
  expect(record.configFile).toBe('…/app.json')
})

it('rotates by size, keeps at most keep generations and bounds disk growth (C-04 §3)', async () => {
  const { logsDir, file, secretsDir } = await dataRoot(null)
  const log = service(file, secretsDir, { maxBytes: 400, keep: 3 })
  for (let index = 0; index < 40; index += 1) { log.info(`line ${index}`, { padding: 'x'.repeat(60) }) }
  await log.close()
  const names = (await readdir(logsDir)).sort()
  expect(names).toEqual(['desktop.log', 'desktop.log.1', 'desktop.log.2'])
  const contents = await Promise.all(names.map(name => readFile(path.join(logsDir, name), 'utf8')))
  expect(contents.every(text => text.length < 1000)).toBe(true)
})

it('keeps the main flow working when the sink is unwritable and counts the drops (C-04 §6)', async () => {
  const { root, secretsDir } = await dataRoot(null)
  // 在普通文件之下建目录必然失败：等价于磁盘满/权限拒绝。
  const blocker = path.join(root, 'blocker')
  await writeFile(blocker, 'not a directory')
  const log = service(path.join(blocker, 'desktop.log'), secretsDir)
  expect(() => { log.info('still fine'); log.error('also fine') }).not.toThrow()
  expect(log.stats().dropped).toBeGreaterThan(0)
  expect(log.stats().writable).toBe(false)
  expect(log.health.lastError).not.toBeNull()
})

it('raises a visible warning once consecutive failures reach the threshold (C-04 §6)', async () => {
  const { root, secretsDir } = await dataRoot(null)
  const blocker = path.join(root, 'blocker')
  await writeFile(blocker, 'not a directory')
  const seen: LogHealth[] = []
  const log = service(path.join(blocker, 'desktop.log'), secretsDir, { onUnwritable: health => { seen.push(health) } })
  for (let index = 0; index < 3; index += 1) { log.info('again') }
  expect(seen).toHaveLength(1)
  expect(seen[0]?.consecutiveFailures).toBeGreaterThanOrEqual(3)
  expect(seen[0]?.writable).toBe(false)
})

it('changes level immediately without a restart and defaults to info (C-04 §7)', async () => {
  const { file, secretsDir } = await dataRoot(null)
  const log = service(file, secretsDir)
  expect(log.getLevel()).toBe('info')
  log.debug('hidden')
  log.setLevel('debug')
  expect(log.getLevel()).toBe('debug')
  log.debug('visible')
  const messages = (await lines(file)).map(record => (record as { msg: string }).msg)
  expect(messages).toEqual(['visible'])
})

it('drops non-JSON field values and breaks cycles without losing the record (C-04 §1)', async () => {
  const { file, secretsDir } = await dataRoot(null)
  const cyclic: Record<string, unknown> = { name: 'loop' }
  cyclic.self = cyclic
  service(file, secretsDir).info('mixed', {
    fn: (): number => 1,
    sym: Symbol('nope'),
    missing: undefined,
    big: BigInt(1),
    cyclic,
    keep: 'yes',
  } as Record<string, unknown>)
  const [record] = await lines(file) as Record<string, unknown>[]
  expect(record).toEqual({
    ts: '2026-09-28T12:34:56.789Z',
    level: 'info',
    scope: 'host.desktop',
    msg: 'mixed',
    cyclic: { name: 'loop' },
    keep: 'yes',
  })
})

it('exposes redactValue as a standalone redaction entry point for arbitrary trees', () => {
  const redacted = redactValue({ a: { b: [{ token: TOKEN }] }, p: '/data/root/file.db' }, { secrets: [TOKEN] })
  expect(redacted).toEqual({ a: { b: [{ token: '[redacted]' }] }, p: '…/file.db' })
})

it('CANARY: token bytes never reach the log files, in all three leak shapes (C-04 §8)', async () => {
  const { logsDir, file, secretsDir } = await dataRoot()
  const log = service(file, secretsDir)
  log.info('field name', { token: TOKEN })
  log.info('renamed field', { myKey: TOKEN })
  log.info(`bearer ${TOKEN}`)
  await log.close()
  const written = await Promise.all((await readdir(logsDir)).map(name => readFile(path.join(logsDir, name), 'utf8')))
  expect(written.length).toBeGreaterThan(0)
  for (const text of written) {
    expect(text.split(TOKEN)).toHaveLength(1)
    expect(text).toContain('[redacted]')
  }
})

it('reports health facts for the settings UI and closes idempotently', async () => {
  const { file, secretsDir } = await dataRoot(null)
  const log = service(file, secretsDir)
  log.info('once')
  expect(log.stats()).toEqual({ dropped: 0, writable: true })
  await expect(log.close()).resolves.toBeUndefined()
  await expect(log.close()).resolves.toBeUndefined()
  log.info('after close')
  expect(await lines(file)).toHaveLength(1)
})

it('ignores an unknown level instead of throwing', () => {
  const { file, secretsDir } = { file: '/tmp/unused-level.log', secretsDir: undefined }
  const log = service(file, secretsDir)
  expect(() => { log.setLevel('verbose' as LogLevel) }).not.toThrow()
  expect(log.getLevel()).toBe('info')
})
