/**
 * Half-B 前向钉（= 批准件 `approvals/Half-B-internal-release.md` 04:55Z 的验收 3「三值归因钉」）：
 * abort 结果的**内部三值归因**各自可观测、互不冒充；X18④（fetch 抛错）从无痕变有痕 `UNKNOWN`。
 *
 * 三值映射（批文形状句与验收 3 的唯一可同立读法，先报于 `outbox/goal-H-021` §2(B)）：
 *   2xx → ABORTED（仅确认停后落）；404 → REFUSED_NO_ACTIVE_TURN（对端明拒，重放安全）；
 *   其余非 2xx → UNKNOWN（无法归类不冒充 refused）；fetch 抛错／超时 → UNKNOWN（X18④ 本体）。
 *
 * 与 `opencode_control_leg_audit.test.mjs`（1c(b2) 六钉）分工：那份钉 500/404/302 的 status 面，
 * 本文件钉 **`AbortOutcome` 归因面**；两份共用同一套 fake 接缝，语句互不重叠。
 * 红-绿（批文验收 2，整树前缀反证法）：本文件除 ⑥ 外在 pristine 驱动（`16ef381`）上必须为红
 * ——枚举缺席、载荷字段缺席、无痕——那正是"钉有牙"；⑥ 是接缝面反向守卫，两树同绿。
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

const { createDriver, AbortOutcome } = await import(DRIVER)

const json = (status, doc) => new Response(JSON.stringify(doc ?? {}), {
  status, headers: { "content-type": "application/json" },
})

function fakeChild() {
  const child = new EventEmitter()
  child.pid = 4545
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

/** `abortBehaviour` 决定宿主怎么回答控制请求（或直接断线）；`auditLines()` 读盘上那份记录。 */
async function withDriver({ abortBehaviour = () => json(200, {}) } = {}) {
  const original = globalThis.fetch
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "agentbox-halfb-"))
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
// 红-绿可读性：pristine 前缀树上枚举不存在，每枚归因钉先亮这一句再红，而不是抛 TypeError。
const requireEnum = () => assert.ok(
  AbortOutcome && typeof AbortOutcome === "object",
  "Half-B 未落（pristine 前缀树上的预期红）：AbortOutcome 枚举缺席",
)

test("① 2xx ⇒ 恰一条完成形状记录且归因 ABORTED；零 abort-failed（ABORTED 仅确认停后落）", async () => {
  requireEnum()
  const pin = await withDriver({ abortBehaviour: () => json(200, {}) })
  try {
    await pin.abort()
    const lines = pin.auditLines()
    const records = abortRecords(lines)
    assert.equal(records.length, 1, "一次 abort 一份记录，不多也不少")
    assert.equal(records[0].event, "abort", "被接受的 abort 仍是完成形状（1c(b2) 正向对照不许被改掉）")
    assert.equal(records[0].abortOutcome, AbortOutcome.ABORTED, "完成形状的归因是 ABORTED，且与导出枚举同一字面量")
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort-failed").length, 0,
      "确认停之后不许再留一条失败记录")
  } finally { await pin.restore() }
})

test("② 404 对端明拒 ⇒ REFUSED_NO_ACTIVE_TURN（与 UNKNOWN 不同线），零完成形", async () => {
  requireEnum()
  const pin = await withDriver({ abortBehaviour: () => json(404, {}) })
  try {
    await pin.abort()
    const lines = pin.auditLines()
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort").length, 0,
      "明拒不冒充已停（1c(b2) 反例钉在新形状下继续成立）")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1)
    assert.equal(failures[0].status, 404, "状态码仍在同一条内部通道（1c(b2) 面不动）")
    assert.equal(failures[0].abortOutcome, AbortOutcome.REFUSED_NO_ACTIVE_TURN,
      "对端明示\"无此会话 ⇒ 无在飞轮次\" ⇒ REFUSED；重放安全")
    assert.notEqual(failures[0].abortOutcome, AbortOutcome.UNKNOWN,
      "验收 3：REFUSED 与 UNKNOWN 是两条线，不许合并")
    assert.equal(abortRecords(lines).filter((r) => r.abortOutcome === AbortOutcome.ABORTED).length, 0,
      "没停就是没停：ABORTED 只在 2xx 后落")
  } finally { await pin.restore() }
})

test("③ X18④ 本体：fetch 抛错 ⇒ 有痕 UNKNOWN（恰一条 abort-failed）、零完成形、向上零事件、返回 undefined", async () => {
  requireEnum()
  const pin = await withDriver({ abortBehaviour: () => { throw new TypeError("fetch failed") } })
  try {
    const returned = await pin.abort()
    assert.equal(returned, undefined, "返回契约不动：X18(a) 按裁定归增量 2")
    assert.equal(pin.emitted.length, 0, "向上仍零事件（事件名零新增的另一面）")
    const lines = pin.auditLines()
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort").length, 0,
      "结果未知不冒充已停")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1, "批文本体：断线不再是零记录（此前无痕＝1e 前科族）")
    assert.equal(failures[0].abortOutcome, AbortOutcome.UNKNOWN, "断／超时的归因是 UNKNOWN")
    assert.equal(typeof failures[0].message, "string",
      "证据分级走载荷字段：脱敏后的失败线索在同一条记录里（长度受限，无凭据面）")
    assert.equal(failures[0].sessionId, SESSION)
    assert.equal(pin.requests.filter(([m, t]) => m === "POST" && t.endsWith("/abort")).length, 1,
      "请求确实试过一次（这个信息产品永远拿不到，只在探针侧可证）")
  } finally { await pin.restore() }
})

test("④ 500 无法归类 ⇒ UNKNOWN（不冒充 refused），与②的 404 在归因字段上分线", async () => {
  requireEnum()
  const pin = await withDriver({ abortBehaviour: () => json(500, { error: "busy" }) })
  try {
    await pin.abort()
    const lines = pin.auditLines()
    assert.equal(abortRecords(lines).filter((r) => r.event === "abort").length, 0,
      "500 更不冒充完成")
    const failures = abortRecords(lines).filter((r) => r.event === "abort-failed")
    assert.equal(failures.length, 1)
    assert.equal(failures[0].status, 500)
    assert.equal(failures[0].abortOutcome, AbortOutcome.UNKNOWN,
      "500 不蕴含\"无在飞轮次\"⇒ 无法归类＝UNKNOWN（H9 纪律：不把 unknown 压成 refused，反之亦然）")
    assert.notEqual(failures[0].abortOutcome, AbortOutcome.REFUSED_NO_ACTIVE_TURN,
      "验收 3：500 不是\"明拒无在飞轮次\"，把它记成 REFUSED 就是冒充")
  } finally { await pin.restore() }
})

test("⑤ AbortOutcome 枚举恰三值、值即键、已冻结（扩值绕道在此变红）", () => {
  requireEnum()
  assert.deepEqual(Object.keys(AbortOutcome).sort(),
    ["ABORTED", "REFUSED_NO_ACTIVE_TURN", "UNKNOWN"],
    "批文形状句锁死三值；增删任何一值都需要新批文")
  for (const [key, value] of Object.entries(AbortOutcome)) {
    assert.equal(value, key, "值即键：不存在第二种拼写（命名轮 refused_<单数> 骨架不在此轮铸值）")
  }
  assert.ok(Object.isFrozen(AbortOutcome), "内部事实枚举不可被运行期改写")
})

test("⑥ M-1 抽查：driver 接缝面键集合与修前逐字相同（导出枚举不进接缝）", async () => {
  // 两树同绿的反向守卫：本批只加了模块级导出，`createDriver` 返回的接缝对象不得多出任何方法。
  const pin = await withDriver()
  try {
    assert.deepEqual(Object.keys(pin.driver).sort(),
      ["abort", "capabilities", "close", "contract", "create", "open", "prompt", "start", "status"],
      "接缝面（native-driver.mjs 消费的那组键）零变化")
  } finally { await pin.restore() }
})
