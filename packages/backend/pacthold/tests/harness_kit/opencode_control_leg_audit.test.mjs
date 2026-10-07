/**
 * 1c(b2) 前向钉（= 批准件里的 **X18(b)**）：控制腿 `abort()` 在被拒时**不得**留下"已完成"形状的记录。
 *
 * 与 `harness/tests/opencode_control_leg.test.mjs`（X18 研究仪器，双形态）的分工同 1c(b) 那一对：
 * 那份记录缺陷形状与补丁后形状各是什么，这份只声明**修好之后**的行为，随 `node --test` 长期跑。
 * 在 1c 之前的树（`61c1c5f`）上，②③ 两钉必须为红 —— 那正是"钉有牙"，不是回归；
 * 正向对照与"reject 无痕"两钉在两棵树上都必须为绿（前者防"探针坏"，后者钉住**本轮刻意未改**的那一行）。
 *
 * **Half-B 翻转记录（批文 04:55Z，验收 2 红-绿双向）**：末行"reject 无痕"钉钉的正是本批批准
 * 改写的那一行（X18④ 无痕→有痕 `UNKNOWN`）⇒ 该钉期望按批文翻转（`goal-H-021` §2(A) 预申报）；
 * 其余五钉字节零触、原样绿；三值归因细节由新文件 `opencode_abort_outcome_halfb.test.mjs` 承担。
 *
 * 边界：不 spawn、不读凭据、不调模型、不触真实 OpenCode 构建；全部 HTTP 由临时替换的全局 `fetch`
 * 回答；审计写进 `os.tmpdir()` 下的临时目录并自删，不落仓内。
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

const json = (status, doc) => new Response(JSON.stringify(doc ?? {}), {
  status, headers: { "content-type": "application/json" },
})

function fakeChild() {
  const child = new EventEmitter()
  child.pid = 4343
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

/** `abortBehaviour` 决定宿主怎么回答控制请求；`auditLines()` 读的是**产品会留下的那份记录**。 */
async function withDriver({ abortBehaviour = () => json(200, {}) }) {
  const original = globalThis.fetch
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "agentbox-1cb2-"))
  const auditPath = path.join(directory, "audit.jsonl")
  const emitted = []
  const requests = []
  globalThis.fetch = async (url, options = {}) => {
    const target = String(url)
    requests.push([options.method ?? "GET", target])
    if (target.endsWith("/global/health")) return json(200, { version: "pin" })
    if (target.includes("/config/providers")) return json(200, { providers: [] })
    if (target.endsWith("/event")) return new Response(new ReadableStream({ start() {} }),
      { status: 200, headers: { "content-type": "text/event-stream" } })
    if (target.endsWith("/abort")) return abortBehaviour(target)
    return json(200, {})
  }
  const { createDriver } = await import(DRIVER)
  const driver = await createDriver({
    profileID: "opencode", command: "/runtime/bin/opencode", args: [],
    environment: { AGENTBOX_DRIVER_AUDIT: auditPath }, credentialEnvironment: null, hasCredential: false,
    directory, stateDirectory: null,
    emit: (m) => emitted.push(m),
    redact: (v, max) => String(v ?? "").slice(0, max),
    spawnProcess: () => fakeChild(),
  })
  await driver.start()
  return {
    driver,
    emitted,
    requests,
    abort: () => driver.abort(SESSION),
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

const abortRecords = (lines) => lines.filter((r) => String(r.event).startsWith("abort"))

test("① 正向对照：宿主接受 abort ⇒ 恰好一条完成形状记录，不但也不多留痕", async () => {
  const pin = await withDriver({ abortBehaviour: () => json(200, {}) })
  try {
    await pin.abort()
    const records = abortRecords(pin.auditLines())
    assert.equal(records.length, 1, "一次 abort 一份记录")
    assert.equal(records[0].event, "abort", "被接受的 abort 仍记成完成形状（本钉不许把它一并改掉）")
    assert.equal(records[0].sessionId, SESSION)
  } finally { await pin.restore() }
})

test("② 宿主拒绝（HTTP 500）⇒ 盘上不得出现 completed-abort 记录，失败与状态码进同一条内部通道", async () => {
  const pin = await withDriver({ abortBehaviour: () => json(500, { error: "busy" }) })
  try {
    const returned = await pin.abort()
    assert.equal(returned, undefined, "`abort()` 仍不返回事实：返回契约是 X18(a)，按裁定归增量 2，本钉不许越界")
    assert.equal(pin.emitted.length, 0, "向上仍零事件：同理，新公开事件不在批准范围内")
    const lines = pin.auditLines()
    assert.deepEqual(abortRecords(lines).filter((r) => r.event === "abort"), [],
      "**反例钉本体**（批准件 §X18(b) 的验收条件）：被拒的 abort 不得冒充已完成的 abort")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1)
    assert.equal(failures[0].status, 500, "被拒的原因是可查的，而不是被抹平成成功")
    assert.equal(failures[0].sessionId, SESSION)
  } finally { await pin.restore() }
})

test("③ abort 打到从未存在的会话（404）⇒ 记失败，且与②在**盘上**可区分（对外仍不可，那是增量 2）", async () => {
  const pin = await withDriver({ abortBehaviour: () => json(404, {}) })
  try {
    await pin.abort()
    const lines = pin.auditLines()
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort").length, 0, "打到空处也不记『已中止』")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1)
    assert.equal(failures[0].status, 404,
      "『被拒』(500) 与『没东西可停』(404) 在盘上不再同形；但调用方拿到的仍是 `undefined` ⇒ 对外区分要新出口事实，未批")
  } finally { await pin.restore() }
})

test("④ 连 HTTP 状态都拿不到（fetch reject）⇒ **Half-B 起翻转极性**：有痕 UNKNOWN、零完成形、向上仍零事件", async () => {
  // 原期望（零记录）钉的正是本批批准改写的那一行：批文验收 2 明令红-绿双向——
  // "abort 抛错无痕"在 pristine 上红、新形绿。翻转不是放宽：断言从"什么都没有"变为
  // "恰一条可归因记录且不得冒充完成"（其余五钉字节未动，见文件头 Half-B 翻转记录）。
  const pin = await withDriver({ abortBehaviour: () => { throw new TypeError("fetch failed") } })
  try {
    const returned = await pin.abort()
    assert.equal(returned, undefined, "返回契约仍不动（X18(a) 归增量 2）")
    assert.equal(pin.emitted.length, 0, "向上仍零事件（事件名零新增的另一面）")
    const lines = pin.auditLines()
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort").length, 0,
      "零完成形：未知不冒充已停（1c(b2) 的反例钉在新形状下继续成立）")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1, "X18④ 本体：断线不再是零记录（批文验收 2 的新形绿）")
    assert.equal(failures[0].abortOutcome, "UNKNOWN", "有痕的归因是 UNKNOWN（批文原词，字面量直钉不依赖导出）")
    assert.equal(pin.requests.filter(([m, t]) => m === "POST" && t.endsWith("/abort")).length, 1,
      "探针侧能确认请求真的试过（这个信息产品永远拿不到）")
  } finally { await pin.restore() }
})

// ⑤⑥ 是变异表 N4/N6 逼出来的两行：②③ 只钉了 500/404，所以"把成功判据改成 <400"或"改成 ===200"
// 都不会让任何一钉变红。判据不是本钉发明的——`rawRequest` 之上产品自己的 `expectJson`（:245）就用
// `200 <= status < 300`，本补丁只是让 abort 的审计与它早已存在的那套成败口径一致。
test("⑤ 3xx 不是『已中止』（N4 逼出来的钉）：成功判据不得放宽到 <400", async () => {
  const pin = await withDriver({ abortBehaviour: () => json(302, {}) })
  try {
    await pin.abort()
    const lines = pin.auditLines()
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort").length, 0,
      "302 被记成已中止，就是 X18(b) 要修的那类假事实的另一种写法")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1)
    assert.equal(failures[0].status, 302, "与 `expectJson` 的成败口径逐位一致")
  } finally { await pin.restore() }
})

test("⑥ 204 仍是成功（正向对照的另一侧，N6 逼出来的钉）：成功判据也不得收窄成『只有 200』", async () => {
  const pin = await withDriver({ abortBehaviour: () => new Response(null, { status: 204 }) })
  try {
    await pin.abort()
    const records = abortRecords(pin.auditLines())
    assert.equal(records.length, 1)
    assert.equal(records[0].event, "abort",
      "无正文的 2xx 是真被接受了；把它记成失败会是这个补丁自己制造的新假事实")
  } finally { await pin.restore() }
})
