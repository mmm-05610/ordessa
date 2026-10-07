/**
 * C-04 — 日志 sink（宿主实现）。
 *
 * 契约文本：`specs/013-desktop-product/contracts/C-04-logging.md`（冻结，只读）。
 *
 * 设计要点：
 *  - 脱敏在 sink 统一入口强制（C-04 §4），调用方无法绕过；`redactValue` 单独导出
 *    供诊断收集器与测试复用，保证日志与诊断走同一套规则。
 *  - 任何日志调用都不抛（C-04 §1/§6）：写失败只计数，连续失败达阈值回调
 *    `onUnwritable`，交由 UI 显示"日志不可写"。
 *  - 轮转按大小（C-04 §3），保留份数含当前文件，超出的直接删除，磁盘增长有界。
 */

import fs from 'node:fs'
import path from 'node:path'
import type { LogFields, Logger, LogHealth, LogLevel } from '@extensions/ordessa.contracts/contract.js'

/** 默认 scope：宿主自身。 */
const DEFAULT_SCOPE = 'host.desktop'
/** 默认轮转阈值 10 MiB（C-04 §3）。 */
const DEFAULT_MAX_BYTES = 10 * 1024 * 1024
/** 默认保留份数（含当前文件，C-04 §3）。 */
const DEFAULT_KEEP = 5
/** 连续写失败达到该次数即告警（C-04 §6，不静默）。 */
const UNWRITABLE_THRESHOLD = 3
/** 嵌套深度上限，避免深层结构拖垮序列化。 */
const MAX_DEPTH = 8
/** 哨兵令牌的最小可信长度，过短的值不参与子串匹配以免误伤。 */
const MIN_SENTINEL_LENGTH = 8
/** 哨兵重新读取的最小间隔（毫秒），兼顾令牌轮换与每行一次读取的成本。 */
const SECRET_REFRESH_MS = 1000

/** 字段名规则命中即整体脱敏（C-04 §4.1）。 */
const SENSITIVE_KEY = /token|secret|password|credential|authorization|bearer|apikey|api_key/i
/** 定位符规则的键名后缀（C-04 §4.4）。 */
const LOCATOR_KEY = /(?:path|file|dir)$/i
/** 路径型取值：POSIX 绝对路径、Windows 盘符路径、UNC 路径。 */
const ABSOLUTE_PATH = /^(?:\/|[A-Za-z]:[\\/]|\\\\)/
/** 含分隔符的取值同样按路径处理（相对路径也算定位符）。 */
const HAS_SEPARATOR = /[\\/]/

const REDACTED = '[redacted]'
/** 被截断的定位符标记：只保留 basename，目录前缀永不出现。 */
const TRUNCATED = '…/'

const LEVEL_ORDER: Readonly<Record<LogLevel, number>> = { debug: 10, info: 20, warn: 30, error: 40 }

export interface LogSinkOptions {
  /** 日志文件绝对路径，如 `${dataRoot}/logs/desktop.log`。 */
  file: string
  /** secrets 目录绝对路径（`${dataRoot}/secrets`）；其内容永不读取、永不落盘、永不进日志。 */
  secretsDir?: string
  /** 默认 `info`（C-04 §7）。 */
  level?: LogLevel
  /** 轮转阈值，默认 10 MiB。 */
  maxBytes?: number
  /** 保留份数（含当前文件），默认 5。 */
  keep?: number
  /** 可注入时钟，便于确定性测试。 */
  now?: () => Date
  /** 连续写失败达到阈值时的告警回调（C-04 §6）。 */
  onUnwritable?: (health: LogHealth) => void
}

export interface LogService extends Logger {
  readonly health: LogHealth
  /** 立即生效，无需重启（C-04 §7）。 */
  setLevel(level: LogLevel): void
  getLevel(): LogLevel
  /** 落盘并关闭句柄；可重复调用，绝不抛。 */
  close(): Promise<void>
  /** 给设置页用的健康事实结构化视图。 */
  stats(): { readonly dropped: number; readonly writable: boolean }
}

// --- 脱敏 --------------------------------------------------------------------

interface RedactContext {
  readonly secretsDir: string | undefined
  readonly secrets: readonly string[]
}

function isSafeKey(key: string): boolean {
  return key !== '__proto__' && key !== 'constructor' && key !== 'prototype'
}

/** 值是否落在 secrets 目录之下（C-04 §4.3：这类值整值替换，不保留任何片段）。 */
function underSecretsDir(value: string, secretsDir: string | undefined): boolean {
  if (secretsDir === undefined || value === '') { return false }
  const abs = path.resolve(value)
  const root = path.resolve(secretsDir)
  return abs === root || abs.startsWith(root + path.sep)
}

/** 取 basename 并加截断标记（C-04 §4.4）。 */
function toLocator(value: string): string {
  // path.basename 在非 Windows 主机上不识别反斜杠，这里跨平台切分。
  return TRUNCATED + (value.split(/[\\/]/).pop() ?? value)
}

/** 哨兵规则：子串替换覆盖正文/消息/嵌入 URL/堆栈；整值等于令牌则整体替换（C-04 §4.2）。 */
function redactSentinels(text: string, secrets: readonly string[]): string {
  let out = text
  for (const secret of secrets) {
    if (secret.length < MIN_SENTINEL_LENGTH || !out.includes(secret)) { continue }
    out = out.split(secret).join(REDACTED)
  }
  return out
}

function redactScalar(value: string, key: string | undefined, ctx: RedactContext): string {
  // 顺序即优先级：字段名 > secrets 路径 > 定位符 > 哨兵。
  if (key !== undefined && SENSITIVE_KEY.test(key)) { return REDACTED }
  if (underSecretsDir(value, ctx.secretsDir)) { return REDACTED }
  if (ABSOLUTE_PATH.test(value) || HAS_SEPARATOR.test(value)) {
    if (key !== undefined && LOCATOR_KEY.test(key)) { return toLocator(value) }
    if (ABSOLUTE_PATH.test(value)) { return toLocator(value) }
  }
  return redactSentinels(value, ctx.secrets)
}

function redactEntry(
  value: unknown,
  key: string | undefined,
  ctx: RedactContext,
  depth: number,
  seen: Set<object>,
): unknown {
  if (value === null) { return null }
  switch (typeof value) {
    case 'string': { return redactScalar(value, key, ctx) }
    case 'number': { return Number.isFinite(value) ? value : undefined }
    case 'boolean': { return value }
    case 'object': { break }
    // 函数/符号/undefined/BigInt 不是普通 JSON 值，整字段丢弃（C-04 §1）。
    default: { return undefined }
  }
  if (depth >= MAX_DEPTH) { return undefined }
  const obj = value as object
  if (seen.has(obj)) { return undefined }   // 环：丢弃该字段，不得崩溃
  seen.add(obj)
  try {
    if (Array.isArray(obj)) {
      const out: unknown[] = []
      for (const item of obj as unknown[]) {
        const redacted = redactEntry(item, undefined, ctx, depth + 1, seen)
        if (redacted !== undefined) { out.push(redacted) }
      }
      return out
    }
    const proto = Object.getPrototypeOf(obj)
    if (proto !== Object.prototype && proto !== null) {
      return undefined   // 非普通对象（Date/Map/Error…）不作为 JSON 字段透传
    }
    const out: Record<string, unknown> = {}
    for (const [key2, inner] of Object.entries(obj as Record<string, unknown>)) {
      if (!isSafeKey(key2)) { continue }
      const redacted = redactEntry(inner, key2, ctx, depth + 1, seen)
      if (redacted !== undefined) { out[key2] = redacted }
    }
    return out
  } finally {
    seen.delete(obj)
  }
}

/**
 * 对任意 JSON 值树执行 C-04 §4 全套脱敏。诊断收集器与测试共用此入口，
 * 保证"日志里安全"与"诊断包里安全"是同一套规则。
 */
export function redactValue(
  value: unknown,
  ctx: { secretsDir?: string; secrets: readonly string[] },
): unknown {
  try {
    return redactEntry(value, undefined, { secretsDir: ctx.secretsDir, secrets: ctx.secrets }, 0, new Set())
  } catch {
    return undefined   // 脱敏自身失败也不得把主流程带崩
  }
}

// --- sink --------------------------------------------------------------------

interface MutableHealth {
  writable: boolean
  dropped: number
  consecutiveFailures: number
  lastError: string | null
}

function snapshot(health: MutableHealth): LogHealth {
  return {
    writable: health.writable,
    dropped: health.dropped,
    consecutiveFailures: health.consecutiveFailures,
    lastError: health.lastError,
  }
}

export function createLogService(options: LogSinkOptions): LogService {
  const file = options.file
  const secretsDir = options.secretsDir
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES
  const keep = Math.max(1, options.keep ?? DEFAULT_KEEP)
  const now = options.now ?? ((): Date => new Date())
  const onUnwritable = options.onUnwritable

  let level: LogLevel = options.level ?? 'info'
  let fd: number | null = null
  let closed = false
  let warnFired = false
  let secrets: readonly string[] = []
  let lastSecretRead = -Infinity
  const health: MutableHealth = { writable: true, dropped: 0, consecutiveFailures: 0, lastError: null }

  function refreshSecrets(): void {
    if (secretsDir === undefined) { return }
    const stamp = Date.now()
    if (stamp - lastSecretRead < SECRET_REFRESH_MS) { return }
    lastSecretRead = stamp
    const found: string[] = []
    try {
      // 只读取哨兵文件本身；secrets 目录下的其余内容永不读取（C-04 §4.3）。
      const raw = fs.readFileSync(path.join(secretsDir, 'http-token'), 'utf8').trim()
      if (raw.length >= MIN_SENTINEL_LENGTH) { found.push(raw) }
    } catch {
      // 令牌尚未生成：留空，后续写入再试。
    }
    secrets = found
  }

  function fail(error: unknown): void {
    health.writable = false
    health.dropped += 1
    health.consecutiveFailures += 1
    health.lastError = error instanceof Error ? error.message : String(error)
    if (health.consecutiveFailures >= UNWRITABLE_THRESHOLD && !warnFired) {
      warnFired = true
      try { onUnwritable?.(snapshot(health)) } catch { /* 告警回调自身失败也不外溢 */ }
    }
  }

  function succeed(): void {
    health.writable = true
    health.consecutiveFailures = 0
    health.lastError = null
  }

  function closeFd(): void {
    if (fd !== null) {
      try { fs.closeSync(fd) } catch { /* 关闭失败不影响主流程 */ }
      fd = null
    }
  }

  function rotate(): void {
    // 代际上移：最旧的一代被直接覆盖丢弃，磁盘上最多 keep 份（含当前文件）。
    try { fs.rmSync(`${file}.${keep}`, { force: true }) } catch { /* 不存在即无需删除 */ }
    for (let index = keep - 2; index >= 1; index -= 1) {
      try {
        if (fs.existsSync(`${file}.${index}`)) { fs.renameSync(`${file}.${index}`, `${file}.${index + 1}`) }
      } catch (error) {
        fail(error)
      }
    }
    try {
      fs.renameSync(file, `${file}.1`)
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') { fail(error) }
    }
    closeFd()
  }

  function openFd(): number | null {
    if (fd !== null) { return fd }
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true })
      fd = fs.openSync(file, 'a')
      succeed()
    } catch (error) {
      fail(error)
      return null
    }
    return fd
  }

  function needsRotation(size: number): boolean {
    try {
      if (!fs.existsSync(file)) { return false }
      return fs.statSync(file).size + size > maxBytes
    } catch {
      return false
    }
  }

  function emit(levelName: LogLevel, scope: string, msg: unknown, fields: LogFields | undefined): void {
    if (closed) { return }
    if (LEVEL_ORDER[levelName] < LEVEL_ORDER[level]) { return }
    try {
      refreshSecrets()
      const ctx: RedactContext = { secretsDir, secrets }
      // 字段顺序固定为 ts/level/scope/msg，之后才是附加字段（C-04 §2，跨语言逐字一致）。
      const record: Record<string, unknown> = {
        ts: now().toISOString(),
        level: levelName,
        scope,
        msg: typeof msg === 'string' ? redactScalar(msg, undefined, ctx) : '[unloggable]',
      }
      if (fields !== null && typeof fields === 'object') {
        const redacted = redactValue(fields, ctx)
        if (redacted !== null && typeof redacted === 'object' && !Array.isArray(redacted)) {
          for (const [key, value] of Object.entries(redacted as Record<string, unknown>)) {
            if (isSafeKey(key) && key !== 'ts' && key !== 'level' && key !== 'scope' && key !== 'msg') {
              record[key] = value
            }
          }
        }
      }
      const line = JSON.stringify(record) + '\n'
      if (needsRotation(Buffer.byteLength(line))) { rotate() }
      const handle = openFd()
      if (handle === null) { return }
      fs.writeSync(handle, line)
      succeed()
    } catch (error) {
      fail(error)
    }
  }

  function makeLogger(scope: string): Logger {
    const api: Logger = {
      debug: (msg, fields) => { emit('debug', scope, msg, fields) },
      info: (msg, fields) => { emit('info', scope, msg, fields) },
      warn: (msg, fields) => { emit('warn', scope, msg, fields) },
      error: (msg, fields) => { emit('error', scope, msg, fields) },
      child: (child: string) => {
        // child 永不抛（C-04 §1）；非法入参退化为当前 scope。
        try {
          const next = typeof child === 'string' && child.length > 0 ? `${scope}.${child}` : scope
          return makeLogger(next)
        } catch {
          return api
        }
      },
    }
    return api
  }

  const root = makeLogger(DEFAULT_SCOPE)
  return {
    debug: root.debug,
    info: root.info,
    warn: root.warn,
    error: root.error,
    child: root.child,
    get health(): LogHealth { return snapshot(health) },
    setLevel(next: LogLevel): void {
      // 立即生效，不需重启（C-04 §7）；非法取值忽略而非抛。
      if (typeof next === 'string' && next in LEVEL_ORDER) { level = next }
    },
    getLevel(): LogLevel { return level },
    async close(): Promise<void> {
      closed = true
      closeFd()
    },
    stats(): { readonly dropped: number; readonly writable: boolean } {
      return { dropped: health.dropped, writable: health.writable }
    },
  }
}
