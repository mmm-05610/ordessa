import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { tmpdir } from "node:os"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { installedArtifactSummary } from "../../runtime/native-artifact-policy.mjs"
import { resolveInstalledLaunch, resolveManagedLaunch } from "../../runtime/access-launch.mjs"
import { nativeServerPlan } from "../../packaging/native-server-plan.mjs"

const REPO = fileURLToPath(new URL("../../../../", import.meta.url))
const ENTRY = fileURLToPath(new URL("../../runtime/access-entry.mjs", import.meta.url))
const BRANDS = [
  ["pi", "pi-runtime", "@automatalabs/pi-acp", "0.5.0"],
  ["codex", "codex-runtime", "@agentclientprotocol/codex-acp", "1.1.14"],
  ["claude-code", "claude-runtime", "@agentclientprotocol/claude-agent-acp", "0.81.2"],
]

// Only metadata is simulated: filesystem contents, links, descriptors and Python digest are real.
function simulateRootAdministration(t, overrides = new Map()) {
  for (const method of ["lstatSync", "fstatSync"]) {
    const original = fs[method]
    t.mock.method(fs, method, (...args) => {
      const stat = original(...args)
      const altered = Object.create(stat)
      Object.assign(altered, { uid: 0, mode: stat.mode & ~0o022 },
        method === "lstatSync" ? overrides.get(String(args[0])) : undefined)
      return altered
    })
  }
}

function fixture(t, brand = BRANDS[0], sharedBase) {
  const base = sharedBase ?? fs.mkdtempSync(path.join(tmpdir(), "ordessa-installed-policy-"))
  if (!sharedBase) t.after(() => fs.rmSync(base, { recursive: true, force: true }))
  const [harness, artifact, packageName, version] = brand
  const root = path.join(base, artifact)
  const packageRoot = path.join(root, "node_modules", packageName)
  fs.mkdirSync(path.join(packageRoot, "dist"), { recursive: true })
  const entry = path.join(packageRoot, "dist/index.js")
  fs.writeFileSync(entry, "process.stdin.resume()\n")
  fs.writeFileSync(path.join(packageRoot, "package.json"), JSON.stringify({ name: packageName, version }))
  return { base, root, entry, harness, packageName, version, manifestPath: `${root}.manifest.json`,
    launch: { command: process.execPath, args: [entry] } }
}

function manifestFor(f) {
  const summary = installedArtifactSummary(f.root)
  return { schemaVersion: 1, kind: `agentbox-${path.basename(f.root)}-artifact`,
    adapter: { package: f.packageName, version: f.version, entry: `node_modules/${f.packageName}/dist/index.js` },
    treeDigest: summary.digest, entries: summary.entries, bytes: summary.bytes,
    sourceLockDigest: `sha256:${"a".repeat(64)}` }
}

function publishManifest(f, manifest = manifestFor(f)) {
  fs.writeFileSync(f.manifestPath, JSON.stringify(manifest))
}

for (const brand of BRANDS) {
  test(`${brand[0]}: simulated root metadata verifies actual content against Python v1`, (t) => {
    simulateRootAdministration(t)
    const f = fixture(t, brand)
    publishManifest(f)
    const python = spawnSync("python3", ["-S", "-c",
      "import json,sys; from pacthold_runtime_compat.resource_contracts.runtime_artifacts import runtime_artifact_tree_summary; print(json.dumps(runtime_artifact_tree_summary(sys.argv[1])))", f.root], {
      encoding: "utf8", env: { ...process.env, PYTHONPATH: [path.join(REPO, "packages/pacthold/src"),
        path.join(REPO, "plugins/runtime-compat/src")].join(path.delimiter) },
    })
    assert.equal(python.status, 0, python.stderr)
    assert.deepEqual(installedArtifactSummary(f.root), JSON.parse(python.stdout))
    assert.equal(resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }).source, "installed-artifact")
    const plan = nativeServerPlan({ harnessId: f.harness, pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: f.base })
    assert.equal(Object.isFrozen(plan.args), true)
    assert.deepEqual(plan.args, ["--execution-mode", "native", "--plugin-root", "/opt/ordessa/harness-plugin",
      "--native-harness", f.harness, "--native-adapter-command", process.execPath,
      `--native-adapter-arg=${f.entry}`, "--native-installed-artifact-root", f.base])
    fs.appendFileSync(f.entry, "// tampered\n")
    assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
    assert.throws(() => nativeServerPlan({ harnessId: f.harness,
      pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  })
}

test("multi-brand plan uses individually verified launch references", (t) => {
  simulateRootAdministration(t)
  const first = fixture(t, BRANDS[0])
  const members = [first, ...BRANDS.slice(1).map(brand => fixture(t, brand, first.base))]
  for (const item of members) publishManifest(item)
  const plan = nativeServerPlan({ harnessIds: members.map(item => item.harness),
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: first.base })
  const index = plan.args.indexOf("--native-additional-adapters")
  assert.ok(index > 0)
  assert.deepEqual(JSON.parse(plan.args[index + 1]), members.slice(1).map(item => ({
    harnessId: item.harness, command: process.execPath, args: [item.entry],
  })))
  fs.appendFileSync(members[1].entry, "// tamper one brand\n")
  assert.throws(() => nativeServerPlan({ harnessIds: members.map(item => item.harness),
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: first.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("multi-brand selection never accepts ambiguous or duplicate identities", () => {
  for (const harnessIds of [[], ['pi', 'pi'], [null]]) {
    assert.throws(() => nativeServerPlan({ harnessIds, pluginRoot: "/opt/ordessa/harness-plugin",
      artifactRoot: "/opt/ordessa/artifacts" }), /NATIVE_HARNESS_SELECTION_INVALID/)
  }
  assert.throws(() => nativeServerPlan({ harnessIds: ['pi'], harnessId: 'pi',
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: "/opt/ordessa/artifacts" }),
  /NATIVE_HARNESS_SELECTION_INVALID/)
})

test("installed manifest/brand/argv remain authoritative", (t) => {
  simulateRootAdministration(t)
  const f = fixture(t)
  const manifest = manifestFor(f)
  const resolve = () => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base })
  assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/)
  for (const change of [
    { schemaVersion: 2 }, { kind: "agentbox-codex-runtime-artifact" },
    { adapter: { ...manifest.adapter, version: "9.9.9" } },
    { adapter: { ...manifest.adapter, package: BRANDS[1][2] } },
    { adapter: { ...manifest.adapter, entry: "../elsewhere.js" } },
    { treeDigest: `sha256:${"0".repeat(64)}` }, { sourceLockDigest: "fake" },
    { entries: manifest.entries + 1 }, { bytes: manifest.bytes + 1 },
  ]) {
    publishManifest(f, { ...manifest, ...change })
    assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, JSON.stringify(change))
  }
  fs.writeFileSync(f.manifestPath, "not json")
  assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/)
  publishManifest(f, manifest)
  assert.throws(() => resolveInstalledLaunch("claude", f.launch, { artifactBase: f.base }), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => resolveInstalledLaunch("unknown", f.launch, { artifactBase: f.base }), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => resolveInstalledLaunch("codex", f.launch, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("pi", { ...f.launch, args: [f.entry, "--anything"] }, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("pi", { ...f.launch, command: "/another/node" }, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: `${f.base}/../escape` }), /ADAPTER_LAUNCH_MISMATCH/)
  fs.writeFileSync(path.join(path.dirname(path.dirname(f.entry)), "package.json"),
    JSON.stringify({ name: f.packageName, version: "9.9.9" }))
  publishManifest(f)
  assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, "tree digest alone cannot replace the package pin")
})

test("every ancestor, tree member and sibling manifest require root ownership and protected modes", (t) => {
  const overrides = new Map()
  simulateRootAdministration(t, overrides)
  const f = fixture(t)
  publishManifest(f)
  for (const file of ["/", "/tmp", f.base, f.root, path.dirname(f.entry), f.entry, f.manifestPath]) {
    for (const change of [{ uid: 1000 }, { mode: fs.lstatSync(file).mode | 0o022 }]) {
      overrides.set(file, change)
      assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/, file)
      overrides.delete(file)
    }
  }
  fs.symlinkSync(f.entry, path.join(f.root, "linked.js"))
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  fs.unlinkSync(path.join(f.root, "linked.js"))
  const fifo = path.join(f.root, "special")
  assert.equal(spawnSync("mkfifo", [fifo]).status, 0)
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  fs.unlinkSync(fifo)
  const savedManifest = `${f.base}/saved.json`
  fs.renameSync(f.manifestPath, savedManifest)
  fs.symlinkSync(savedManifest, f.manifestPath)
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  fs.unlinkSync(f.manifestPath)
  fs.renameSync(savedManifest, f.manifestPath)
  fs.renameSync(f.root, `${f.root}-real`)
  fs.symlinkSync(`${f.root}-real`, f.root)
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("actual user-owned chmod555 tree is refused; old managed route still requires its ro source", (t) => {
  const f = fixture(t)
  fs.chmodSync(f.root, 0o555)
  try {
    assert.notEqual(fs.lstatSync(f.root).uid, 0, "this negative proof uses actual user ownership")
    assert.throws(() => installedArtifactSummary(f.root), /untrusted installed asset/)
    assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
    assert.throws(() => resolveManagedLaunch("pi", f.launch, { artifactBase: f.base,
      mountInfoText: `1 0 0:1 / / rw - ext4 /dev/test rw\n` }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  } finally { fs.chmodSync(f.root, 0o755) }
})

function entryRun(args, message, environment = {}) {
  const result = spawnSync(process.execPath, [ENTRY, ...args], { encoding: "utf8", timeout: 5000,
    input: message ? `${JSON.stringify(message)}\n` : "", env: { ...process.env, AGENTBOX_SIDECAR_ISOLATED: "", ...environment } })
  assert.equal(result.error, undefined)
  return result.stdout.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line))
}

test("startup root is native-only, immutable from connect and never falls back", (t) => {
  const f = fixture(t)
  const argv = ["--native", "--installed-artifact-root", f.base]
  const connect = { op: "connect", id: 1, harness: "pi", launch: f.launch }
  const result = entryRun(argv, connect)
  assert.equal(result.find((row) => row.id === 1)?.error.code, "ADAPTER_ARTIFACT_UNVERIFIED")
  for (const key of ["artifactBase", "installedArtifactRoot", "treeDigest", "manifest"]) {
    const refused = entryRun(argv, { ...connect, [key]: f.base })
    assert.equal(refused.find((row) => row.id === 1)?.error.code, "ACP_CONNECT_FIELD_UNKNOWN")
    const launchRefused = entryRun(argv, { ...connect, launch: { ...f.launch, [key]: f.base } })
    assert.equal(launchRefused.find((row) => row.id === 1)?.error.code, "ADAPTER_LAUNCH_FIELD_UNKNOWN")
  }
  const conflict = entryRun(argv, null, { AGENTBOX_SIDECAR_ISOLATED: "1" })
  assert.equal(conflict[0].error.code, "SIDECAR_MODE_CONFLICT")
  for (const invalid of [["--installed-artifact-root", f.base], ["--native", "--installed-artifact-root", "relative"],
    [...argv, "--controlled-test-peer"]]) {
    assert.equal(entryRun(invalid, null)[0].error.code, "SIDECAR_MODE_INVALID")
  }
})
