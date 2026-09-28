import assert from "node:assert/strict"
import { mkdtemp, readFile, rm, symlink, writeFile } from "node:fs/promises"
import { mkdir } from "node:fs/promises"
import { spawnSync } from "node:child_process"
import { tmpdir } from "node:os"
import path from "node:path"
import test from "node:test"
import { controlledHarness, withSidecar } from "./sidecar_harness.mjs"
import { resolveManagedLaunch } from "../../runtime/access-launch.mjs"

const orchestrationPeer = path.resolve("tests/acp_orchestration/fixtures/bidirectional_acp_peer.mjs")

const pins = [
  ["pi", "pi-acp", "0.5.0"],
  ["codex", "codex-acp", "1.1.14"],
  ["claude-code", "claude-agent-acp", "0.81.2"],
]

async function fakeAdapter(root, binary, version) {
  const command = path.join(root, binary)
  await writeFile(command, `#!/usr/bin/env node\nif (process.argv[2] === "--version") { console.log(${JSON.stringify(`${binary} ${version}`)}); process.exit(0) }\nawait import(${JSON.stringify(new URL(`file://${controlledHarness}`).href)})\n`, { mode: 0o755 })
  return command
}

test("G05: each canonical brand refuses a self-asserted installed adapter", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "ordessa-adapter-route-"))
  try {
    for (const [harness, binary, version] of pins) {
      const command = await fakeAdapter(root, binary, version)
      await withSidecar(async ({ sidecar }) => {
        const result = await sidecar.request({ op: "connect", harness, launch: { command, args: [] } })
        assert.equal(result.ok, false)
        assert.equal(result.error.code, "ADAPTER_LAUNCH_MISMATCH")
        assert.deepEqual(await sidecar.allNotes(), [])
      }, {}, { controlledPeer: false })
    }
  } finally { await rm(root, { recursive: true, force: true }) }
})

test("G05: the orchestration fixture needs an explicit controlled entry mode", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "ordessa-orchestration-peer-"))
  try {
    const launch = { command: process.execPath, args: [orchestrationPeer] }
    await withSidecar(async ({ sidecar }) => {
      const refused = await sidecar.connect({ harness: "pi", launch })
      assert.equal(refused.ok, false)
      assert.equal(refused.error.code, "ADAPTER_LAUNCH_MISMATCH")
    }, { HD003_LOG: path.join(root, "peer") }, { controlledPeer: false })
    await withSidecar(async ({ sidecar }) => {
      const refused = await sidecar.connect({ harness: "pi", launch })
      assert.equal(refused.ok, false)
      assert.equal(refused.error.code, "ADAPTER_LAUNCH_MISMATCH",
        "ambient test marker cannot enable the controlled route without its startup flag")
    }, { HD003_LOG: path.join(root, "peer"), AGENTBOX_ACCESS_TEST_MODE: "controlled-peer-v1" },
    { controlledPeer: false })
    await withSidecar(async ({ sidecar }) => {
      const connected = await sidecar.connect({ harness: "pi", launch })
      assert.equal(connected.ok, true, JSON.stringify(connected))
      const closed = await sidecar.request({ op: "close" })
      assert.equal(closed.ok, true)
      assert.equal(closed.result.released, true)
    }, { HD003_LOG: path.join(root, "peer") })
    await withSidecar(async ({ sidecar }) => {
      const refused = await sidecar.connect({ harness: "pi", launch: {
        command: process.execPath, args: [path.join(root, "arbitrary.mjs")],
      } })
      assert.equal(refused.ok, false)
      assert.equal(refused.error.code, "CONTROLLED_PEER_MISMATCH")
    }, { HD003_LOG: path.join(root, "peer") })
    await withSidecar(async ({ sidecar }) => {
      const refused = await sidecar.connect({ harness: "codex", launch })
      assert.equal(refused.ok, false, "the root orchestration peer is only a pi fixture")
      assert.equal(refused.error.code, "CONTROLLED_PEER_MISMATCH")
    }, { HD003_LOG: path.join(root, "peer") })
  } finally { await rm(root, { recursive: true, force: true }) }
})

test("G05: an alias path cannot select the controlled orchestration peer", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "ordessa-orchestration-alias-"))
  try {
    const alias = path.join(root, "peer-alias.mjs")
    await symlink(orchestrationPeer, alias)
    await withSidecar(async ({ sidecar }) => {
      const refused = await sidecar.connect({ harness: "pi", launch: {
        command: process.execPath, args: [alias],
      } })
      assert.equal(refused.ok, false)
      assert.equal(refused.error.code, "CONTROLLED_PEER_MISMATCH")
    }, { HD003_LOG: path.join(root, "peer") })
  } finally { await rm(root, { recursive: true, force: true }) }
})

test("G05: wrong brand, wrong version, legacy alias, and renderer-chosen command are refused before spawn", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "ordessa-adapter-refuse-"))
  try {
    const codex = await fakeAdapter(root, "codex-acp", "1.1.14")
    const wrongVersion = await fakeAdapter(root, "pi-acp", "99.0.0")
    await withSidecar(async ({ sidecar }) => {
      const selfAsserted = await sidecar.request({ op: "connect", harness: "codex",
        launch: { command: codex, args: [] } })
      assert.equal(selfAsserted.error.code, "ADAPTER_LAUNCH_MISMATCH",
        "a fake --version is not artifact provenance")
    }, {}, { controlledPeer: false })
    await withSidecar(async ({ sidecar }) => {
      for (const [harness, command, code] of [
        ["pi", codex, "ADAPTER_LAUNCH_MISMATCH"],
        ["pi", wrongVersion, "ADAPTER_LAUNCH_MISMATCH"],
        ["claude", codex, "ADAPTER_LAUNCH_MISMATCH"],
        ["codex", process.execPath, "ADAPTER_LAUNCH_MISMATCH"],
      ]) {
        const result = await sidecar.request({ op: "connect", harness, launch: { command, args: [] } })
        assert.equal(result.ok, false)
        assert.equal(result.error.code, code)
      }
      const legacyAlias = await sidecar.request({ op: "connect", harness: "claude",
        launch: { command: "npx", args: ["--yes",
          "--package=@agentclientprotocol/claude-agent-acp@0.75.1", "claude-agent-acp"] } })
      assert.equal(legacyAlias.error.code, "ADAPTER_LAUNCH_MISMATCH",
        "the historical npx route cannot bypass the fixed legacy artifact")
      const injected = await sidecar.request({ op: "connect", harness: "codex",
        launch: { command: codex, args: [], environment: { NODE_OPTIONS: "--require=/tmp/other.js" } } })
      assert.equal(injected.error.code, "ADAPTER_ENVIRONMENT_INVALID")
      assert.deepEqual(await sidecar.allNotes(), [], "no refused launch reaches the ACP peer")
    }, {}, { controlledPeer: false })
  } finally { await rm(root, { recursive: true, force: true }) }
})

test("G05: Claude alias and canonical route to distinct pinned read-only artifact entries", async () => {
  const base = await mkdtemp(path.join(tmpdir(), "ordessa-claude-artifacts-"))
  try {
    for (const [harness, artifact, version] of [
      ["claude", "claude-legacy-runtime", "0.75.1"],
      ["claude-code", "claude-runtime", "0.81.2"],
    ]) {
      const packageRoot = path.join(base, artifact, "node_modules", "@agentclientprotocol", "claude-agent-acp")
      const entry = path.join(packageRoot, "dist", "index.js")
      await mkdir(path.dirname(entry), { recursive: true })
      await writeFile(path.join(packageRoot, "package.json"), JSON.stringify({
        name: "@agentclientprotocol/claude-agent-acp", version, type: "module",
      }))
      await writeFile(entry, `await import(${JSON.stringify(new URL(`file://${controlledHarness}`).href)})\n`)
      const mountInfoText = `100 1 0:1 / ${path.join(base, artifact)} ro - tmpfs tmpfs ro\n`
      const requested = { command: process.execPath, args: [entry] }
      const selected = resolveManagedLaunch(harness, requested, { artifactBase: base, mountInfoText })
      assert.equal(selected.version, version)
      assert.equal(selected.source, "managed-artifact")
      const peer = spawnSync(selected.command, selected.args, {
        input: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: {} }) + "\n",
        encoding: "utf8", timeout: 5000,
      })
      assert.equal(peer.status, 0, peer.stderr)
      assert.equal(JSON.parse(peer.stdout.split("\n").find(Boolean)).result.agentInfo.name, "controlled-harness")
      assert.throws(() => resolveManagedLaunch(harness, requested, { artifactBase: base,
        mountInfoText: mountInfoText.replace(" ro -", " rw -") }), /ADAPTER_ARTIFACT_UNVERIFIED/)
      const other = harness === "claude" ? "claude-code" : "claude"
      assert.throws(() => resolveManagedLaunch(other, requested, { artifactBase: base, mountInfoText }),
        /ADAPTER_LAUNCH_MISMATCH/)
    }
  } finally { await rm(base, { recursive: true, force: true }) }
})

test("G05: legacy brands keep descriptor routes but reject arbitrary renderer executables", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "ordessa-legacy-route-"))
  try {
    const omp = await fakeAdapter(root, "omp", "controlled")
    await withSidecar(async ({ sidecar }) => {
      const wrong = await sidecar.request({ op: "connect", harness: "dsh",
        launch: { command: omp, args: ["--profile", "acp"] } })
      assert.equal(wrong.error.code, "ADAPTER_LAUNCH_MISMATCH")
      const arbitrary = await sidecar.request({ op: "connect", harness: "omp",
        launch: { command: process.execPath, args: [controlledHarness] } })
      assert.equal(arbitrary.error.code, "ADAPTER_LAUNCH_MISMATCH")
      const routed = await sidecar.request({ op: "connect", harness: "omp",
        launch: { command: "omp", args: ["acp"] } })
      assert.equal(routed.ok, true, JSON.stringify(routed))
      assert.equal(routed.result.launch.source, "legacy-profile-route")
      assert.equal((await sidecar.request({ op: "close" })).ok, true)
    }, { PATH: `${root}${path.delimiter}${process.env.PATH ?? ""}` }, { controlledPeer: false })
  } finally { await rm(root, { recursive: true, force: true }) }
})

test("G05: a version-probe executable cannot replace itself before managed spawn", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "ordessa-probe-swap-"))
  try {
    const command = path.join(root, "pi-acp")
    const replacement = path.join(root, "replacement")
    const marker = path.join(root, "unexpected-launch")
    await writeFile(replacement, `#!/usr/bin/env node\nrequire("node:fs").writeFileSync(${JSON.stringify(marker)}, "ran")\n`, { mode: 0o755 })
    await writeFile(command, `#!/usr/bin/env node\nif (process.argv[2] === "--version") { require("node:fs").renameSync(${JSON.stringify(replacement)}, ${JSON.stringify(command)}); console.log("pi-acp 0.5.0"); process.exit(0) }\n`, { mode: 0o755 })
    await withSidecar(async ({ sidecar }) => {
      const result = await sidecar.request({ op: "connect", harness: "pi", launch: { command, args: [] } })
      assert.equal(result.ok, false, "a self-replacing version probe must not launch its replacement")
      assert.equal(await readFile(marker, "utf8").catch(() => null), null)
    }, { ORDESSA_HARNESS_TRUSTED_INSTALL_ROOTS: root }, { controlledPeer: false })
  } finally { await rm(root, { recursive: true, force: true }) }
})
