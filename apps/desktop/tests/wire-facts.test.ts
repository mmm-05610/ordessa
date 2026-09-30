/**
 * B-006（I-003）：装机模式下资产扩展激活拿到 `No provider for: ordessa.wirePort.v1`。
 *
 * 真因不是 facts 时序，而是 Token 实例双重身份：打包后的宿主把
 * `runtime.ts` 的相对路径导入内联成一份 Token，扩展经契约载体
 * （`@extensions/ordessa.contracts/contract.js` → `ordessa://` 协议）拿到另一份。
 * lumino 按 Token **对象同一性**解析服务，同名不同实例即 `No provider`。
 * 仓库内测试用 `new Token('ordessa.wirePort.v1')` 复刻"消费者携带同名重份"。
 *
 * 另外钉住 facts 的活值语义：服务常注册、后到事实可见、真缺席 typed 拒绝。
 */
import { Token } from '@lumino/coreutils'
import { describe, expect, it } from 'vitest'
import { runtime } from '@ordessa/extension-host'
import type { Plugin, PluginContext } from '@ordessa/extension-api'
import type { WirePort, WireResult } from '@extensions/ordessa.contracts/contract.js'
import { WirePortToken } from '@extensions/ordessa.contracts/contract.js'
import { buildHostServices, type BridgeWireFacts } from '../renderer/host-services'

/** 与部署扩展同构的消费者：require 一个同名但**另一实例**的 wire token。 */
function wireConsumerPlugin(id: string, token: Token<WirePort>, seen: { port?: WirePort }): Plugin<unknown> {
  return {
    id,
    autoStart: true,
    requires: [token],
    activate(_context: PluginContext, port: WirePort) { seen.port = port; return {} },
  }
}

describe('B-006 宿主服务注册对 Token 重份的容忍', () => {
  it('消费者携带同名另一实例 → requires 解析成功并拿到宿主 wire 服务', async () => {
    const port = buildHostServices({ bridge: fakeBridge() }).wire
    const duplicate = new Token<WirePort>('ordessa.wirePort.v1') // 打包产物的第二实例
    const seen: { port?: WirePort } = {}
    const desktop = runtime([wireConsumerPlugin('ordessa.skills-like', duplicate, seen)], { wire: port })
    await desktop.start()
    expect(desktop.failures).toEqual([])
    expect(seen.port).toBe(port)
  })

  it('缺席的宿主服务仍然缺席：同名重份不伪造 provider（显式 No provider 语义保留）', async () => {
    const duplicate = new Token<WirePort>('ordessa.wirePort.v1')
    const seen: { port?: WirePort } = {}
    const desktop = runtime([wireConsumerPlugin('ordessa.skills-like', duplicate, seen)], {})
    await desktop.start()
    expect(desktop.failures.some(failure => failure.id === 'ordessa.skills-like' && failure.error.includes('No provider for: ordessa.wirePort.v1'))).toBe(true)
    expect(seen.port).toBeUndefined()
  })
})

describe('B-006 wire facts 活值语义（宿主常注册，后到事实可见）', () => {
  it('facts 未就绪启动：服务已注册，facts 后到 → ready/scope 对扩展可见', async () => {
    // 装配层持有的活值 cell：启动时未就绪，握手后更新。
    const cell = { ready: false, scope: null } as BridgeWireFacts
    const port = buildHostServices({ bridge: fakeBridge(), wire: cell }).wire
    expect(port.ready).toBe(false)
    expect(port.scope).toBeNull()
    // 同名重份的消费者在未就绪时激活：provider 已在，激活必成。
    const duplicate = new Token<WirePort>('ordessa.wirePort.v1')
    const seen: { port?: WirePort } = {}
    const desktop = runtime([wireConsumerPlugin('ordessa.skills-like', duplicate, seen)], { wire: port })
    await desktop.start()
    expect(desktop.failures).toEqual([])
    // 事实后到：扩展手里的是同一个 port 实例，下一次读取即见最终事实。
    cell.ready = true
    cell.scope = 'http://127.0.0.1:34323|server_476b'
    expect(seen.port!.ready).toBe(true)
    expect(seen.port!.scope).toBe('http://127.0.0.1:34323|server_476b')
  })

  it('真缺席（无宿主桥）：调用 typed 拒绝为 port-absent，绝不假绿', async () => {
    const port = buildHostServices().wire
    expect(port.ready).toBe(false)
    expect(port.scope).toBeNull()
    const result = await port.call('anything', {}) as WireResult
    expect(result.kind).toBe('Unknown')
    expect((result as { reason: string }).reason).toBe('port-absent')
  })

  it('传输层异常降级 Unknown/transport-unreachable，不冒泡', async () => {
    const port = buildHostServices({ bridge: { ...fakeBridge(), wireCall: async () => { throw Error('down') } } }).wire
    const result = await port.call('anything', {}) as WireResult
    expect(result.kind).toBe('Unknown')
    expect((result as { reason: string }).reason).toBe('transport-unreachable')
  })
})

function fakeBridge() {
  return {
    about: async () => ({}), openLicense: async () => true, faults: async () => [],
    dataRoot: async () => ({ dataRoot: '/', logsDir: '/' }), openLogs: async () => true,
    readSetting: async () => undefined, writeSetting: async () => undefined,
    settingFragments: async () => [], setLogLevel: async () => 'info',
    logHealth: async () => ({ dropped: 0, writable: true }),
    exportDiagnostics: async () => ({ exported: false }),
    wireCall: async () => ({ kind: 'Unknown', requestId: 'x', reason: 'host-not-ready' }),
    wireReady: async () => false, wireScope: async () => null,
    updateState: async () => ({}), checkUpdate: async () => ({}),
    downloadUpdate: async () => ({}), applyUpdate: async () => ({}),
  }
}
