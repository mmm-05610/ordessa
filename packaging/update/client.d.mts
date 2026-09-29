/**
 * 类型声明：打包包的更新引擎（C-09）。
 *
 * 引擎本体是 `client.mjs`（打包包所有）；本声明只描述桌面侧适配层需要的那一小块
 * 可观察语义，**不**改变引擎的实现或所有权。构建期由 esbuild 打进 `electron-main.cjs`。
 */

export interface EngineCheckVerdict {
  ok: boolean
  status?: string
  reason?: string
  remedy?: string
  cause?: string
  manifest?: {
    latest?: {
      version?: string
      build?: string
      notes?: string
      deb?: { url?: string; size?: number; sha256?: string; signature?: string }
    }
    [k: string]: unknown
  }
}

export interface EngineVerdict {
  ok: boolean
  status?: string
  reason?: string
  remedy?: string
  cause?: string
  debPath?: string
}

export declare function checkForUpdate(opts: {
  manifestUrl: string
  publicKeyPem: string
  currentVersion: string
  timeoutMs?: number
  fetchImpl?: typeof fetch
}): Promise<EngineCheckVerdict>

export declare function downloadAndVerify(opts: {
  manifest: unknown
  dataRoot: string
  publicKeyPem: string
  fetchImpl?: typeof fetch
  onProgress?: (received: number, total: number) => void
}): Promise<EngineVerdict>

export declare function backUpAndCheckCompatibility(opts: {
  dataRoot: string
  manifest: unknown
  currentVersion: string
  currentBuild: string
  currentDataSchema: number
}): Promise<EngineVerdict> | EngineVerdict

export declare function installDeb(opts: {
  dataRoot: string
  debPath: string
  needsPrivilege?: boolean
}): Promise<EngineVerdict>

export declare function selfCheck(opts: {
  expectedVersion: string
  expectedBuild: string
  readInstalled: () => { version: string; build: string } | null
  probeLive: () => boolean | Promise<boolean>
  timeoutMs?: number
}): Promise<EngineVerdict>

export declare function markUpdateDone(dataRoot: string): void
export declare function markUpdateFailed(
  dataRoot: string,
  failure: { reason: string; remedy?: string },
): void
export declare function currentDataSchema(dataRoot: string): number
