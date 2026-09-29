/**
 * 设置存储（PA-13 / PA-14）。语义来自 C-06 §A3 与全局规则 §3：
 * 提供者卸载 → 片段隐藏但**配置保留**；未知片段 → 不下发、不崩，标记 unknown。
 * 存储是数据根里的一个 JSON 文件（0700 目录内），由主进程独占，渲染进程只经 IPC 读写。
 */
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'

export type SettingsFragmentState = 'known' | 'unknown'

export interface SettingsFragment { readonly id: string; readonly state: SettingsFragmentState; readonly value: unknown }

export interface SettingsDocument { readonly version: 1; readonly values: Readonly<Record<string, unknown>> }

/** 归一化：非法文档（坏 JSON / 非对象）→ 空文档，不崩、不丢磁盘上的原文。 */
export function normalizeDocument(parsed: unknown): SettingsDocument {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return { version: 1, values: {} }
  const values = (parsed as { values?: unknown }).values
  return { version: 1, values: values && typeof values === 'object' && !Array.isArray(values) ? values as Record<string, unknown> : {} }
}

/** 下发视图：只含**已知**提供者登记过的 id；未登记者标记 unknown 且不下发值（C-06 §A3）。 */
export function projectFragments(document: SettingsDocument, known: ReadonlySet<string>): readonly SettingsFragment[] {
  return Object.keys(document.values).sort().map((id): SettingsFragment => known.has(id)
    ? { id, state: 'known', value: document.values[id] }
    // 未知片段**不下发值**：只留 id 与状态，数据仍留在磁盘上。
    : { id, state: 'unknown', value: undefined })
}

export function createSettingsStore(file: string) {
  let document: SettingsDocument = { version: 1, values: {} }
  let loaded = false
  return {
    async load(): Promise<SettingsDocument> {
      try { document = normalizeDocument(JSON.parse(await readFile(file, 'utf8'))) }
      catch { document = { version: 1, values: {} } }
      loaded = true
      return document
    },
    get(id: string): unknown { return document.values[id] },
    /** 写入是原子的（临时文件 + rename），避免半写文件。 */
    async set(id: string, value: unknown): Promise<SettingsDocument> {
      document = { version: 1, values: { ...document.values, [id]: value } }
      await mkdir(path.dirname(file), { recursive: true, mode: 0o700 })
      const temp = file + '.tmp'
      await writeFile(temp, JSON.stringify(document, null, 2) + '\n', { mode: 0o600 })
      await rename(temp, file)
      return document
    },
    /** 卸载提供者：隐藏入口但**保留**已存配置（这里只去掉登记者，不动数据）。 */
    fragments(known: ReadonlySet<string>) { return projectFragments(document, known) },
    snapshot(): SettingsDocument { return document },
    get isLoaded() { return loaded },
  }
}
