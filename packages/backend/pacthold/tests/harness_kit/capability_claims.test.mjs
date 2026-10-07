/**
 * `canonicalCapabilityClaims` 的合同（JS 侧）。
 *
 * 被测的性质只有一条，但它是硬要求：**原生声明只能收窄静态上限，不能抬高产品能力**。
 * 静态上限来自受校验投影 `runtime/capability_declarations.json`，而那份投影由 Python 侧
 * 测试逐项断言等于 `harnesses.toml`。所以本文件的 ⊆ 断言实际上把 JS 运行时也钉在了
 * TOML 上——运行时不会因为某个 adapter 多播发了一个能力，就凭空多出一个产品能力。
 */
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..")
const runtime = path.join(pluginRoot, "runtime")
const {
  AGENTBOX_HARNESS_PROFILES,
  NATIVE_CAPABILITY_TO_CANONICAL,
  UNMAPPED_NATIVE_CAPABILITIES,
  canonicalCapabilityClaims,
  capabilityDeclarations,
  declaredCapabilityCeiling,
  registeredHarnessIDs,
} = await import(`file://${path.join(runtime, "profile_extensions.mjs")}`)

const projection = JSON.parse(
  readFileSync(path.join(runtime, "capability_declarations.json"), "utf8"),
)

/** 投影里出现过的全部 canonical id：本测试用它当"词汇表"，不另立一份。 */
const CANONICAL_IDS = new Set(Object.values(projection.harnessTypes).flat())

/** 每一家原生能力表里出现过的键（用于构造"全部播发"的极端原生声明）。 */
const NATIVE_KEYS = [
  "sessions", "prompt", "abort", "streaming", "agents", "diff", "filesystemBrowser",
  "questions", "permissions", "sessionRename", "sessionDelete", "models", "todos",
  "commands", "actions", "native_continuation", "attach", "steer",
]

test("the projection is the schema-versioned map the Python side checks", () => {
  assert.equal(projection.schemaVersion, 1)
  assert.equal(typeof projection.harnessTypes, "object")
  for (const [harnessType, ids] of Object.entries(projection.harnessTypes)) {
    assert.ok(Array.isArray(ids), harnessType)
    assert.deepEqual(ids, [...ids].sort(), harnessType)
  }
})

test("the mapping table only ever points at canonical ids", () => {
  for (const [native, targets] of Object.entries(NATIVE_CAPABILITY_TO_CANONICAL)) {
    assert.ok(!CANONICAL_IDS.has(native) || native === "permissions",
      `a native spelling must not itself be a canonical id: ${native}`)
    assert.ok(targets.length > 0, native)
    for (const target of targets) assert.ok(CANONICAL_IDS.has(target), `${native} -> ${target}`)
  }
  // 反向：任何 canonical id 都不许被当作"原生键"偷偷映射（permissions 是唯一同名同级的一对）。
  const mappedNativeKeys = new Set(Object.keys(NATIVE_CAPABILITY_TO_CANONICAL))
  for (const id of CANONICAL_IDS) {
    if (id === "permissions") {
      assert.ok(mappedNativeKeys.has("permissions"))
      continue
    }
    assert.ok(!mappedNativeKeys.has(id), `canonical id used as a native key: ${id}`)
  }
})

test("abort is not steer and filesystemBrowser is not attach", () => {
  assert.equal(NATIVE_CAPABILITY_TO_CANONICAL.abort, undefined)
  assert.equal(NATIVE_CAPABILITY_TO_CANONICAL.filesystemBrowser, undefined)
  assert.equal(NATIVE_CAPABILITY_TO_CANONICAL.sessions, undefined)
  assert.equal(NATIVE_CAPABILITY_TO_CANONICAL.attach, undefined)
  assert.equal(NATIVE_CAPABILITY_TO_CANONICAL.native_continuation, undefined)
  // 每个"故意不映射"的键都要有理由，理由不能是空话。
  for (const key of Object.keys(UNMAPPED_NATIVE_CAPABILITIES)) {
    assert.equal(typeof UNMAPPED_NATIVE_CAPABILITIES[key], "string")
    assert.ok(UNMAPPED_NATIVE_CAPABILITIES[key].length > 8, key)
  }
})

test("every registered profile's mapping stays inside its declared ceiling", () => {
  for (const profileID of registeredHarnessIDs()) {
    if (!(profileID in projection.harnessTypes)) continue
    const claims = canonicalCapabilityClaims(profileID)
    const declared = new Set(projection.harnessTypes[profileID])
    for (const id of claims) assert.ok(declared.has(id), `${profileID}: ${id}`)
  }
})

test("no native promotion can push a claim past the static declaration", () => {
  const everything = Object.fromEntries(NATIVE_KEYS.map((key) => [key, true]))
  for (const profileID of registeredHarnessIDs()) {
    if (!(profileID in projection.harnessTypes)) continue
    const claims = canonicalCapabilityClaims(profileID, everything)
    const declared = new Set(projection.harnessTypes[profileID])
    for (const id of claims) assert.ok(declared.has(id), `${profileID}: ${id}`)
    // 一个"全播发"的原生声明也不可能带出 native_continuation / attach / steer：
    // 原生表里根本没有能证明它们的键。
    for (const forbidden of ["native_continuation", "attach", "steer"]) {
      assert.ok(!claims.includes(forbidden), `${profileID} promoted ${forbidden}`)
    }
  }
})

test("a native claim the declaration rejects is dropped, not raised", () => {
  // hermes 未声明 attach / permissions，即使原生播发它们也不出现。
  const claims = canonicalCapabilityClaims("hermes", { prompt: true, streaming: true, permissions: true })
  assert.deepEqual(claims, ["start", "stream"])
  // 而 permissions: false 时不出现（原生只认 === true）。
  assert.deepEqual(canonicalCapabilityClaims("hermes", { permissions: false }), [])
})

test("permissions is mapped only when the native advertisement really says so", () => {
  assert.ok(!canonicalCapabilityClaims("hermes").includes("permissions"))
  assert.ok(!canonicalCapabilityClaims("pi").includes("permissions"))
  assert.deepEqual(canonicalCapabilityClaims("codex", { permissions: true }), ["permissions"])
})

test("canonicalCapabilityClaims returns a sorted, de-duplicated id list", () => {
  const claims = canonicalCapabilityClaims("codex", {
    prompt: true, streaming: true, permissions: true, agents: true, models: true,
  })
  assert.deepEqual(claims, [...claims].sort())
  assert.deepEqual(claims, [...new Set(claims)])
  assert.deepEqual(claims, ["permissions", "start", "stream"])
  // pi 声明里没有 permissions，所以同一个原生声明在 pi 上会被静态上限削掉它。
  assert.deepEqual(
    canonicalCapabilityClaims("pi", { prompt: true, streaming: true, permissions: true }),
    ["start", "stream"],
  )
})

test("a non-boolean native claim is refused, never coerced", () => {
  for (const bad of [{ streaming: "yes" }, { streaming: 1 }, { streaming: null },
                     { streaming: [] }, { streaming: undefined }]) {
    assert.throws(() => canonicalCapabilityClaims("pi", bad), /CAPABILITY_CLAIM_NOT_BOOLEAN/)
  }
  assert.throws(() => canonicalCapabilityClaims("pi", ["streaming"]), /CAPABILITY_CLAIM_NOT_BOOLEAN/)
  assert.throws(() => canonicalCapabilityClaims("pi", null), /CAPABILITY_CLAIM_NOT_BOOLEAN/)
})

test("a profile with no static declaration fails loudly instead of returning nothing", () => {
  // `claude` 是上游 ACP profile id，注册表里的 harness_type 是 `claude-code`；两者口径
  // 不同是既有事实，本模块不编 alias 掩盖它。
  assert.throws(() => canonicalCapabilityClaims("claude"), /HARNESS_CAPABILITY_UNDECLARED/)
  // `omp` 只有上游 profile，插件没有官方 TOML 条目。
  assert.throws(() => canonicalCapabilityClaims("omp"), /HARNESS_CAPABILITY_UNDECLARED/)
  // 完全不认识的 id。
  assert.throws(() => canonicalCapabilityClaims("nope"), /HARNESS_PROFILE_UNREGISTERED/)
})

test("a native driver must hand in the abilities it advertises itself", () => {
  // OpenCode 不是 ACP profile（不得被伪装成 profile），所以它必须显式传驱动播发的布尔。
  assert.throws(() => canonicalCapabilityClaims("opencode"), /HARNESS_PROFILE_UNREGISTERED/)
  assert.deepEqual(canonicalCapabilityClaims("opencode", {}), [])
  assert.deepEqual(
    canonicalCapabilityClaims("opencode", { prompt: true, streaming: true, permissions: false }),
    ["start", "stream"],
  )
  // 驱动报 image=false 的附件能力在这里根本无法表达成 attach——没有那个键可映射。
  assert.ok(!canonicalCapabilityClaims("opencode", { prompt: true, filesystemBrowser: true })
    .includes("attach"))
})

test("the ceiling is read from the projection and is frozen", () => {
  const declarations = capabilityDeclarations()
  assert.deepEqual(Object.keys(declarations).sort(),
    Object.keys(projection.harnessTypes).sort())
  for (const ids of Object.values(declarations)) {
    assert.deepEqual(ids, [...ids].sort())
    assert.ok(Object.isFrozen(ids))
    assert.throws(() => { ids.push("attach") }, TypeError)
  }
  assert.deepEqual([...declaredCapabilityCeiling("hermes")].sort(),
    [...projection.harnessTypes.hermes].sort())
  // 没有声明的 harness 的上限是空集（不会凭空给出能力）。
  assert.deepEqual([...declaredCapabilityCeiling("omp")], [])
})

test("the plugin's own hermes profile cannot claim more than the registry declares", () => {
  const native = AGENTBOX_HARNESS_PROFILES.hermes.capabilities
  for (const [key, value] of Object.entries(native)) {
    assert.equal(typeof value, "boolean", key)
  }
  const claims = canonicalCapabilityClaims("hermes")
  const declared = new Set(projection.harnessTypes.hermes)
  assert.deepEqual(claims, claims.filter((id) => declared.has(id)))
  assert.ok(!claims.includes("permissions"), "hermes advertises permissions: false")
})
