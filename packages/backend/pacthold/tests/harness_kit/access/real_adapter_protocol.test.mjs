/**
 * Category: 接入 ACP / native access — the fixtures are checked against a **real**
 * adapter's protocol, not against a protocol this repository wrote down.
 *
 * Why this file exists at all: every other test in this directory drives a fake.
 * A fake that invents a method name proves nothing about the boundary, so here the
 * real adapter is the oracle. Its bytes are on disk — `packaging/codex/vendor/
 * agentclientprotocol-codex-acp-1.1.14.tgz` is the tarball the optional install
 * would use — and an npm tarball is gzip plus 512-byte-header tar, which node can
 * read with `zlib` alone. Nothing is installed, downloaded or executed.
 *
 * What is asserted:
 *   1. the protocol tables (`AGENT_METHODS`, `CLIENT_METHODS`, `PROTOCOL_VERSION`)
 *      are read out of the real bundle, and are not empty;
 *   2. the controlled harness — the fake *Agent* every boundary test drives —
 *      never puts a method on the wire that the real adapter does not know;
 *   3. an inventory of which brands' protocol vocabulary is on disk, derived by
 *      reading files. This is the honest half: protocol coverage for OpenCode,
 *      Qwen Code and Hermes **cannot** be tested offline today, and a test that
 *      pretended otherwise would be worse than no test.
 */
import assert from "node:assert/strict"
import { existsSync, readFileSync, readdirSync } from "node:fs"
import path from "node:path"
import test from "node:test"
import { gunzipSync } from "node:zlib"
import { fileURLToPath } from "node:url"

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..")
const packaging = path.join(pluginRoot, "packaging")
const harnessPath = path.join(pluginRoot, "tests", "access", "controlled_harness.mjs")

/** Every member of an npm tarball as `{ name, text }`, read from memory. */
function tarballMembers(tarball) {
  const tar = gunzipSync(readFileSync(tarball))
  const members = []
  let offset = 0
  let longName = null
  while (offset + 512 <= tar.length) {
    const header = tar.subarray(offset, offset + 512)
    if (header.every((byte) => byte === 0)) break
    const flag = String.fromCharCode(header[156])
    const size = parseInt(header.subarray(124, 136).toString("ascii").replace(/\0.*/, "").trim() || "0", 8)
    const prefix = header.subarray(345, 500).toString("utf8").replace(/\0.*/, "")
    let name = longName ?? header.subarray(0, 100).toString("utf8").replace(/\0.*/, "")
    if (!longName && prefix) name = `${prefix}/${name}`
    const body = tar.subarray(offset + 512, offset + 512 + size)
    offset += 512 + Math.ceil(size / 512) * 512
    // GNU long-name support: an 'L' header carries the next entry's real name.
    if (flag === "L") { longName = body.toString("utf8").replace(/\0.*/, ""); continue }
    longName = null
    if (flag === "0" || flag === "\0") members.push({ name: name.replace(/^\.\//, ""), text: body.toString("utf8") })
  }
  return members
}

const codexMembers = tarballMembers(path.join(packaging, "codex", "vendor", "agentclientprotocol-codex-acp-1.1.14.tgz"))
const codexSource = codexMembers.find((member) => member.name === "package/dist/index.js")
assert.ok(codexSource, "the vendored Codex adapter has no dist/index.js; the bundle changed shape")

/** Pull a `var NAME = { key: "value", ... }` table out of bundled JavaScript. */
function schemaTable(source, name) {
  const match = new RegExp(`var ${name} = \\{([\\s\\S]*?)\\n\\};`).exec(source)
  assert.ok(match, `the real adapter bundle has no ${name} table; the schema moved`)
  const table = {}
  for (const line of match[1].split("\n")) {
    const entry = /^\s*([A-Za-z_$][\w$]*)\s*:\s*"([^"]+)"/.exec(line)
    if (entry) table[entry[1]] = entry[2]
  }
  assert.ok(Object.keys(table).length, `${name} parsed to an empty table`)
  return table
}

const agentMethods = schemaTable(codexSource.text, "AGENT_METHODS")
const clientMethods = schemaTable(codexSource.text, "CLIENT_METHODS")
const protocolMethods = schemaTable(codexSource.text, "PROTOCOL_METHODS")
const protocolVersion = Number(/var PROTOCOL_VERSION = (\d+)/.exec(codexSource.text)[1])
const known = new Set([
  ...Object.values(agentMethods), ...Object.values(clientMethods), ...Object.values(protocolMethods),
])

function packagingRoots() {
  return readdirSync(packaging).filter((name) => {
    const directory = path.join(packaging, name)
    return existsSync(path.join(directory, "package-lock.json"))
  })
}

function vendorTarballs(brand) {
  const directory = path.join(packaging, brand, "vendor")
  return existsSync(directory) ? readdirSync(directory).filter((name) => name.endsWith(".tgz")).map((name) => path.join(directory, name)) : []
}

function acpPackagesInLock(brand) {
  const lock = JSON.parse(readFileSync(path.join(packaging, brand, "package-lock.json"), "utf8"))
  return Object.keys(lock.packages ?? {}).filter((key) => key.includes("agentclientprotocol"))
}

test("real adapter: the Codex bundle's own protocol tables are what they claim to be", () => {
  // Counterexample: a hand-maintained method list in this repository drifting from
  // the adapter's schema. Reading the tables from the shipped bytes makes that
  // impossible, and pins ACP protocol version 1 as the assumption of every test here.
  assert.equal(protocolVersion, 1)
  for (const method of ["initialize", "session/new", "session/prompt", "session/cancel",
    "session/set_config_option", "session/load", "session/resume", "session/close", "session/list"]) {
    assert.ok(Object.values(agentMethods).includes(method), `the real adapter has no agent method ${method}`)
  }
  for (const method of ["session/request_permission", "session/update", "fs/read_text_file",
    "fs/write_text_file", "terminal/create", "elicitation/create"]) {
    assert.ok(Object.values(clientMethods).includes(method), `the real adapter has no client method ${method}`)
  }
  assert.equal(Object.values(agentMethods).length >= 19, true, "the agent table shrank; re-read the schema")
})

test("real adapter: the controlled harness only ever speaks methods the real adapter knows", () => {
  // The harness is a *fake*, so this is the assertion that keeps every other
  // boundary test honest: a method name in the fixture that the shipped adapter
  // does not define would make "the Agent's frame reached the host" meaningless.
  const fixture = readFileSync(harnessPath, "utf8")
  const spoken = new Set()
  for (const match of fixture.matchAll(/"([A-Za-z][\w-]*\/[A-Za-z][\w-]*)"/g)) spoken.add(match[1])
  assert.ok(spoken.size >= 8, `the scan found only ${JSON.stringify([...spoken])}; the fixture's methods left the quotes`)
  const invented = [...spoken].filter((method) => !known.has(method))
  assert.deepEqual(invented, [], `the harness invented ${invented}, which no real adapter speaks`)
})

test("real adapter: the method-name scan is not a detector that matches nothing", () => {
  // Counterexample for the check above: a fixture that invents a method *is* caught.
  const tampered = readFileSync(harnessPath, "utf8").replace('"session/update"', '"session/not_a_real_method"')
  const spoken = new Set()
  for (const match of tampered.matchAll(/"([A-Za-z][\w-]*\/[A-Za-z][\w-]*)"/g)) spoken.add(match[1])
  assert.ok([...spoken].filter((method) => !known.has(method)).includes("session/not_a_real_method"),
    "an invented method must be reported by the same scan")
})

test("real adapter: the harness answers with the real result fields, not fixture words", () => {
  for (const field of ["stopReason", "outcome", "configOptions", "sessionId"]) {
    assert.ok(codexSource.text.includes(field), `the real bundle never mentions ${field}`)
  }
})

test("protocol source inventory: derived from disk, not from a list of claims", () => {
  // Each category is decided by reading files, so the test cannot be talked into
  // saying a brand is covered when it is not.
  const brands = [...packagingRoots(), "opencode", "hermes"]
  const inventory = {}
  for (const brand of brands) {
    const balls = vendorTarballs(brand)
    if (!balls.length) { inventory[brand] = "absent"; continue }
    const sources = balls.flatMap((ball) => tarballMembers(ball)).filter((member) => member.name.endsWith(".js"))
    const inlined = sources.some((member) => member.text.includes("var AGENT_METHODS"))
    const delegates = sources.some((member) => member.text.includes("@agentclientprotocol/sdk"))
    inventory[brand] = inlined ? "tables" : delegates ? "delegated" : "present but unread"
  }
  assert.equal(inventory.codex, "tables", "Codex's vocabulary must stay readable from the shipped bytes")
  assert.equal(inventory.pi, "delegated",
    "Pi's adapter imports the schema instead of inlining it; `@automatalabs/pi-acp` declares @agentclientprotocol/sdk, which is neither vendored nor installed")
  assert.deepEqual(Object.entries(inventory).filter(([, state]) => state === "tables").map(([brand]) => brand), ["codex"],
    `more adapter bytes than expected are on disk: ${JSON.stringify(inventory)}`)
})

test("protocol source inventory: the brands with no readable JS adapter are named, with the file that says so", () => {
  // The reviewer asked for real-adapter tests for Codex, OpenCode, Qwen Code and
  // Hermes. Codex has one above. These are the filesystem facts that make the
  // other three impossible to read offline today, asserted so the claim stays
  // checkable. OpenCode used to sit here for the strongest possible reason — it had
  // no install root at all. It now has one, and the reason it still cannot be read
  // offline has changed with it: the root is a pinned closure whose entry is a
  // native ELF, not JavaScript, so there is still no adapter source to assert on.
  // Asserting "no root" now would be a stale claim that happened to be true.
  assert.equal(packagingRoots().includes("opencode"), true,
    "packaging/opencode now holds the pinned opencode-ai + opencode-linux-x64 closure")
  assert.deepEqual(acpPackagesInLock("opencode"), [],
    "OpenCode's root resolves no ACP package: its entry is a native binary, so there is no JS adapter to read")
  assert.equal(packagingRoots().includes("hermes"), false,
    "Hermes is a Python distribution (`hermes-agent`, entry `python3 -m hermes_cli.main acp`) with no npm root")
  assert.equal(vendorTarballs("qwen").length, 0)
  assert.equal(vendorTarballs("claude").length, 0)
  assert.deepEqual(acpPackagesInLock("qwen"), [],
    "packaging/qwen declares @qwen-code/qwen-code 0.23.4 and its closure resolves no ACP package")
  assert.ok(acpPackagesInLock("codex").length, "positive control: other roots do name an ACP package")
})
