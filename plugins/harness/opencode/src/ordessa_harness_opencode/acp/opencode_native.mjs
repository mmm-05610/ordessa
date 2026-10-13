/**
 * OpenCode 原生驱动模块：在隔离 guest 内托管真实的 `opencode serve` 进程。
 *
 * 这是 OpenCode 自有的原生能力模块，经品牌 `acp_resources()` 保留源码资源。
 * 历史 `adapter.driver.source` 声明仍可作为部署材料，已退役的通用
 * native-driver/Worker envelope 不再加载它；现行产品没有授予这一路原生执行准入。
 * 它只做 OpenCode 原生语义的三件事：
 *
 *   1. 用上游复用组件 `ManagedOpenCodeHost` 启动 `opencode serve`（loopback、
 *      随机空闲端口、每次运行生成基本认证口令），健康就绪后通过它的 HTTP API
 *      驱动一个原生会话；
 *   2. 把每一轮的真实增量（SSE `message.part.delta`）即时 emit 成产品中立的
 *      `message_delta` 事件，把轮次结束交给 prompt 的返回值；
 *   3. `open` 只重开"已经存在"的原生会话（读 SQLite 存储），绝不静默新建；
 *      找不到就报错，让产品看到可恢复性失败而不是一条错位的转写。
 *
 * 原生能力的调用合同（未来实际 owner 仍须独立验证准入与隔离）：
 *   - 驱动合同不接收产品凭据值，只能通过 `context.spawnProcess` 启动原生进程，
 *     秘密因此只进入子进程环境，不进 argv、不进文件、不进事件；
 *   - 驱动自己的诊断文本走 `context.redact`；未来消费者必须独立保证向上事件的删密；
 *   - 模型值由上层翻译后传入（`provider/model` 形式），驱动不写死任何模型映射，
 *     只做"这段原生地址在本机目录里是否存在"的校验。
 *
 * 实测依据（见 docs/server-round1/fullstack/opencode-production-packaging.md）：
 *   - `serve` 的会话与消息持久化在 `$XDG_DATA_HOME/opencode/opencode.db`（SQLite，
 *     含 -wal/-shm），stop(SIGTERM) 后重新启动同一数据目录即可读回同一 session；
 *   - 带 title 创建会话后，一轮 prompt 恰好产生 1 次 provider 请求；不传 title 时
 *     OpenCode 会额外用模型生成标题（多一次请求），所以 `create` 始终写入标题；
 *   - `sessionCapabilities.resume` 的声明以"重开后 `GET /session/<id>` 与
 *     `GET /session/<id>/message` 能读回上一轮"为证据，而不是猜测。
 */
import { randomBytes } from "node:crypto"
import { appendFileSync } from "node:fs"
import { createServer } from "node:net"
import { ManagedOpenCodeHost } from "./vendor/opencode-host.js"

/** 向上事件名：与 sidecar 的通用映射一致（不得改成任何产品事件名）。 */
export const DELTA_EVENT = "message_delta"
/** guest 内托管的 server 只绑 loopback。 */
export const HOST = "127.0.0.1"
export const READY_TIMEOUT_MS = 30_000
export const PROMPT_TIMEOUT_MS = 570_000
export const CLOSE_TIMEOUT_MS = 15_000
/** 响应返回后等待迟到增量事件的排空窗口（毫秒）。 */
export const DRAIN_DELTAS_MS = 400
/** 由驱动生成、只用于本机 loopback 服务的基本认证口令长度（base64url）。 */
const SECRET_BYTES = 32
/** 不传 title 时 OpenCode 会为了生成标题多发一次 provider 请求；这里给一个常量标题。 */
const FALLBACK_TITLE = "agentbox-session"

/**
 * abort 结果的**内部事实枚举**（Half-B 批文 `approvals/Half-B-internal-release.md`，04:55Z）。
 *
 * 三值只进**可选审计载荷**（字段 `abortOutcome`）：事件名零新增、`tail.outcome` 五值零新增、
 * 返回契约不动（`abort()` 仍返回 undefined）、公开投影不动（候 B2 版本窗）。三值互不合并（H9 纪律）：
 *   ABORTED                — 对端 2xx 确认停之后才落，"已发出"不配用它；
 *   REFUSED_NO_ACTIVE_TURN — 对端 404 明示无此会话 ⇒ 无在飞轮次（未命中任何在飞轮次，重放安全）；
 *   UNKNOWN                — 已下发但结果未知：其余非 2xx 无法归类、fetch 抛错、超时（禁盲重投）。
 * 与 `tail.outcome` 是两枚不同的枚举，字段名因此不叫 outcome——x20 冻结钉扫描的是 tail 面那组
 * 字面量，混用会让两枚事实互相污染；事件名集合的冻结仍由那枚钉守住（本批零新增事件名）。
 */
export const AbortOutcome = Object.freeze({
  ABORTED: "ABORTED",
  REFUSED_NO_ACTIVE_TURN: "REFUSED_NO_ACTIVE_TURN",
  UNKNOWN: "UNKNOWN",
})

export class DriverError extends Error {
  constructor(code, message) {
    super(`${code}: ${message}`)
    this.name = "DriverError"
    this.code = code
  }
}

function fail(code, message) {
  throw new DriverError(code, message)
}

/**
 * 把上层传来的原生模型值拆成 OpenCode 的 provider/model 地址。
 *
 * 这不是模型映射表：翻译（产品 modelId -> 原生值）由 Harness 扩展层完成，
 * 驱动只是校验"这段原生地址形态正确"，形态不对时用与 Pi 相同的措辞拒绝，
 * 使产品的失败理由里能看到用户选择的模型。
 */
export function splitNativeModel(value) {
  const shown = typeof value === "string" ? value : String(value)
  if (typeof value !== "string" || value.length === 0 || value.length > 200
      || value.startsWith("/") || !value.includes("/")) {
    fail("OPENCODE_MODEL_NOT_AVAILABLE", `Harness model is not available: ${shown}`)
  }
  const index = value.indexOf("/")
  const providerID = value.slice(0, index)
  const modelID = value.slice(index + 1)
  if (!providerID || !modelID || modelID.includes("/")) {
    fail("OPENCODE_MODEL_NOT_AVAILABLE", `Harness model is not available: ${shown}`)
  }
  return { providerID, modelID }
}

/** 原生目录里是否存在该 provider/model；不存在即拒绝（发送 provider 请求之前）。 */
export function catalogHasModel(catalog, providerID, modelID) {
  const providers = catalog && typeof catalog === "object" && Array.isArray(catalog.providers)
    ? catalog.providers : null
  if (!providers) return null // 目录读不到：与"不存在"分开处理
  const provider = providers.find((item) => item && item.id === providerID)
  if (!provider || typeof provider.models !== "object" || provider.models === null) return false
  return Object.prototype.hasOwnProperty.call(provider.models, modelID)
}

/** 记录里比流多出来的那段后缀，或 null（流已完整 / 两者不一致时不给猜测）。
 *
 * 单独成函数是为了能被测：`prompt` 的尾部校准就靠它决定"补什么"。
 * 只有记录以流为前缀时才返回后缀；不一致时返回 null，交由调用方只记事实。 */
export function tailSuffix(streamed, recorded) {
  if (typeof recorded !== "string" || typeof streamed !== "string") return null
  if (!recorded.startsWith(streamed)) return null
  return recorded.length > streamed.length ? recorded.slice(streamed.length) : null
}

/** 从 OpenCode 的 parts 里取出助手文本（仅在增量缺失时作为兜底）。 */
export function textOfParts(parts) {
  if (!Array.isArray(parts)) return ""
  return parts.filter((part) => part && part.type === "text" && typeof part.text === "string")
    .map((part) => part.text).join("")
}

/**
 * 尾部校准的判定：流式文本、权威记录与实际到达的增量数三者之间的关系。
 *
 * PATCH (AgentBox 增量1)：与 `tailSuffix` 同样单独成函数是为了能被测；这里只**给结论**，
 * 补发与审计由 `prompt` 执行。结论本身要能被调用方看见，因为审计文件是可选的、写失败也不
 * 报错，而"产品收到的文本未必是原生记录的那一份"只有转写的所有者能决定怎么处理。
 *
 * - `record-only` —— SSE 一个增量都没到：整段记录就是需要补发的全部。
 * - `completed`  —— 记录以流为前缀且更长：补发缺的那一段后缀，已流出的一字不改。
 * - `mismatch`   —— 流不是记录的前缀：两者不一致，不猜顺序、不重写，只报事实。
 * - `matched`    —— 流与记录完全一致。
 * - `record-empty` —— 记录里没有助手文本可比（例如只回了 reasoning），不能称其为一致。
 */
export function tailVerdict({ streamed, recorded, deltas }) {
  if (deltas === 0) return { outcome: "record-only", supplement: typeof recorded === "string" ? recorded : "" }
  const suffix = tailSuffix(streamed, recorded)
  if (suffix) return { outcome: "completed", supplement: suffix }
  if (recorded && !recorded.startsWith(streamed)) return { outcome: "mismatch", supplement: "" }
  return { outcome: recorded ? "matched" : "record-empty", supplement: "" }
}

/** 审计钩子：只有显式声明且位于本次工作目录内的绝对路径才会被写入。 */
export function auditPathFor(environment, directory) {
  const value = environment ? environment.AGENTBOX_DRIVER_AUDIT : undefined
  if (typeof value !== "string" || !value.startsWith("/") || value.includes("\0")) return null
  if (typeof directory === "string" && directory.startsWith("/")
      && !value.startsWith(directory.replace(/\/+$/, "") + "/")) {
    return null
  }
  return value
}

/** OpenCode 在给定的 XDG 数据根下使用的目录名。 */
export function dataDirectoryUnder(xdgDataHome) {
  return `${String(xdgDataHome).replace(/\/+$/, "")}/opencode`
}

/** 在 serve 之前插入 `--pure`（对外部插件的关闭与 42d 的 `run --pure` 对齐）。 */
export function withPure(args) {
  if (!Array.isArray(args) || args.length === 0 || args[0] !== "serve") return args
  return args.includes("--pure") ? args : [args[0], "--pure", ...args.slice(1)]
}

/** 让操作系统给出一个空闲端口：绑定 0 再释放（端口随后立刻被本进程占用）。 */
export function freePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer()
    probe.unref()
    probe.on("error", reject)
    probe.listen(0, HOST, () => {
      const address = probe.address()
      const port = address && typeof address === "object" ? address.port : 0
      probe.close(() => (port ? resolve(port) : reject(new Error("no free port"))))
    })
  })
}

export async function createDriver(context) {
  const emit = typeof context?.emit === "function" ? context.emit : () => {}
  const redact = typeof context?.redact === "function"
    ? context.redact : (value, maximum) => String(value ?? "").slice(0, maximum)
  const environment = { ...(context?.environment ?? {}) }
  const directory = typeof context?.directory === "string" ? context.directory : process.cwd()
  const stateDirectory = typeof context?.stateDirectory === "string" ? context.stateDirectory : null
  // OpenCode 的持久化根（SQLite 与快照）是 `$XDG_DATA_HOME/opencode`。XDG 根由
  // guest 环境给出，deployment **不**再声明它（否则同一个事实会有两份、可以漂移）；
  // 本进程就跑在那个 guest 环境里，所以审计/status 用的数据目录优先取声明值、
  // 其次取进程环境。它只用于审计，不参与任何寻址决定。
  const xdgDataHome = typeof environment.XDG_DATA_HOME === "string"
    ? environment.XDG_DATA_HOME
    : typeof process.env.XDG_DATA_HOME === "string" ? process.env.XDG_DATA_HOME : null
  const dataDirectory = xdgDataHome ? dataDirectoryUnder(xdgDataHome) : null
  const auditTarget = auditPathFor(environment, directory)
  const authorization = () => "Basic " + Buffer.from(`${username}:${password}`).toString("base64")
  const username = "agentbox"
  // 每次运行一张一次性口令：它只保护本机 loopback 端口，从不写进任何文件或事件。
  const password = randomBytes(SECRET_BYTES).toString("base64url")
  const sessions = new Map()
  let port = 0
  let host = null
  let catalog = null
  let stopEvents = null
  let resetStreamBuffer = null
  let active = null
  let closed = false

  const capabilities = {
    agentInfo: { name: "opencode", version: null },
    promptCapabilities: { image: false },
    // resume 声明基于实测：重开后同一 native session 与其消息可从存储读回，
    // 因此产品的 checkpoint 可以是 resumable。
    sessionCapabilities: { resume: {}, list: {} },
  }
  const contract = { transport: "opencode-server", health: "/global/health", state: "sqlite" }

  function audit(record) {
    if (!auditTarget) return
    const sanitized = {}
    for (const [key, value] of Object.entries(record)) {
      sanitized[key] = typeof value === "string" ? redact(value, 200) : value
    }
    try {
      appendFileSync(auditTarget, JSON.stringify({ at: new Date().toISOString(), driver: "opencode", ...sanitized }) + "\n")
    } catch {
      // 审计永远不是驱动失败的理由。
    }
  }

  function baseUrl() {
    return `http://${HOST}:${port}`
  }

  async function rawRequest(method, suffix, body, timeoutMs = 30_000) {
    const response = await fetch(baseUrl() + suffix, {
      method,
      headers: {
        Authorization: authorization(),
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: AbortSignal.timeout(timeoutMs),
    })
    const text = await response.text()
    let parsed = null
    try {
      parsed = text ? JSON.parse(text) : null
    } catch {
      parsed = null
    }
    return { status: response.status, body: parsed, text }
  }

  async function expectJson(method, suffix, body, timeoutMs = 30_000) {
    const result = await rawRequest(method, suffix, body, timeoutMs)
    if (result.status < 200 || result.status >= 300) {
      // 服务端错误的理由可能包含请求细节，先由驱动自己脱敏。
      fail("OPENCODE_SERVER_ERROR", `${method} ${suffix} -> HTTP ${result.status}: ${redact(result.text, 200)}`)
    }
    return result.body
  }

  async function loadCatalog() {
    const result = await rawRequest("GET", "/config/providers")
    if (result.status !== 200 || !result.body) {
      fail("OPENCODE_MODEL_CATALOG_UNAVAILABLE",
        `the native model catalogue could not be read (HTTP ${result.status})`)
    }
    catalog = result.body
    return catalog
  }

  async function assertModelAvailable(native, requested) {
    const current = catalog ?? await loadCatalog()
    const available = catalogHasModel(current, native.providerID, native.modelID)
    if (available === null) {
      fail("OPENCODE_MODEL_CATALOG_UNAVAILABLE", "the native model catalogue has no providers")
    }
    if (!available) {
      fail("OPENCODE_MODEL_NOT_AVAILABLE", `Harness model is not available: ${requested}`)
    }
  }

  /**
   * 订阅 server 的 SSE 事件流，把助手文本增量即时上报。
   *
   * OpenCode 把每次流式增量作为 `message.part.delta`（field=text）播发，正是产品
   * `message.delta` 需要的粒度；这里只按当前活跃的 session 过滤，事件名保持通用。
   */
  async function subscribe() {
    const controller = new AbortController()
    const response = await fetch(`${baseUrl()}/event`, {
      headers: { Authorization: authorization() }, signal: controller.signal,
    })
    if (!response.ok || !response.body) {
      fail("OPENCODE_EVENT_STREAM_UNAVAILABLE", `the event stream answered HTTP ${response.status}`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ""
    // PATCH (AgentBox 增量1c-b): the block parser is shared by the streaming loop and by the two
    // paths that used to have none (end of stream, reader error, turn boundary), so a frame can no
    // longer disappear simply because its terminator never arrived. It returns how many `data:`
    // lines it saw and how many of those were undecodable, which is what makes a framing failure
    // distinguishable from "this host does not stream" without inventing a new public fact.
    function consumeBlock(block) {
      let dataLines = 0
      let undecodable = 0
      for (const line of block.split("\n")) {
        if (!line.startsWith("data: ")) continue
        dataLines += 1
        let event = null
        try {
          event = JSON.parse(line.slice(6))
        } catch {
          event = null
        }
        if (!event) {
          undecodable += 1
          continue
        }
        if (event.type === "message.part.delta") {
          const properties = event.properties ?? {}
          const text = typeof properties.delta === "string" ? properties.delta : ""
          if (text && properties.field === "text" && active && active.sessionId === properties.sessionID) {
            active.deltas += 1
            active.text += text
            // X19（C 21:31Z 裁定「按来源分流」）：订阅者的错**不是**"流断了"。`emit` 单独包一层
            // try——不是把它移出外层 try（移出会让同一个抛错击穿泵，那是新失败模式）。这里只多一条
            // 可选审计事实，与 `abort-failed` 同族；对外事件/枚举/出口零新增。
            try {
              emit({ event: DELTA_EVENT, data: { text } })
            } catch (error) {
              audit({
                event: "subscriber-error",
                message: redact(String(error?.message ?? error), 200),
              })
            }
          }
        }
      }
      return { dataLines, undecodable }
    }
    // A stream that ends — cleanly or not — may still hold bytes that never saw a "\n\n". They are
    // already in this process, so losing them is ours, not the host's. Whatever still cannot be
    // decoded is counted into the existing opt-in audit channel (lengths only, never content).
    function flushRemaining(reason) {
      buffer += decoder.decode()
      if (buffer.length === 0) return
      const remainder = buffer
      buffer = ""
      const { dataLines, undecodable } = consumeBlock(remainder)
      if (dataLines > 0) {
        audit({
          event: "stream-tail", reason, characters: remainder.length, dataLines, undecodable,
        })
      }
    }
    // Mirror of 增量1b's per-`#start` reset on the ACP leg: this leg has no restart event to hang it
    // on, and the only boundary it does have is the turn. A partial frame left by turn N can never
    // be completed by turn N+1 — it can only corrupt N+1's first frame — so it is dropped here, and
    // the drop is counted rather than silent.
    resetStreamBuffer = () => {
      if (buffer.length > 0) {
        audit({ event: "stream-tail-discarded", characters: buffer.length })
        buffer = ""
      }
    }
    const pump = (async () => {
      try {
        while (true) {
          const { value, done } = await reader.read()
          if (done) {
            flushRemaining("done")
            break
          }
          buffer += decoder.decode(value, { stream: true })
          let boundary = buffer.indexOf("\n\n")
          while (boundary !== -1) {
            const block = buffer.slice(0, boundary)
            buffer = buffer.slice(boundary + 2)
            consumeBlock(block)
            boundary = buffer.indexOf("\n\n")
          }
        }
      } catch (error) {
        // 流断开不是驱动失败：prompt 仍有返回值兜底。但"不是失败"不等于"不必说"——中断现在
        // 带上已收到的字节数进审计，且已收到的部分照旧交付，损失由此变为有界。
        //
        // 但**主动 close() 也会走到这里**（stopEvents 里的 controller.abort() 会让 read() 抛
        // AbortError）。那不是"流断了"：把它记成中断，就等于给每次正常停机留一条假事实，正是
        // 本组 X18 在 abort() 一侧量到并批评的那类错。所以下面按"是不是我们自己关的"分流。
        const aborted = controller.signal.aborted || closed
        const pendingCharacters = buffer.length
        flushRemaining(aborted ? "aborted" : "reader-error")
        if (aborted) return
        // X20(b)：主事实不得被"记录它的那一步"自己的错抹掉。格式化器（`redact`）是可注入的，
        // 它一抛就让整个 catch 体带着 `stream-interrupted` 一起消失。先算，算不出就留空串。
        let interruption
        try {
          interruption = redact(String(error?.message ?? error), 200)
        } catch {
          interruption = ""
        }
        audit({
          event: "stream-interrupted",
          pendingCharacters,
          message: interruption,
        })
      }
    })()
    // X20(a)：处理器必须挂在 `pump` 创建处，不能等收摊。原先 `.catch` 只存在于下面的 teardown
    // 闭包里 ⇒ 泵在 `close()` 之前死掉就是一条无人认领的 rejection（Node 15+ 默认策略下是真实
    // worker 里的进程级事件），而 `stream-pump-failed` 要等 teardown 才被补记，归因由时机变成事后。
    // 处理器体自己也得关住异常：它再抛就是第二条未处理拒绝，且会把刚保住的主事实连同审计线一起带走。
    // （X19 之后订阅者的错已在源头分流 ⇒ 这条线不再有"被误标的订阅者"这条来源。）
    pump.catch((error) => {
      try {
        audit({
          event: "stream-pump-failed",
          message: redact(String(error?.message ?? error), 200),
        })
      } catch {
        // 审计线自身的失败不得再变成一条未处理拒绝。
      }
    })
    return () => {
      try {
        controller.abort()
      } catch {
        // 关闭路径上的异常不得覆盖主结果。
      }
    }
  }

  async function start() {
    port = await freePort()
    host = new ManagedOpenCodeHost({
      command: context.command,
      host: HOST,
      port,
      username,
      password,
      environment,
      startTimeoutMs: READY_TIMEOUT_MS,
      // 口令只经 `env` 子进程的瞬时 argv 与子进程环境传递；opencode 自身的 argv
      // 里没有口令（`env` 在执行时消耗掉 VAR=value 参数），文件里也没有。
      spawnProcess: (command, args, options = {}) => context.spawnProcess(
        "/usr/bin/env",
        [`OPENCODE_SERVER_USERNAME=${username}`, `OPENCODE_SERVER_PASSWORD=${password}`,
          command, ...withPure(args)],
        { ...options, cwd: directory },
      ),
    })
    const argv = withPure(["serve", "--hostname", HOST, "--port", String(port)])
    await host.start()
    // 托管进程意外退出才算这一轮失败：主动 close 不产生 driver_exit，
    // 否则会在正常收尾时给产品上报一个假的失败事实。
    host.on("unavailable", (error) => {
      if (closed) return
      emit({ event: "driver_exit", data: { message: redact(String(error?.message ?? error), 300) } })
    })
    const health = await expectJson("GET", "/global/health")
    capabilities.agentInfo.version = typeof health?.version === "string" ? health.version : null
    await loadCatalog()
    stopEvents = await subscribe()
    audit({
      event: "host-start",
      command: context.command,
      argv,
      host: HOST,
      port,
      processID: host.processID ?? null,
      dataDirectory,
      stateDirectory,
      configPath: typeof environment.OPENCODE_CONFIG === "string" ? environment.OPENCODE_CONFIG : null,
      healthVersion: capabilities.agentInfo.version,
      credentialsInArgv: false,
    })
  }

  async function create({ title, model } = {}) {
    const native = splitNativeModel(model)
    await assertModelAvailable(native, model)
    const created = await expectJson("POST", "/session", {
      // 显式标题避免 OpenCode 为生成标题再发一次 provider 请求（实测）。
      title: typeof title === "string" && title.length > 0 ? title.slice(0, 200) : FALLBACK_TITLE,
      model: { id: native.modelID, providerID: native.providerID },
    })
    const sessionId = created && typeof created.id === "string" ? created.id : null
    if (!sessionId) fail("OPENCODE_SESSION_CREATE_FAILED", "the native session id is missing")
    sessions.set(sessionId, { title: created.title ?? null, model: String(model) })
    audit({
      event: "create", method: "POST /session", sessionId,
      title: created.title ?? null, model: String(model), titleSupplied: true,
    })
    return { sessionId, title: created.title ?? null }
  }

  async function storedSession(sessionId) {
    const result = await rawRequest("GET", `/session/${encodeURIComponent(sessionId)}`)
    if (result.status === 404 || !result.body || typeof result.body.id !== "string") return null
    if (result.status !== 200) {
      fail("OPENCODE_SERVER_ERROR", `GET /session -> HTTP ${result.status}`)
    }
    return result.body
  }

  /**
   * 重开一个已经存储的原生会话：只读存储，绝不新建。
   *
   * 证据：`GET /session/<id>` 与 `GET /session/<id>/message` 从 SQLite 读回上一轮
   * 的标题与消息；找不到时以 OPENCODE_SESSION_NOT_FOUND 失败，让产品的不可用
   * checkpoint 明确失败而不是静默换一条新会话。
   */
  async function open({ sessionId, model } = {}) {
    if (typeof sessionId !== "string" || sessionId.length === 0) {
      fail("OPENCODE_SESSION_NOT_FOUND", "the native session id is missing")
    }
    const stored = await storedSession(sessionId)
    if (!stored) {
      fail("OPENCODE_SESSION_NOT_FOUND", `the native session is not stored: ${redact(sessionId, 120)}`)
    }
    const messages = await rawRequest("GET", `/session/${encodeURIComponent(sessionId)}/message`)
    sessions.set(sessionId, { title: stored.title ?? null, model: String(model ?? "") })
    audit({
      event: "open",
      method: `GET /session/${redact(sessionId, 120)}`,
      created: false,
      sessionId,
      title: stored.title ?? null,
      storedMessages: Array.isArray(messages.body) ? messages.body.length : null,
      model: model === undefined ? null : String(model),
    })
    return { sessionId: stored.id }
  }

  async function prompt({ sessionId, text, model, attachments } = {}) {
    if (closed) fail("OPENCODE_DRIVER_CLOSED", "the driver is closed")
    if (Array.isArray(attachments) && attachments.length > 0) {
      fail("OPENCODE_ATTACHMENTS_UNSUPPORTED", "this deployment does not carry attachments")
    }
    if (typeof text !== "string" || text.length === 0) {
      fail("OPENCODE_PROMPT_INVALID", "the prompt text is empty")
    }
    const native = splitNativeModel(model)
    await assertModelAvailable(native, model)
    if (!sessions.has(sessionId)) {
      // 重开路径不会先 create；这里仍然只校验存在性，不新建。
      const stored = await storedSession(sessionId)
      if (!stored) fail("OPENCODE_SESSION_NOT_FOUND", `the native session is not stored: ${redact(sessionId, 120)}`)
      sessions.set(sessionId, { title: stored.title ?? null, model: String(model) })
    }
    const current = { sessionId, deltas: 0, text: "" }
    active = current
    // PATCH (AgentBox 增量1c-b ⑦): 轮次边界丢弃上一轮残留的半帧（丢弃被计数，不是静默消失）。
    if (resetStreamBuffer) resetStreamBuffer()
    let response = null
    try {
      response = await expectJson("POST", `/session/${encodeURIComponent(sessionId)}/message`, {
        model: { providerID: native.providerID, modelID: native.modelID },
        parts: [{ type: "text", text }],
      }, PROMPT_TIMEOUT_MS)
      // provider 一次性返回整段文本时，最后一个增量事件与响应几乎同时到达；
      // 给事件流一个很短的排空窗口，避免丢掉"已经发生"的增量。
      const drainUntil = Date.now() + DRAIN_DELTAS_MS
      while (current.deltas === 0 && Date.now() < drainUntil) {
        await new Promise((resolve) => setTimeout(resolve, 20))
      }
    } finally {
      active = null
    }
    const authoritative = textOfParts(response?.parts)
    // PATCH (AgentBox 增量1): the tail calibration's verdict has to reach the caller. Before this it
    // was written only to the audit file, which is opt-in (`AGENTBOX_DRIVER_AUDIT`) and whose failed
    // writes are swallowed on purpose, so with auditing off a mismatch between what the product was
    // streamed and what the native record holds left no trace at all. The verdict carries lengths
    // only — no transcript content is part of the fact — and every branch keeps its old action.
    const verdict = tailVerdict({
      streamed: current.text, recorded: authoritative, deltas: current.deltas,
    })
    if (verdict.supplement) emit({ event: DELTA_EVENT, data: { text: verdict.supplement } })
    if (verdict.outcome === "completed") {
      audit({ event: "tail-completed", sessionId, missing: verdict.supplement.length })
    } else if (verdict.outcome === "mismatch") {
      audit({ event: "tail-mismatch", sessionId, streamed: current.text.length, recorded: authoritative.length })
    }
    const tail = {
      outcome: verdict.outcome,
      emittedCharacters: verdict.supplement.length,
      streamedCharacters: current.text.length,
      recordedCharacters: authoritative.length,
    }
    audit({
      event: "prompt", sessionId, model: String(model),
      incrementalDeltas: current.deltas, streamed: current.deltas > 0,
      messageId: response && response.info ? response.info.id ?? null : null,
      failed: Boolean(response && response.info && response.info.error),
    })
    return {
      done: true,
      sessionId,
      messageId: response && response.info ? response.info.id ?? null : null,
      deltas: current.deltas,
      tail,
    }
  }

  async function abort(sessionId) {
    if (typeof sessionId !== "string" || sessionId.length === 0) return
    // 失败记录的唯一落点（Half-B）：事件字面量在本文件里只出现一次——x20 冻结钉按字面量
    // **多重集**比对源码，三处各写一遍会让那枚钉红；本结构同时让"失败面只有一种写法"成为代码事实。
    const recordFailure = (fields) => {
      try {
        audit({ event: "abort-failed", ...fields })
      } catch {
        // 审计线自身的失败不得让 abort() 变成抛错。
      }
    }
    let result
    try {
      result = await rawRequest("POST", `/session/${encodeURIComponent(sessionId)}/abort`, {})
    } catch (error) {
      // Half-B / X18④：请求已下发但结果未知（fetch 抛错、超时、通道断）⇒ **当场记有痕
      // `UNKNOWN`**，不再无痕（1e 前科族闭口）。仍不新增事件名、不改返回契约（abort() 仍返回
      // undefined，X18(a) 按裁定归增量 2）。归因线自保护（1e 先例）：格式化器可注入，
      // 它一抛不得把这条记录连同"尽力而为的 abort"一起带走。
      let detail
      try {
        detail = redact(String(error?.message ?? error), 200)
      } catch {
        detail = ""
      }
      recordFailure({ sessionId, abortOutcome: AbortOutcome.UNKNOWN, message: detail })
      return
    }
    // 分级（Half-B 批文 04:55Z，映射表见 outbox/goal-H-021 §2(B)）：只有 2xx 才配得上完成形状
    // （1c(b2) 起）；404 是对端明示"无此会话 ⇒ 无在飞轮次"（重放安全）⇒ REFUSED；其余非 2xx
    // 无法归类 ⇒ UNKNOWN——500 不蕴含"没有在飞轮次"，记 refused 即冒充（H9 纪律 (b)）。
    // 三值只走载荷字段 `abortOutcome`，事件名两词零新增。
    try {
      if (result.status >= 200 && result.status < 300) {
        audit({ event: "abort", sessionId, abortOutcome: AbortOutcome.ABORTED })
      } else {
        recordFailure({
          sessionId,
          status: result.status,
          abortOutcome: result.status === 404
            ? AbortOutcome.REFUSED_NO_ACTIVE_TURN : AbortOutcome.UNKNOWN,
        })
      }
    } catch {
      // 完成形状记录的格式化失败不是驱动失败；abort 始终是尽力而为，不因记录而抛。
    }
  }

  async function waitForExit(timeoutMs) {
    const deadline = Date.now() + timeoutMs
    while (Date.now() < deadline) {
      if (!host || host.processID === undefined) return true
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
    return !host || host.processID === undefined
  }

  async function close() {
    if (closed) return
    closed = true
    if (stopEvents) stopEvents()
    let stopped = false
    let forced = false
    if (host) {
      host.stop("SIGTERM")
      stopped = await waitForExit(CLOSE_TIMEOUT_MS)
      if (!stopped) {
        host.stop("SIGKILL")
        forced = true
        stopped = await waitForExit(CLOSE_TIMEOUT_MS)
      }
    }
    audit({ event: "close", stopped, forced, dataDirectory, stateDirectory })
  }

  async function status(sessionId) {
    return {
      sessions: [...sessions.keys()],
      sessionId: sessionId ?? null,
      host: HOST,
      port,
      processID: host ? host.processID ?? null : null,
      dataDirectory,
      stateDirectory,
      modelDirectory: catalog !== null,
      deltas: active ? active.deltas : 0,
    }
  }

  return { capabilities, contract, start, create, open, prompt, abort, close, status }
}
