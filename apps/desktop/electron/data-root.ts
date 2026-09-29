/**
 * 数据根（消费 C-01，定义方 P-B）。宿主只**消费**语义，不重定义布局：
 * 解析顺序 env → `~/.ordessa`，锁语义与五类类型化错误码按契约映射为故障（PA-07 / PA-12）。
 * P-B 交付 `server-bridge` 之前，这里的目录事实由本模块直接探针（不 spawn 任何服务）。
 */
import { constants } from 'node:fs'
import { access, mkdir, open, readFile, rm, stat, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import type { Fault } from '@extensions/ordessa.contracts/contract.js'

/** C-01 §6 的类型化错误码，宿主只认这五个。 */
export type DataRootCode =
  | 'DATA_ROOT_SYMLINK'
  | 'DATA_ROOT_NOT_WRITABLE'
  | 'DATA_ROOT_LOCKED'
  | 'DATA_ROOT_INVALID'
  | 'MIGRATION_REFUSED'

export const DATA_ROOT_ENV = 'ORDESSA_DATA_ROOT'
export const DEFAULT_DATA_ROOT_DIR = '.ordessa'

export function resolveDataRoot(env: Readonly<Record<string, string | undefined>>, home: string): string {
  const fromEnv = env[DATA_ROOT_ENV]
  return fromEnv && fromEnv.length > 0 ? path.resolve(fromEnv) : path.join(home, DEFAULT_DATA_ROOT_DIR)
}

export type DataRootProbe =
  | { readonly ok: true; readonly dataRoot: string; readonly logsDir: string; readonly secretsDir: string }
  | { readonly ok: false; readonly code: DataRootCode; readonly fault: Fault }

/** 只读探针：存在性、类型、权限、锁。任何一类不满足都返回带 reason/remedy 的故障，不抛异常。 */
export async function probeDataRoot(dataRoot: string, { isLive }: { isLive?: (pid: number) => boolean; now?: Date } = {}): Promise<DataRootProbe> {
  const logsDir = path.join(dataRoot, 'logs')
  const secretsDir = path.join(dataRoot, 'secrets')
  const logRef = `data-root:${path.basename(dataRoot)}`
  let info
  try { info = await stat(dataRoot) } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') {
      return { ok: false, code: 'DATA_ROOT_INVALID', fault: { kind: 'data-root-missing', reason: `数据根不可读：${String(error)}`, remedy: '检查目录权限后重启应用', logRef } }
    }
    return {
      ok: false, code: 'DATA_ROOT_INVALID',
      fault: { kind: 'data-root-missing', reason: '数据目录不存在，应用无法保存任何数据', remedy: '点击"创建数据目录"后重试，或用 ORDESSA_DATA_ROOT 指定已有目录', logRef },
    }
  }
  if (info.isSymbolicLink()) {
    return { ok: false, code: 'DATA_ROOT_SYMLINK', fault: { kind: 'data-root-missing', reason: '数据目录是符号链接，出于安全考虑拒绝使用', remedy: '改用真实目录后重启应用', logRef, code: 'DATA_ROOT_SYMLINK' } }
  }
  if (!info.isDirectory()) {
    return { ok: false, code: 'DATA_ROOT_INVALID', fault: { kind: 'data-root-missing', reason: '数据路径不是目录', remedy: '改用目录路径后重启应用', logRef, code: 'DATA_ROOT_INVALID' } }
  }
  try { await access(dataRoot, constants.W_OK) } catch {
    return { ok: false, code: 'DATA_ROOT_NOT_WRITABLE', fault: { kind: 'data-root-missing', reason: '数据目录不可写', remedy: '修正目录权限（0700）后重启应用', logRef, code: 'DATA_ROOT_NOT_WRITABLE' } }
  }
  const held = await readLock(dataRoot)
  if (held && isLive?.(held.pid)) {
    return { ok: false, code: 'DATA_ROOT_LOCKED', fault: { kind: 'data-root-locked', reason: `数据目录已被另一个 Ordessa 进程占用（pid ${held.pid}）`, remedy: '关闭另一个实例后重试；若确认无进程占用，可删除锁文件', logRef, code: 'DATA_ROOT_LOCKED' } }
  }
  return { ok: true, dataRoot, logsDir, secretsDir }
}

async function readLock(dataRoot: string): Promise<{ pid: number } | null> {
  try {
    const parsed = JSON.parse(await readFile(path.join(dataRoot, '.lock'), 'utf8')) as { pid?: unknown }
    return typeof parsed.pid === 'number' ? { pid: parsed.pid } : null
  } catch { return null }
}

/** 取得锁：先清掉已死的残留锁，再写自己的。返回释放函数。 */
export async function acquireDataRootLock(dataRoot: string,
  { isLive, pid = process.pid, host = os.hostname() }: { isLive?: (pid: number) => boolean; pid?: number; host?: string } = {}) {
  const held = await readLock(dataRoot)
  if (held && isLive?.(held.pid)) throw Object.assign(Error(`Data root locked by pid ${held.pid}`), { code: 'DATA_ROOT_LOCKED' satisfies DataRootCode })
  const file = path.join(dataRoot, '.lock')
  const handle = await open(file, 'w')
  await handle.writeFile(JSON.stringify({ pid, host, since: new Date().toISOString() }))
  return async () => { await handle.close(); await rm(file, { force: true }) }
}

/** 首次启动时创建数据根（0700 / 0600，契约要求）。 */
export async function ensureDataRoot(dataRoot: string) {
  await mkdir(dataRoot, { recursive: true, mode: 0o700 })
  await mkdir(path.join(dataRoot, 'logs'), { recursive: true, mode: 0o700 })
  await mkdir(path.join(dataRoot, 'secrets'), { recursive: true, mode: 0o700 })
  await writeFile(path.join(dataRoot, '.keep'), '', { mode: 0o600 })
  return dataRoot
}

export const defaultHome = os.homedir()
