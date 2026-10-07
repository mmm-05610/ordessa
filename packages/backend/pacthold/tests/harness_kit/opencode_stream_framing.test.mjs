/**
 * 1c(b) 前向钉：OpenCode 的 HTTP+SSE 腿在「边界不全」时不再静默丢字节（①④⑦）。
 *
 * 与 `harness/tests/sse-defect-evidence.test.mjs`（X17 研究仪器）的分工不同，故两份都留：
 * 那份是**双形态**的，同一文件在补丁前后两棵树上给出不同读数，用来把「缺陷形状」本身钉成事实；
 * 这份是**前向**的，只声明修好之后的行为，落在插件自己的测试面上，随 `node --test` 长期跑，
 * 防止这条腿日后被改回静默丢。基线行（`f896fe8`，含增量 1 不含 1c）上 ①④⑦ 三钉必须为红 ——
 * 那正是"钉有牙"的证明，不是回归；⑤⑧ 两行在两棵树上都必须为绿，它们是防"探针坏"与
 * 防"把正常关流写成中断假事实"的反向守卫。
 *
 * 边界：不 spawn 进程、不读凭据、不调模型、不触任何真实 OpenCode 构建。唯一的内核动作是
 * `freePort()` 在 127.0.0.1 上短暂 bind/listen 一个随机端口（产品代码要求，探针不更换它），
 * 全部 HTTP 由本文件临时替换的全局 `fetch` 回答；审计写进 `os.tmpdir()` 下的临时目录，不落仓内。
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
/** 让真的 `subscribe()` 泵把已入队的字节读走（读循环 + 解码 + emit 是若干个微任务/定时器）。 */
const settle = async (rounds = 10) => { for (let i = 0; i < rounds; i += 1) await tick(1) }

/** 一帧 SSE。`terminator: ""` = 故意缺边界的残帧（真实网络里对应一次被切断的写）。 */
const frame = (text, { terminator = "\n\n" } = {}) => `data: ${JSON.stringify({
  type: "message.part.delta",
  properties: { sessionID: SESSION, field: "text", delta: text },
})}${terminator}`

const json = (status, doc) => new Response(JSON.stringify(doc), {
  status, headers: { "content-type": "application/json" },
})

const deltaTexts = (emitted) => emitted
  .filter((m) => m.event === "message_delta")
  .map((m) => m.data.text)

/** 一个"活着且能被关掉"的假子进程，只满足 ManagedOpenCodeHost 实际读到的面。 */
function fakeChild() {
  const child = new EventEmitter()
  child.pid = 4242
  child.exitCode = null
  child.signalCode = null
  child.stderr = new EventEmitter()
  child.stdout = new EventEmitter()
  // `close()` 的 waitForExit 只看派生自 exitCode/signalCode 的 processID
  // ⇒ 假的 kill 必须把这两个字段落地，否则关流会白等两轮超时。
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
 * 起一个真驱动：全局 `fetch` 被 stub，SSE 的 `/event` 由 `flow` 逐次投放，
 * 因此每个字节何时到、什么时候断、什么时候缺边界都由各行自己决定。
 * `onPrompt(flow, callIndex)` 在 fake 的 `POST /session/{id}/message` 返回前被 await，
 * 用来模拟"这一轮里宿主正在流"的真实时序。
 *
 * 订阅贯穿多轮 ⇒ 一次 `withDriver` 可发多轮 `prompt()`，⑦ 需要这个形状。
 */
async function withDriver({ recorded, onPrompt = async () => {} }) {
  const original = globalThis.fetch
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "agentbox-1cb-"))
  const auditPath = path.join(directory, "audit.jsonl")
  const child = fakeChild()
  const emitted = []
  const sink = {}
  let calls = 0
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
      // 真的 `fetch` 会把 `options.signal` 接到流上：abort 时正在 pending 的 `read()` 会 reject。
      // 不接这个信号，⑧ 那条"正常关流不得写成中断"的守卫就是空的（它会在一个假的对端上跑）。
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
    emit: (m) => emitted.push(m),
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

/* ------------------------------------------------------------ 正向对照（两树皆绿） */

test("⑤ 正向对照：边界齐备、在本轮内流完的 SSE ⇒ 每片都到产品，结论 matched，且没有尾巴可报", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    onPrompt: async (f) => { f.push(frame("alpha ")); f.push(frame("beta ")); f.push(frame("gamma")); await settle() },
  })
  try {
    const result = await pin.prompt()
    assert.deepEqual(deltaTexts(pin.emitted), ["alpha ", "beta ", "gamma"],
      "三片都送达 ⇒ 注入路径确实跑在真的 subscribe() 泵上，下面各钉的红不是探针自身造成的")
    assert.equal(result.deltas, 3)
    assert.equal(result.tail.outcome, "matched")
    assert.equal(result.tail.emittedCharacters, 0, "流与记录一致时不补发")
    assert.deepEqual(of(pin.auditLines(), "stream-tail"), [], "没有残尾就不该有 stream-tail 记录")
  } finally { await pin.restore() }
})

/* ------------------------------------------------------ 1c(b) 的三钉（基线必须为红） */

test("① `done` 冲刷缓冲区 ⇒ 末块缺边界也不从 SSE 侧静默消失", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    onPrompt: async (f) => {
      f.push(frame("alpha "))
      f.push(frame("beta "))
      f.push(frame("gamma", { terminator: "" }))  // 残帧：合法写被切断
      f.close()                                    // 流干净地结束（不是错误）
      await settle()
    },
  })
  try {
    const result = await pin.prompt()
    assert.equal(result.deltas, 3, "末块在 done 时被冲出并解出 ⇒ 三片都在")
    assert.equal(result.tail.outcome, "matched", "流与权威记录一致，不再需要整段补发")
    const tails = of(pin.auditLines(), "stream-tail")
    assert.equal(tails.length, 1)
    assert.equal(tails[0].reason, "done")
    assert.equal(tails[0].dataLines, 1, "冲刷里确实有一行 data，这个事实被记下来而不是消失")
    assert.equal(tails[0].undecodable, 0, "它可解 ⇒ 这一轮没有丢内容")
    assert.ok(tails[0].characters > 0)
  } finally { await pin.restore() }
})

test("④ pump 的 reader 抛错不再被吞：已收到的部分保住，错误留痕，且带走的字节有界", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    onPrompt: async (f) => {
      f.push(frame("alpha "))
      f.push(frame("beta ", { terminator: "" }))
      // 先把已入队的字节交给泵：区分「驱动自己 buffer 里的字节」（可救）与
      // 「入队但未被 read() 取走的字节」（被 errored 状态清空，驱动从未拿到，不可救）。
      await settle()
      f.fail("connection reset")
      await settle()
    },
  })
  try {
    const result = await pin.prompt()
    assert.equal(result.deltas, 2,
      "已到达驱动 buffer 的残帧由错误路径冲刷出来；只有「入队未读」的那部分才是不可恢复的损失")
    assert.equal(result.tail.outcome, "completed")
    assert.equal(result.tail.emittedCharacters, "gamma".length,
      "补发从「beta gamma」缩到「gamma」⇒ 驱动手里的字节不再被错误一并带走，损失变小且有界")
    const interrupted = of(pin.auditLines(), "stream-interrupted")
    assert.equal(interrupted.length, 1, "「事件流断了」成为一个可订阅到的事实，而不是 `catch {}` 的静默")
    assert.match(interrupted[0].message, /connection reset/)
    assert.ok(interrupted[0].pendingCharacters > 0, "错误发生时驱动手里还压着多少字节，是可报的")
    const tails = of(pin.auditLines(), "stream-tail")
    assert.deepEqual(tails.map((l) => [l.reason, l.dataLines, l.undecodable]), [["reader-error", 1, 0]])
  } finally { await pin.restore() }
})

test("⑦ 残帧不跨轮存活：轮次边界丢弃上一轮的尾巴，而丢弃本身被计数", async () => {
  const pin = await withDriver({
    recorded: (call) => (call === 1 ? "alpha " : "beta 2"),
    onPrompt: async (f, call) => {
      if (call === 1) {
        f.push(frame("alpha "))
        f.push(frame("残留尾巴").slice(0, 18))  // 一次被切断的写：无边界、也不完整
      } else {
        f.push(frame("beta 2"))                  // 完全合法的一帧
      }
      await settle()
    },
  })
  try {
    const first = await pin.prompt()
    assert.equal(first.tail.outcome, "matched", "第一轮看起来毫无问题：流与记录一致")
    assert.equal(first.deltas, 1)
    const second = await pin.prompt()
    assert.equal(second.deltas, 1,
      "上一轮的残帧不与本轮首帧粘连 ⇒ 合法的一帧按自己应得的方式被解出")
    assert.deepEqual(deltaTexts(pin.emitted).slice(-1), ["beta 2"])
    assert.equal(second.tail.outcome, "matched", "不再读作「宿主这一轮没流」")
    const discarded = of(pin.auditLines(), "stream-tail-discarded")
    assert.equal(discarded.length, 1)
    assert.ok(discarded[0].characters > 0, "丢弃是显式记账的动作，不是 `buffer` 被顺手覆盖")
  } finally { await pin.restore() }
})

/* ------------------------------------------- 反向守卫（两树皆绿；防"修出假事实"） */

test("⑧ 正常 close() 不得留下 `stream-interrupted` 或 `stream-pump-failed` 假事实", async () => {
  const pin = await withDriver({
    recorded: () => FULL_TEXT,
    onPrompt: async (f) => { f.push(frame("alpha ")); f.push(frame("beta ")); await settle() },
  })
  try {
    await pin.prompt()
    await pin.driver.close()
    // 关流后泵还在若干个微任务之外；不 await 就读审计，等于读一个还没写完的文件。
    await settle()
    const lines = pin.auditLines()
    assert.deepEqual(of(lines, "stream-interrupted"), [],
      "`stopEvents()` 会 abort controller ⇒ read() reject 进同一个 catch；那是主动收摊，不是连接被中断")
    assert.deepEqual(of(lines, "stream-pump-failed"), [],
      "`void pump` 挂的失败处理器不该在正常路径上响")
  } finally { await pin.restore() }
})
