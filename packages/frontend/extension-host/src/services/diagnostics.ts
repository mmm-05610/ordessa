/**
 * C-06 B — 诊断包收集器（宿主骨架）。
 *
 * 契约文本：`specs/013-desktop-product/contracts/C-06-settings-diagnostics.md`（冻结，只读）。
 *
 * 不变式：
 *  - 硬门（FR-061）：`secrets/` 永不收集；全包令牌字节零命中。所有取值都过
 *    C-04 的 `redactValue`，日志与诊断共用同一套脱敏。
 *  - 插件片段 3 s 超时；整体导出 5 s 预算（SC-009）。超时/异常 → `unknown` 三态，
 *    导出本身永不失败。
 */

import fs from 'node:fs/promises'
import path from 'node:path'
import type { DiagnosticFragment, DiagnosticProvider } from '@extensions/ordessa.contracts/contract.js'
import { redactValue } from './logging'
import { createZip, type ZipEntry } from './zip'

/** 插件片段超时（C-06 B2）。 */
const PROVIDER_TIMEOUT_MS = 3000
/** 整包导出预算（SC-009 / C-06 B3）。 */
const EXPORT_BUDGET_MS = 5000
/** 哨兵文件名：只用于脱敏，其内容永不进包（C-04 §4.2）。 */
const SENTINEL_FILE = 'http-token'
/** 单个日志文件的收集上限，避免一个大文件拖垮整包导出。 */
const MAX_LOG_FILE_BYTES = 4 * 1024 * 1024

export interface DiagnosticsInput {
  /** `${dataRoot}`，用于日志目录与数据根状态探测。 */
  dataRoot: string
  /** `${dataRoot}/secrets`，硬排除（C-06 B1 硬门）。 */
  secretsDir: string
  meta: {
    readonly appVersion: string
    readonly build: string
    readonly builtAt: string
    readonly platform: string
    readonly productManifestSha256: string
  }
  /** 日志目录，由收集器自行读取。 */
  logsDir: string
  /** 产品清单原始字节（extensions.json / extensions.lock.json）。 */
  productManifests?: Readonly<Record<string, string>>
  /** 环境事实，不含个人标识。 */
  environment: Readonly<Record<string, unknown>>
  /** 插件贡献的诊断片段。 */
  providers?: readonly DiagnosticProvider[]
  /** 可注入时钟，默认真实时间。 */
  now?: () => Date
}

export interface DiagnosticsResult {
  readonly fileName: string
  readonly bytes: Uint8Array
  readonly fragments: readonly DiagnosticFragment[]
  readonly elapsedMs: number
}

/** 只保留文件名里的安全字符，避免条目名穿越目录。 */
function safeName(raw: string): string {
  const cleaned = raw.replace(/[^A-Za-z0-9._-]/g, '_').replace(/^\.+/, '_')
  return cleaned.length > 0 ? cleaned.slice(0, 120) : 'unnamed'
}

async function exists(target: string): Promise<boolean> {
  try {
    await fs.access(target)
    return true
  } catch {
    return false
  }
}

async function isWritable(target: string): Promise<boolean> {
  try {
    await fs.access(target, fs.constants.W_OK)
    return true
  } catch {
    return false
  }
}

/** 读取哨兵令牌字节（只读这一个文件，其余 secrets 内容永不触碰）。 */
async function readSentinels(secretsDir: string): Promise<string[]> {
  try {
    const raw = (await fs.readFile(path.join(secretsDir, SENTINEL_FILE), 'utf8')).trim()
    return raw.length >= 8 ? [raw] : []
  } catch {
    return []
  }
}

interface RedactScope {
  readonly secretsDir: string
  readonly secrets: readonly string[]
}

/**
 * 把一个日志文件转成脱敏后的 JSON Lines（C-04 §5）：能解析的行按 C-04 §2 结构
 * 重新序列化；解析失败的行**既不丢弃也不原样入包**，先脱敏再打 `parse-failed` 标记。
 */
function normalizeLogFile(name: string, content: string, scope: RedactScope): string {
  const lines: string[] = []
  let lineNumber = 0
  for (const rawLine of content.split('\n')) {
    lineNumber += 1
    const line = rawLine.trim()
    if (line === '') { continue }
    let parsed: unknown
    try {
      parsed = JSON.parse(line)
    } catch {
      lines.push(JSON.stringify({
        ts: new Date(0).toISOString(),
        level: 'warn',
        scope: 'host.diagnostics',
        msg: 'parse-failed',
        source: name,
        line: lineNumber,
        // 证据保留，但先脱敏：原始行可能含令牌字节。
        raw: redactValue(line, scope),
      }))
      continue
    }
    const redacted = redactValue(parsed, scope)
    lines.push(JSON.stringify(redacted ?? { msg: 'unloggable' }))
  }
  return lines.length > 0 ? lines.join('\n') + '\n' : ''
}

async function collectLogs(logsDir: string, scope: RedactScope): Promise<ZipEntry[]> {
  let names: string[]
  try {
    names = (await fs.readdir(logsDir)).filter(name => !name.startsWith('.'))
  } catch {
    // 日志目录缺席是缺席，不是失败：记为无条目，不造假绿也不崩。
    return []
  }
  names.sort()
  const entries: ZipEntry[] = []
  for (const name of names) {
    try {
      const stat = await fs.stat(path.join(logsDir, name))
      if (!stat.isFile() || stat.size > MAX_LOG_FILE_BYTES) { continue }
      const content = await fs.readFile(path.join(logsDir, name), 'utf8')
      const normalized = normalizeLogFile(name, content, scope)
      if (normalized !== '') { entries.push({ name: `logs/${safeName(name)}`, data: normalized }) }
    } catch {
      // 单个日志文件读不到就跳过，其余部分照常导出。
    }
  }
  return entries
}

/** 数据根状态：只记录存在性/权限/锁事实，绝不含任何 secrets 内容（C-06 B1）。 */
async function dataRootState(input: DiagnosticsInput): Promise<Record<string, unknown>> {
  return {
    dataRoot: {
      exists: await exists(input.dataRoot),
      writable: await isWritable(input.dataRoot),
    },
    secrets: {
      exists: await exists(input.secretsDir),
      // 硬门：只探测存在性，内容永不读取。
      collected: false,
    },
    logs: {
      exists: await exists(input.logsDir),
    },
    lock: {
      markerPresent: await exists(path.join(input.dataRoot, '.data-root.lock')),
    },
  }
}

/** 片段超时包装（C-06 B2）：超时/异常都转成 `unknown` 三态，导出继续。 */
function collectFragment(provider: DiagnosticProvider, budgetMs: number): Promise<DiagnosticFragment> {
  return new Promise<DiagnosticFragment>(resolve => {
    let settled = false
    const finish = (fragment: DiagnosticFragment): void => {
      if (settled) { return }
      settled = true
      clearTimeout(timer)
      resolve(fragment)
    }
    const timer = setTimeout(() => {
      finish({ id: provider.id, state: 'unknown', reason: `timeout after ${budgetMs}ms` })
    }, budgetMs)
    timer.unref?.()
    const reason = (error: unknown): string => (error instanceof Error ? error.message : String(error))
    try {
      void Promise.resolve(provider.collect()).then(
        data => { finish({ id: provider.id, state: 'collected', data }) },
        (error: unknown) => { finish({ id: provider.id, state: 'unknown', reason: reason(error) }) },
      )
    } catch (error) {
      finish({ id: provider.id, state: 'unknown', reason: reason(error) })
    }
  })
}

export async function collectDiagnostics(input: DiagnosticsInput): Promise<DiagnosticsResult> {
  const now = input.now ?? ((): Date => new Date())
  const started = Date.now()
  const fragments: DiagnosticFragment[] = []
  const entries: ZipEntry[] = []
  const scope: RedactScope = { secretsDir: input.secretsDir, secrets: await readSentinels(input.secretsDir) }

  const build = async (): Promise<void> => {
    entries.push({
      name: 'meta.json',
      data: `${JSON.stringify({ ...input.meta, generatedAt: now().toISOString(), exportBudgetMs: EXPORT_BUDGET_MS }, null, 2)}\n`,
    })
    entries.push({
      name: 'environment.json',
      data: `${JSON.stringify(redactValue(input.environment, scope) ?? {}, null, 2)}\n`,
    })
    entries.push({
      name: 'product-manifest.json',
      data: `${JSON.stringify(redactValue(input.productManifests ?? {}, scope) ?? {}, null, 2)}\n`,
    })
    entries.push({
      name: 'data-root-state.json',
      data: `${JSON.stringify(await dataRootState(input), null, 2)}\n`,
    })
    entries.push(...await collectLogs(input.logsDir, scope))
    for (const provider of input.providers ?? []) {
      // 片段预算取 3 s 与整包剩余时间的较小者。
      const remaining = EXPORT_BUDGET_MS - (Date.now() - started)
      fragments.push(await collectFragment(provider, Math.max(0, Math.min(PROVIDER_TIMEOUT_MS, remaining))))
    }
  }

  // 整包预算兜底：即便某个环节挂住也必须在 5 s 内返回（SC-009）。
  const deadline = new Promise<void>(resolve => {
    const timer = setTimeout(resolve, EXPORT_BUDGET_MS)
    timer.unref?.()
  })
  await Promise.race([build().catch(() => { /* 收集失败仍产出骨架包，不崩也不假绿 */ }), deadline])

  for (const fragment of fragments) {
    const body = fragment.state === 'collected'
      ? { id: fragment.id, state: 'collected', data: redactValue(fragment.data, scope) }
      : { id: fragment.id, state: 'unknown', reason: redactValue(fragment.reason, scope) }
    entries.push({ name: `plugins/${safeName(fragment.id)}.json`, data: `${JSON.stringify(body, null, 2)}\n` })
  }

  return {
    fileName: `ordessa-diagnostics-${safeName(input.meta.appVersion)}-${safeName(input.meta.build)}.zip`,
    bytes: createZip(entries),
    fragments: [...fragments],
    // 真实墙钟耗时：SC-009 的 5 s 预算就是按它计的。
    elapsedMs: Date.now() - started,
  }
}
