/**
 * 1e 钉（X20）：`stream-pump-failed` 的**归因时机**与**处理器体自保护**。
 *
 * 病灶（C 01:24Z `goal/decisions/H6-split-X20-1e-ruling.md` §B 原话）："pump 在收摊之前死掉＝
 * 一条无人认领的 rejection（Node 15+ 默认策略下是真实 worker 里的**进程级事件**），且处理器自抛会
 * 连带抹掉 `stream-interrupted` 主事实"。批准范围只有两处：`.catch` 挂点移到 `pump` 创建处 ＋
 * catch 体自保护；**不改事件名、不新增 `tail.outcome` 值、不触 Half-B/④/②⑥/X18(a)**。
 *
 * 红-绿分工（**实测，不是预告**；两棵树的 TAP 落在 `harness/work/checkpoint-1e/`）：
 * ①② 在修前为红（①：`unhandledRejections=[redactor blew up]` 且 `stream-interrupted` 整条消失；
 * ②：收摊前查不到 `stream-pump-failed` ＋ 一条 unhandledRejection）；③ 在修前为红（第二条无人认领
 * 的拒绝）；④ 在两棵树上都为绿——它是"别把修法做歪成新增对外面"的反向守卫。
 *
 * 边界：不 spawn 真进程、不读凭据、不调模型；`fetch`/`redact`/`spawnProcess` 全由本文件注入。
 * 审计写在 `os.tmpdir()` 的临时目录里，不落仓内。
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

// 进程级：unhandledRejection 是这条线的**病**本身，所以它必须在模块装载时就监听，
// 每枚钉只看自己开始之后的那一段（避免跨钉污染，也避免"监听器装晚了"造成的假绿）。
const rejections = []
process.on("unhandledRejection", (reason) => rejections.push(String(reason?.message ?? reason)))

/**
 * `breaks(record)` 决定"格式化器对这个字符串抛不抛"——三枚钉的全部变量都在这一个接缝上。
 * `audit()` 会对记录里**每个字符串字段**（含 `event` 本身）调 `redact`，且那一行不在 `audit`
 * 自己的 try 里 ⇒ 让 `redact` 认 `"stream-interrupted"` 就能造出"catch 体自己抛"的泵死亡形状，
 * 不需要给驱动新开任何测试接缝。
 */
async function withDriver({ breaks = () => false }) {
  const original = globalThis.fetch
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "agentbox-1e-"))
  const auditPath = path.join(directory, "audit.jsonl")
  const emitted = []
  const sink = {}
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url)
    const method = options.method ?? "GET"
    if (target.endsWith("/global/health")) return json(200, { version: "pin" })
    if (target.includes("/config/providers")) {
      return json(200, { providers: [{ id: "testprov", models: { testmodel: { id: "testmodel" } } }] })
    }
    if (method === "POST" && target.endsWith("/message")) {
      sink.controller.enqueue(enc(frame("alpha ")))
      await settle()
      sink.controller.error(new Error("connection reset"))
      await settle()
      return json(200, { info: { id: "msg_1" }, parts: [{ type: "text", text: "alpha " }] })
    }
    if (target.includes(`/session/${SESSION}`)) return json(200, { id: SESSION })
    if (target.endsWith("/event")) {
      const stream = new ReadableStream({ start(controller) { sink.controller = controller } })
      return new Response(stream, { status: 200, headers: { "content-type": "text/event-stream" } })
    }
    return json(200, {})
  }
  const { createDriver } = await import(DRIVER)
  const driver = await createDriver({
    profileID: "opencode", command: "/runtime/bin/opencode", args: [],
    environment: { AGENTBOX_DRIVER_AUDIT: auditPath }, credentialEnvironment: null, hasCredential: false,
    directory, stateDirectory: null,
    emit: (message) => { emitted.push(message) },
    redact: (value, max) => {
      const text = String(value ?? "")
      if (breaks(text)) throw new Error(`redactor blew up on ${text}`)
      return text.slice(0, max)
    },
    spawnProcess: () => fakeChild(),
  })
  await driver.start()
  const auditEvents = () => (fs.existsSync(auditPath)
    ? fs.readFileSync(auditPath, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l).event)
    : [])
  return {
    driver, emitted, auditEvents,
    prompt: () => driver.prompt({ sessionId: SESSION, text: "hello", model: MODEL }),
    async restore() {
      try { await driver.close() } catch { /* 关流路径上的异常不是本钉的结论 */ }
      globalThis.fetch = original
      fs.rmSync(directory, { recursive: true, force: true })
    },
  }
}

const has = (events, name) => events.filter((e) => e === name).length
const newRejections = (mark) => rejections.slice(mark)

/* ------- ① 处理器自抛不得抹掉主事实（修前红：unhandledRejection ＋ `stream-interrupted` 整条消失） */

test("① 格式化器在写 `stream-interrupted` 时自抛：主事实仍要留下，且不留无人认领的拒绝", async () => {
  const mark = rejections.length
  const pin = await withDriver({ breaks: (text) => text.includes("connection reset") })
  try {
    await pin.prompt()
    await settle(20)
    const beforeClose = pin.auditEvents()
    assert.equal(has(beforeClose, "stream-interrupted"), 1,
      "修前为红：`message: redact(...)` 与记录同处一条语句，格式化器一抛就把整条主事实带走")
    assert.deepEqual(newRejections(mark), [],
      "修前为红：catch 体抛出 ⇒ 该 promise 被拒绝，而当时处理器还没挂上，是一条无人认领的拒绝")
  } finally { await pin.restore() }
})

/* --------- ② 当场归因（修前红：收摊前查不到 `stream-pump-failed`，且有一条 unhandledRejection） */

test("② 泵真的死了：`stream-pump-failed` 在收摊**之前**就要落地，不是等 close() 补记", async () => {
  const mark = rejections.length
  // 让 catch 体在**记录主事实**那一步抛 ⇒ 泵死亡，走 `.catch` 这条独立归因线。
  const pin = await withDriver({ breaks: (text) => text === "stream-interrupted" })
  try {
    await pin.prompt()
    await settle(20)
    const beforeClose = pin.auditEvents()
    assert.equal(has(beforeClose, "stream-pump-failed"), 1,
      "归因由时机决定，不由收摊决定：修前 `.catch` 只挂在 teardown 闭包里，这里必然是 0")
    assert.deepEqual(newRejections(mark), [],
      "挂点提前之后，不再有『收摊前无人认领的 rejection』这个空档")
  } finally { await pin.restore() }
})

/* ------------- ③ 处理器体自保护（修前红：第二条无人认领的拒绝；事件名与记录面不得因此变宽） */

test("③ 归因线自己也抛时，不得造出第二条未处理拒绝", async () => {
  const mark = rejections.length
  // 两条线的字符串都让它抛：catch 体抛 ⇒ 泵死 ⇒ `.catch` 里再抛。
  const pin = await withDriver({ breaks: (text) => text === "stream-interrupted" || text === "stream-pump-failed" })
  try {
    await pin.prompt()
    await settle(20)
    assert.deepEqual(newRejections(mark), [],
      "修前为红：处理器体没有自保护时，它的抛出是第二条 unhandledRejection")
  } finally { await pin.restore() }
})

/* ------------------ ④ 零对外可见面反证（两树皆绿：修法不得变成新事件名 / 新 tail 值） */

// 下面两组名字**照修前树 `1c7c76c` 抄录**（`driver-native.mjs` 里 `event: "…"` 与 `outcome: "…"`
// 的全部字面量）。用等号而不是"包含"来钉：新增任何一个名字都会红，哪怕它这一轮没被触发。
const AUDIT_NAMES = ["abort", "abort-failed", "close", "create", "host-start", "open", "prompt",
  "stream-interrupted", "stream-pump-failed", "stream-tail", "stream-tail-discarded",
  "subscriber-error", "tail-completed", "tail-mismatch"]
// `driver_exit` 是**公开** `emit` 的名字（同处还有走 `DELTA_EVENT` 常量的那一条），不是审计名；
// 把它一起放进等号右边，才不会给"新增一个带下划线的公开事件名"留出空子。
const EVENT_LITERALS = [...AUDIT_NAMES, "driver_exit"].sort()
const TAIL_OUTCOMES = ["completed", "matched", "mismatch", "record-empty", "record-only"]

// `event:` 取紧跟其后的字面量；`outcome:` 取**该行的全部**字面量（先剔掉 `=== "…"` 这类比较，
// 例如 `typeof recorded === "string"`）。两者取法不同是有原因的：outcome 的取值里有两个写在三元
// 分支上（`recorded ? "matched" : "record-empty"`），只锚在 `outcome:` 后面就会漏读，而"新增一个
// 取值"最省事的做法正是塞进三元分支 —— 所以那一行的每个字面量都得算数。
const eventLiterals = (source) => {
  const found = []
  for (const line of source.split("\n")) {
    for (const match of line.matchAll(/event:\s*"([a-z_-]+)"/g)) found.push(match[1])
  }
  return found.sort()
}
const outcomeLiterals = (source) => {
  const found = []
  for (const line of source.split("\n")) {
    if (!line.includes("outcome:")) continue
    for (const match of line.replace(/===\s*"[a-z_-]+"/g, "").matchAll(/"([a-z_-]+)"/g)) {
      found.push(match[1])
    }
  }
  return found.sort()
}

test("④ 反向守卫：新归因只进可选审计，事件名与 `tail.outcome` 取值集合不因此变宽", async () => {
  const pin = await withDriver({ breaks: (text) => text === "stream-interrupted" })
  try {
    const result = await pin.prompt()
    await settle(20)
    assert.deepEqual([...new Set(pin.emitted.map((m) => m.event))].sort(), ["message_delta"],
      "产品从这条腿只看得到 `message_delta`；`stream-pump-failed` 不是新的事件名")
    assert.ok(TAIL_OUTCOMES.includes(result.tail.outcome),
      `tail.outcome 仍是修前那五个值之一，实测为 ${result.tail.outcome}`)
    const source = fs.readFileSync(new URL(DRIVER), "utf8")
    assert.deepEqual(eventLiterals(source), EVENT_LITERALS,
      "驱动里的事件名字面量集合必须与修前逐字相同（不得借修法新增一个）")
    assert.deepEqual(outcomeLiterals(source), [...TAIL_OUTCOMES].sort(),
      "驱动里的 tail.outcome 取值字面量集合必须与修前逐字相同")
    for (const name of new Set(pin.auditEvents())) {
      assert.ok(AUDIT_NAMES.includes(name), `审计里出现了基线之外的名字：${name}`)
    }
  } finally { await pin.restore() }
})
