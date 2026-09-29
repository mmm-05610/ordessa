/**
 * 更新客户端的真实现（INT-01 切换点）。
 *
 * 分工（plan.md §跨包集成归属）：
 *   · **更新引擎** = 打包包 `packaging/update/client.mjs`（清单 / 签名 / 下载 / 校验 /
 *     备份 / 故障门 / `pkexec dpkg -i`）；
 *   · **本文件** = 把引擎的可观察语义适配成 `UpdateClient`，供设置页 UI 与主进程接线。
 *
 * 引擎在构建期被打进 `electron-main.cjs`，所以**安装后的应用不依赖 packaging/ 目录**。
 * 令牌与私钥都不经过本文件：签名验签用的是随包公钥，安装提权走 polkit。
 */
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import type { Fault } from '@extensions/ordessa.contracts/contract.js'
import type { UpdateClient, UpdateState } from './update-client'
import {
  backUpAndCheckCompatibility,
  checkForUpdate,
  currentDataSchema,
  downloadAndVerify,
  installDeb,
  markUpdateDone,
  markUpdateFailed,
  selfCheck,
} from '../../../packaging/update/client.mjs'

export interface UpdateEngineOptions {
  /** 更新源清单地址；缺席即视为"未配置"，检查时报可操作错误而非"已是最新"。 */
  readonly manifestUrl?: string
  /** 随包公钥（`/opt/ordessa/app/update-pubkey` 或开发覆盖）。 */
  readonly publicKeyPath: string
  readonly dataRoot: string
  readonly currentVersion: string
  readonly currentBuild: string
}

interface EngineVerdict {
  ok: boolean
  status?: string
  reason?: string
  remedy?: string
  cause?: string
  manifest?: any
  debPath?: string
}

function faultOf(verdict: EngineVerdict): Fault {
  return {
    // 源不可达与其余失败分开报：前者是网络/配置问题，后者是包或数据问题。
    kind: verdict.status === 'source-unreachable' ? 'update-source-unreachable' : 'update-failed',
    reason: verdict.reason ?? '更新失败，当前版本未改动',
    remedy: verdict.remedy ?? '稍后重试；当前版本与数据均未改动',
    logRef: 'update:apply',
    code: (verdict.status ?? 'UPDATE_FAILED').toUpperCase().replace(/-/g, '_'),
  }
}

/**
 * 真实更新客户端。状态机与 fixture 一致（UI 不改），但每一步都打到真引擎。
 */
export function createUpdateClient(options: UpdateEngineOptions): UpdateClient {
  let state: UpdateState = { state: 'idle' }
  const listeners = new Set<(s: UpdateState) => void>()
  let manifest: any = null
  let debPath: string | null = null

  const publish = (next: UpdateState) => { state = next; listeners.forEach(l => l(next)) }

  const publicKeyPem = async (): Promise<string> => {
    // 公钥是公开物，但它必须来自安装布局；缺席即更新不可用（诚实失败）。
    return readFile(options.publicKeyPath, 'utf8')
  }

  return {
    async check(): Promise<UpdateState> {
      publish({ state: 'checking' })
      if (!options.manifestUrl) {
        // FR-075：源不可达/未配置**不得**说成"已是最新"。
        const failed: EngineVerdict = {
          ok: false,
          status: 'source-unreachable',
          reason: 'UPDATE_SOURCE_NOT_CONFIGURED: 未配置更新源',
          remedy: '在设置中填写更新源地址后重试；当前版本未改动',
        }
        publish({ state: 'failed', reason: failed.reason!, fault: faultOf(failed) })
        return state
      }
      let pem: string
      try {
        pem = await publicKeyPem()
      } catch {
        const failed: EngineVerdict = {
          ok: false,
          status: 'source-unreachable',
          reason: 'UPDATE_PUBLIC_KEY_MISSING: 随包公钥缺失，无法校验更新',
          remedy: '重新安装应用后重试；当前版本未改动',
        }
        publish({ state: 'failed', reason: failed.reason!, fault: faultOf(failed) })
        return state
      }
      const verdict = await checkForUpdate({
        manifestUrl: options.manifestUrl,
        publicKeyPem: pem,
        currentVersion: options.currentVersion,
      }) as EngineVerdict
      if (!verdict.ok) {
        publish({ state: 'failed', reason: verdict.reason!, fault: faultOf(verdict) })
        return state
      }
      manifest = verdict.manifest
      const latest = manifest?.latest?.version
      publish(latest === options.currentVersion
        ? { state: 'up-to-date', current: options.currentVersion }
        : { state: 'available', version: latest, notes: manifest?.latest?.notes })
      return state
    },

    async download(): Promise<UpdateState> {
      if (state.state !== 'available' || !manifest) return state
      const version = manifest.latest.version
      publish({ state: 'downloading', version, received: 0, total: manifest.latest.deb?.size ?? 0 })
      let pem: string
      try {
        pem = await publicKeyPem()
      } catch {
        const failed: EngineVerdict = { ok: false, reason: 'UPDATE_PUBLIC_KEY_MISSING', remedy: '重新安装应用后重试' }
        publish({ state: 'failed', reason: failed.reason!, fault: faultOf(failed) })
        return state
      }
      const verdict = await downloadAndVerify({
        manifest,
        dataRoot: options.dataRoot,
        publicKeyPem: pem,
        onProgress: (received: number, total: number) =>
          publish({ state: 'downloading', version, received, total }),
      }) as EngineVerdict
      if (!verdict.ok) {
        publish({ state: 'failed', reason: verdict.reason!, fault: faultOf(verdict) })
        return state
      }
      debPath = verdict.debPath ?? null
      publish({ state: 'ready-to-install', version })
      return state
    },

    async apply(): Promise<UpdateState> {
      if (state.state !== 'ready-to-install' || !manifest || !debPath) return state
      const version = manifest.latest.version
      // C-09 §C2：备份 + 数据兼容检查**先于**安装；不兼容即中止并保留备份。
      const compat = backUpAndCheckCompatibility({
        dataRoot: options.dataRoot,
        manifest,
        currentVersion: options.currentVersion,
        currentBuild: options.currentBuild,
        currentDataSchema: currentDataSchema(options.dataRoot),
      }) as EngineVerdict
      if (!compat.ok) {
        markUpdateFailed(options.dataRoot, { reason: compat.reason!, remedy: compat.remedy })
        publish({ state: 'failed', reason: compat.reason!, fault: faultOf(compat) })
        return state
      }
      const install = await installDeb({ dataRoot: options.dataRoot, debPath }) as EngineVerdict
      if (!install.ok) {
        markUpdateFailed(options.dataRoot, { reason: install.reason!, remedy: install.remedy })
        publish({ state: 'failed', reason: install.reason!, fault: faultOf(install) })
        return state
      }
      // 成功判据：新版本自检通过才置 done（C-09 §C4）。
      const check = await selfCheck({
        expectedVersion: version,
        expectedBuild: manifest.latest.build,
        readInstalled: () => ({ version: options.currentVersion, build: options.currentBuild }),
        probeLive: () => true,
      }) as EngineVerdict
      if (!check.ok) {
        markUpdateFailed(options.dataRoot, { reason: check.reason!, remedy: check.remedy })
        publish({ state: 'failed', reason: check.reason!, fault: faultOf(check) })
        return state
      }
      markUpdateDone(options.dataRoot)
      publish({ state: 'restart-required', version })
      return state
    },

    snapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => { listeners.delete(listener) } },
    dispose() { listeners.clear() },
  }
}

/** 随包公钥的默认位置（C-09 §C1），开发态可用环境变量覆盖。 */
export function defaultPublicKeyPath(bundledRoot: string): string {
  return path.join(bundledRoot, 'app', 'update-pubkey')
}
