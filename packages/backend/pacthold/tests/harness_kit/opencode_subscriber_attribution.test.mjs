/**
 * 1d 前向钉（X19）：SSE 腿上「订阅者的错」与「流的错」必须各归各位。
 *
 * 裁定的形状（C 21:31Z `H-1d-X19-attribution-fix-approach.md`）：`emit` 单独包一层 try —— **不是**
 * 移出外层保护域（移出会让同一个抛错击穿泵，那是新失败模式）。因此这里既钉"归因分开"，也钉
 * "一条流不被一个坏订阅者拆掉"：后者只有"包在里面"才成立，所以这两枚钉同时把"包 vs 移出"区分开。
 * 零对外可见面：新事实只进可选的 `AGENTBOX_DRIVER_AUDIT`，公开事件名集合不因此变宽（⑤ 反证）。
 *
 * 红-绿分工（**实测，不是预告**）：②③⑤ 在 `23945b5`（Half-A、未含 X19 修法）上为**红**——那里订阅者的错
 * 被记成 `stream-interrupted`、流被拆、独立归因键不存在；①④ 在两棵树上**都为绿**，它们是防"探针坏"与
 * 防"把修法定歪"的反向守卫。两棵树各跑一遍的 TAP 落在 `harness/work/checkpoint-1d/`。
 *
 * 边界：不 spawn 进程、不读凭据、不调模型。唯一内核动作仍是 `freePort()` 短暂 bind/listen 随机端口；
 * 全部 HTTP 由本文件临时替换的全局 `fetch` 回答，审计写 `os.tmpdir()` 下的临时目录，不落仓内。
 */
import assert from "node:assert/strict"
import { EventEmitter } from "node:events"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const DRIVER = new URL(`file://${path.join(pluginRoot, "runtime", "drivers", "opencode-native.mjs")}`)

const SESSION = "ses_1"
const MODEL = "testprov/testmodel"
const FULL_TEXT = "alpha beta gamma"

const enc = (text) => new TextEncoder().encode(text)
const tick = (ms = 1) => new Promise((resolve) => setTimeout(resolve, ms))
const settle = async (rounds = 10) => { for (let i = 0; i < rounds; i += 1) await tick(1) }

const frame = (text) => `data: ${JSON.stringify({
  type: "message.part.delta",
  properties: { sessionID: SESSION, field: "text", delta: text },
})}\n\n`

const json = (status, doc) => new Response(JSON.stringify(doc), {
  status, headers: { "content-type": "application/json" },
})

const deltaTexts = (emitted) => emitted
  .filter((m) => m.event === "message_delta")
  .map((m) => m.data.text)

function fakeChild() {
  const child = new EventEmitter()
  child.pid = 4242
  child.exitCode = null
  child.signalCode = null
  child.stderr = new EventEmitter()
  child.stdout = new EventEmitter()
  child.kill = (signal) => {
    if (child.exitCode != null || child.signalCode != null) return false
    child.signalCode = signal ?? "SIGTERM"
    child.emit("exit", null, child.signalCode)
    return true
  }
  child.once = (name, fn) => child.on(name, fn)
  child.removeAllListeners = (name) => EventEmitter.prototype.removeAllListeners.call(child, name)
  return child
}

/**
 * `subscriber(m, index, deliver)` 决定"产品侧订阅者"每一片做什么 —— ②③⑤ 的全部变量都在这一个接缝上。
 * 默认就是一名健康订阅者：把片原样交给 `deliver`（＝写进 `emitted`），① 因此不需要覆写它。
 */
async function withDriver({ recorded, subscriber, onPrompt = async () => {} }) {
  const original = globalThis.fetch
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "agentbox-1dd-"))
  const auditPath = path.join(directory, "audit.jsonl")
  const child = fakeChild()
  const emitted = []
  const sink = {}
  let calls = 0
  let seen = 0
  const flow = {
    push: (text) => sink.controller.enqueue(enc(text)),
    fail: (message) => sink.controller.error(new Error(message)),
    close: () => sink.controller.close(),
  }
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url)
    const method = options.method ?? "GET"
    if (target.endsWith("/global/health")) return json(200, { version: "pin" })
    if (target.includes("/config/providers")) {
      return json(200, { providers: [{ id: "testprov", models: { testmodel: { id: "testmodel" } } }] })
    }
    if (method === "POST" && target.endsWith("/message")) {
      calls += 1
      await onPrompt(flow, calls)
      return json(200, { info: { id: `msg_${calls}` }, parts: [{ type: "text", text: recorded(calls) }] })
    }
    if (target.includes(`/session/${SESSION}`)) return json(200, { id: SESSION, title: "pin" })
    if (target.endsWith("/event")) {
      const stream = new ReadableStream({ start(controller) { sink.controller = controller } })
      const breakBody = () => { try { sink.controller.error(new Error("This operation was aborted")) } catch {} }
      if (options.signal) {
        if (options.signal.aborted) queueMicrotask(breakBody)
        else options.signal.addEventListener("abort", breakBody, { once: true })
      }
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } })
    }
    return json(200, {})
  }
  const { createDriver } = await import(DRIVER)
  const driver = await createDriver({
    profileID: "opencode", command: "/runtime/bin/opencode", args: [],
    environment: { AGENTBOX_DRIVER_AUDIT: auditPath }, credentialEnvironment: null, hasCredential: false,
    directory, stateDirectory: null,
    emit: (message) => {
      seen += 1
      const deliver = (m) => { emitted.push(m); return m }
      return subscriber ? subscriber(message, seen, deliver) : deliver(message)
    },
    redact: (v, max) => String(v ?? "").slice(0, max),
    spawnProcess: () => child,
  })
  await driver.start()
  return {
    driver,
    emitted,
    flow,
    prompt: () => driver.prompt({ sessionId: SESSION, text: "hello", model: MODEL }),
    auditLines: () => (fs.existsSync(auditPath)
      ? fs.readFileSync(auditPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l))
      : []),
    async restore() {
      try { await driver.close() } catch { /* 关流路径上的异常不是本钉的结论 */ }
      globalThis.fetch = original
      fs.rmSync(directory, { recursive: true, force: true })
    },
  }
}

const of = (lines, event) => lines.filter((l) => l.event === event)

/* ---------------------------------------------------------- 正向对照（两树皆绿） */

test("① 正向对照：健康的订阅者不产生任何一条错记录，三片照旧全到", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    onPrompt: async (f) => { f.push(frame("alpha ")); f.push(frame("beta ")); f.push(frame("gamma")); f.close(); await settle() },
  })
  try {
    const result = await pin.prompt()
    assert.deepEqual(deltaTexts(pin.emitted), ["alpha ", "beta ", "gamma"])
    assert.equal(result.tail.outcome, "matched")
    const lines = pin.auditLines()
    assert.deepEqual(of(lines, "subscriber-error"), [], "没有订阅者抛错就不该有这条记录")
    assert.deepEqual(of(lines, "stream-interrupted"), [])
    assert.deepEqual(of(lines, "stream-pump-failed"), [])
  } finally { await pin.restore() }
})

/* --------------------------------------- ②③⑤ X19 的三枚钉（实测 `23945b5` 上为红） */

test("② 订阅者抛错被记成 `subscriber-error`，而不再冒充 `stream-interrupted` / `stream-pump-failed`", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    subscriber: (message, index, deliver) => {
      if (index === 2) throw new Error("subscriber blew up")
      deliver(message)
    },
    onPrompt: async (f) => {
      f.push(frame("alpha ")); await settle()
      f.push(frame("beta ")); await settle()
      f.push(frame("gamma")); f.close(); await settle()
    },
  })
  try {
    await pin.prompt()
    const lines = pin.auditLines()
    const subscriberErrors = of(lines, "subscriber-error")
    assert.equal(subscriberErrors.length, 1, "抛错的那一片记**一条**独立归因，不多记")
    assert.match(subscriberErrors[0].message, /subscriber blew up/)
    assert.deepEqual(of(lines, "stream-interrupted"), [],
      "X19 的错形：产品订阅者的抛错曾被外层泵的 catch 接住，记成「事件流被中断」")
    assert.deepEqual(of(lines, "stream-pump-failed"), [],
      "也不该把订阅者记成泵自身死亡 —— 那条线留给真的完整性故障（④）")
  } finally { await pin.restore() }
})

test("③ 一个坏订阅者不拆掉这条流：它抛错之后，后续帧仍送达，驱动侧文本真值不受影响", async () => {
  // 这枚钉把裁定的"包在里面"与"移出保护域"分开：移出 ⇒ 同一个抛错击穿泵 ⇒ 后续帧永远不到。
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    subscriber: (message, index, deliver) => {
      if (index === 1) throw new Error("first chunk kills me")
      deliver(message)
    },
    onPrompt: async (f) => {
      f.push(frame("alpha ")); await settle()
      f.push(frame("beta ")); f.push(frame("gamma")); f.close(); await settle()
    },
  })
  try {
    const result = await pin.prompt()
    assert.deepEqual(deltaTexts(pin.emitted), ["beta ", "gamma"],
      "第 1 片按订阅者的意愿丢了，但第 2、3 片仍被交付 ⇒ 隔离在订阅者一侧，不在流一侧")
    assert.equal(result.deltas, 3, "宿主确实流了三片，这个事实不由订阅者的健康决定")
    assert.equal(result.tail.outcome, "matched", "文本真值仍由权威记录判，未被订阅者拖成假失配")
    assert.equal(of(pin.auditLines(), "subscriber-error").length, 1)
  } finally { await pin.restore() }
})

/* ------------------------------------------ ④ 反向守卫（两树皆绿；防"把完整性故障也分错"） */

test("④ 反向：真实的读故障仍归 `stream-interrupted`，不被这次分流误吞成另两条", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    onPrompt: async (f) => {
      f.push(frame("alpha "))
      await settle()
      f.fail("connection reset")
      await settle()
    },
  })
  try {
    await pin.prompt()
    const lines = pin.auditLines()
    const interrupted = of(lines, "stream-interrupted")
    assert.equal(interrupted.length, 1, "对端把连接断了，这条事实照旧要有（1c(b) 已验收的形状）")
    assert.match(interrupted[0].message, /connection reset/)
    assert.deepEqual(of(lines, "stream-pump-failed"), [],
      "读故障不是泵自身死亡 ⇒ 不能借分流之名把它挪线")
    assert.deepEqual(of(lines, "subscriber-error"), [],
      "订阅者什么都没做 ⇒ 独立归因不该出现")
    // 泵真正死亡（错误处理分支自己抛）时的形状**不在此钉**：它需要先穿过一个"无人认领的
    // reject"空档（`pump.catch` 挂在 teardown 里），那是 X20，见 `H2` §6k.4 —— 未获批准，只测不修。
  } finally { await pin.restore() }
})

/* ---------------------- ⑤ 零对外面反证（`23945b5` 上也红：它断言"新键存在且只出现在审计里"） */

test("⑤ 零对外可见面反证：新归因只进审计，公开事件名集合不因此变宽", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    subscriber: (message, index, deliver) => { if (index === 1) throw new Error("noisy"); deliver(message) },
    onPrompt: async (f) => { f.push(frame("alpha ")); f.push(frame("beta ")); f.close(); await settle() },
  })
  try {
    await pin.prompt()
    const names = [...new Set(pin.emitted.map((m) => m.event))].sort()
    assert.deepEqual(names, ["message_delta"],
      "产品从这条腿只能看到 `message_delta`；`subscriber-error` 不是新的事件名")
    assert.ok(of(pin.auditLines(), "subscriber-error").length === 1,
      "它只存在于可选审计通道里")
  } finally { await pin.restore() }
})
