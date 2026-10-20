import { capturedLaunchText } from "../../../../apps/server/tests/support/captured_launch.mjs"
import { launchDeclaration as codexLaunch } from "../../../../plugins/harness/codex/src/ordessa_harness_codex/acp/launch_codex.mjs"
import { launchDeclaration as claudeCodeLaunch } from "../../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/launch_claude_code.mjs"
import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { tmpdir } from "node:os"
import { execFileSync, spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { installedArtifactSummary, verifyInstalledArtifact } from "../../../../packages/execution/agents/src/ordessa_execution_agents/harness/providers/resolution/_deployment/native-artifact-policy.mjs"
import { installedLaunchReference as defaultInstalledLaunchReference, resolveInstalledLaunch as defaultResolveInstalledLaunch,
  resolveManagedLaunch as defaultResolveManagedLaunch } from "../../../../apps/server/tests/support/launch_policy.mjs"
import { captureLaunchCatalog } from "../../../../apps/server/src/ordessa_server/composition/native_channels/launch_catalog.mjs"
import { selectedLaunchPorts } from "../../../../apps/server/src/ordessa_server/composition/native_channels/selected_launch_ports.mjs"
import { bindLaunchPolicy } from "../../../../apps/server/src/ordessa_server/composition/native_channels/launch_policy.mjs"
import { nativeServerPlan } from "../../../../apps/server/src/ordessa_server/composition/native_channels/native_server_plan.mjs"

const REPO = fileURLToPath(new URL("../../../../", import.meta.url))
const ENTRY = fileURLToPath(new URL("../../../../apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs", import.meta.url))
const PROFILE_ENTRIES = {
  codex: fileURLToPath(new URL('../../../../plugins/harness/codex/src/ordessa_harness_codex/acp/profile/entry.mjs', import.meta.url)),
  'claude-code': fileURLToPath(new URL('../../../../plugins/harness/claude-code/src/ordessa_harness_claude_code/acp/profile/entry.mjs', import.meta.url)),
}
const BRANDS = [
  ["pi", "pi-runtime", "@automatalabs/pi-acp", "0.5.0"],
  ["codex", "codex-runtime", "@agentclientprotocol/codex-acp", "1.1.14"],
  ["claude-code", "claude-runtime", "@agentclientprotocol/claude-agent-acp", "0.81.2"],
]

// Receiving map: old Pi enhanced-route cases now prove default-route refusal,
// while their still-valid tree/digest/ownership/variant assertions run through
// the shared artifact verifier and the currently declared Codex/Claude routes.
// Deep route cases explicitly select those real owner declarations; the default
// product capture remains Pi-only and Pi's installed route stays unavailable.
let explicitLaunchText
function artifactLaunchText() {
  if (explicitLaunchText === undefined) {
    const python = process.env.ORDESSA_TEST_PYTHON
    if (!python) throw new Error("ORDESSA_TEST_PYTHON_REQUIRED")
    const program = [
      "import sys",
      "from ordessa_server.composition.harness_catalog import capture_harness_catalog",
      "from ordessa_harness_codex.registration_declarations import registration_declarations as codex",
      "from ordessa_harness_claude_code.registration_declarations import registration_declarations as claude_code",
      "selected = (codex(), claude_code())",
      "captured = capture_harness_catalog(selected, launch_declarations=selected)",
      "sys.stdout.buffer.write(captured.launch_descriptor_bytes)",
    ].join("; ")
    explicitLaunchText = execFileSync(python, ["-c", program], { cwd: REPO, encoding: "utf8" })
  }
  return explicitLaunchText
}

let explicitPolicy
function artifactLaunchPolicy() {
  explicitPolicy ??= bindLaunchPolicy(captureLaunchCatalog(artifactLaunchText(), selectedLaunchPorts))
  return explicitPolicy
}

const resolveInstalledLaunch = (...args) => artifactLaunchPolicy().resolveInstalledLaunch(...args)
const installedLaunchReference = (...args) => artifactLaunchPolicy().installedLaunchReference(...args)
const resolveManagedLaunch = (...args) => artifactLaunchPolicy().resolveManagedLaunch(...args)
const nativeArtifactOptions = (harness, artifactBase) => ({ artifactBase, variant: "native-profile",
  extensionPolicy: { ...(harness === "codex" ? codexLaunch() : claudeCodeLaunch()).nativeExtension,
    mode: "native", variant: "native-profile" } })

function currentPiRouteRefused(t, f) {
  assert.throws(() => defaultInstalledLaunchReference("pi", f.base), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => defaultResolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ROUTE_UNBOUND/)
}

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

function profileFixture(t, brand = BRANDS[1], sharedBase) {
  const f = fixture(t, brand, sharedBase)
  const declaration = (f.harness === "codex" ? codexLaunch() : claudeCodeLaunch()).nativeExtension
  const directory = path.dirname(f.entry)
  f.entry = path.join(directory, "ordessa-profile.mjs")
  fs.copyFileSync(PROFILE_ENTRIES[f.harness], f.entry)
  f.launch.args = [f.entry]
  f.options = nativeArtifactOptions(f.harness, f.base)
  const manifest = manifestFor(f)
  manifest.adapter.entry = `node_modules/${f.packageName}/dist/ordessa-profile.mjs`
  manifest.extension = { id: declaration.id, version: 1,
    configurationQuery: "_ordessa/session/configuration", instanceDirectoryRequired: true,
    upstreamSourceDigest: `sha256:${declaration.source}`,
    ...(declaration.managedAccountScope ? { managedAccountScope: true } : {}) }
  f.manifest = manifest
  publishManifest(f, manifest)
  return f
}

for (const brand of BRANDS.slice(1)) {
  test(`${brand[0]}: native Profile assets require explicit selection and exact extension provenance`, t => {
    simulateRootAdministration(t)
    const f = profileFixture(t, brand)
    const originalEntry = path.join(path.dirname(f.entry), "index.js")
    const options = f.options
    assert.throws(() => installedLaunchReference(f.harness, f.base), /ADAPTER_ARTIFACT_UNVERIFIED/)
    assert.deepEqual(resolveInstalledLaunch(f.harness, f.launch, options),
      { ...f.launch, source: "installed-artifact", version: f.version })
    if (f.harness === "codex") {
      publishManifest(f, {...f.manifest, extension: {...f.manifest.extension, managedAccountScope: true}})
      assert.deepEqual(resolveInstalledLaunch(f.harness, f.launch, options),
        {...f.launch, source: "installed-artifact", version: f.version})
      publishManifest(f, f.manifest)
    }
    const enhancedPlan = nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: f.harness,
      pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: f.base,
      nativeProfileHarnesses: [f.harness] })
    const flag = enhancedPlan.args.indexOf("--native-profile-harness")
    assert.equal(enhancedPlan.args[flag + 1], f.harness)
    assert.ok(enhancedPlan.args.includes(`--native-adapter-arg=${f.entry}`))
    assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: f.harness,
      pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
    for (const delta of [{ id: "wrong-profile" }, { version: 2 },
      { instanceDirectoryRequired: false }, { upstreamSourceDigest: "invalid" },
      { upstreamSourceDigest: `sha256:${"b".repeat(64)}` }, { extra: true },
      { managedAccountScope: false }, { managedAccountScope: "true" }, { managedAccountScope: null },
      ...(f.harness === "claude-code" ? [{ managedAccountScope: true }] : [])]) {
      publishManifest(f, { ...f.manifest, extension: { ...f.manifest.extension, ...delta } })
      assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, options), /ADAPTER_ARTIFACT_UNVERIFIED/)
    }
    publishManifest(f, { ...f.manifest, extension: undefined })
    assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, options), /ADAPTER_ARTIFACT_UNVERIFIED/)
    publishManifest(f, { ...f.manifest, extension: undefined,
      adapter: { ...f.manifest.adapter, entry: `node_modules/${f.packageName}/dist/index.js` } })
    assert.deepEqual(installedLaunchReference(f.harness, f.base).args, [originalEntry])
  })
}

test("current default selection keeps Pi identity but refuses its retired installed launcher", (t) => {
  simulateRootAdministration(t)
  const descriptors = JSON.parse(capturedLaunchText())
  assert.deepEqual(descriptors.harnesses.map(item => item.id), ["pi"])
  const pi = fixture(t, BRANDS[0])
  publishManifest(pi)
  assert.throws(() => defaultInstalledLaunchReference("pi", pi.base), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => defaultResolveInstalledLaunch("pi", pi.launch, { artifactBase: pi.base }), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => defaultInstalledLaunchReference("codex", pi.base), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => nativeServerPlan({ capturedLaunchText: capturedLaunchText(), harnessId: "pi",
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: pi.base }), /ADAPTER_ROUTE_UNBOUND/)
  const entry = entryRun(["--native", "--installed-artifact-root", pi.base, "--pi-profile-bridge"],
    { op: "connect", id: 1, harness: "pi", launch: pi.launch }, {}, capturedLaunchText())
  assert.equal(entry.find(row => row.id === 1)?.error.code, "ADAPTER_ROUTE_UNBOUND")
  // The generic artifact verifier remains independently covered without reviving Pi's old route.
  assert.equal(verifyInstalledArtifact({ artifactBase: pi.base, artifact: "pi-runtime",
    packageName: pi.packageName, version: pi.version }), pi.entry)
})

test("Pi's retired variant route stays unavailable while artifact verifier rejects unselected variants", (t) => {
  simulateRootAdministration(t)
  const pi = fixture(t, BRANDS[0])
  publishManifest(pi)
  assert.throws(() => defaultInstalledLaunchReference("pi", pi.base, { variant: "pi-profile" }), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => verifyInstalledArtifact({ artifactBase: pi.base, artifact: "pi-runtime",
    packageName: pi.packageName, version: pi.version, variant: "pi-profile" }), /variant invalid/)
})

test("native Profile selection cannot select a different, duplicated or invalid brand", () => {
  for (const nativeProfileHarnesses of [true, ["pi"], ["claude-code"], ["codex", "codex"], [{}]]) {
    assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: "codex",
      pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: "/opt/ordessa/artifacts", nativeProfileHarnesses }),
    /NATIVE_PROFILE_SELECTION_INVALID/)
  }
})

test("native Profile manifest identity, extension metadata and entire tree remain authoritative", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t, BRANDS[1])
  const resolve = () => resolveInstalledLaunch(f.harness, f.launch, f.options)
  const extension = f.manifest.extension
  const policy = f.options.extensionPolicy
  for (const change of [
    { kind: "agentbox-other-runtime-artifact" },
    { adapter: { ...f.manifest.adapter, entry: `node_modules/${f.packageName}/dist/index.js` } },
    { adapter: { ...f.manifest.adapter, entry: "../ordessa-profile.mjs" } },
    { adapter: { ...f.manifest.adapter, version: "9.9.9" } },
    { adapter: { ...f.manifest.adapter, package: BRANDS[2][2] } },
    { extension: undefined }, { extension: {} },
    ...[{ id: "other" }, { version: 2 }, { configurationQuery: "session/set_config_option" },
      { instanceDirectoryRequired: false }, { extra: true }, { upstreamSourceDigest: `sha256:${"0".repeat(64)}` }].map(delta => (
      { extension: { ...extension, ...delta } })),
    { ordessaExtension: { id: "wrong-owner" } },
    { treeDigest: `sha256:${"0".repeat(64)}` }, { sourceLockDigest: "invalid" },
    { entries: f.manifest.entries + 1 }, { bytes: f.manifest.bytes + 1 },
  ]) {
    publishManifest(f, { ...f.manifest, ...change })
    assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, JSON.stringify(change))
  }
  publishManifest(f, f.manifest)
  for (const name of ["index.js", "ordessa-profile.mjs"]) {
    const file = path.join(path.dirname(f.entry), name)
    const original = fs.readFileSync(file)
    fs.appendFileSync(file, "\n// changed module\n")
    assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, name)
    fs.writeFileSync(file, original)
  }
  assert.equal(resolve().version, f.version)
  assert.equal(policy.id, extension.id)
})

test("installed route rejects unselected brands, unexpected argv and unknown variants", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t, BRANDS[1])
  for (const harness of ["pi", "unknown", "opencode"]) {
    assert.throws(() => resolveInstalledLaunch(harness, f.launch, f.options), /ADAPTER_ROUTE_UNBOUND/)
    assert.throws(() => installedLaunchReference(harness, f.base, { variant: "native-profile" }), /ADAPTER_ROUTE_UNBOUND/)
  }
  for (const variant of [null, true, "enhanced", "../native-profile"]) {
    assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { ...f.options, variant }), /ADAPTER_ROUTE_UNBOUND/)
  }
  for (const launch of [{ ...f.launch, command: "/another/node" },
    { ...f.launch, args: [f.entry, "--anything"] }, { ...f.launch, args: [path.join(f.root, "arbitrary.mjs")] }]) {
    assert.throws(() => resolveInstalledLaunch(f.harness, launch, f.options), /ADAPTER_LAUNCH_MISMATCH/)
  }
  assert.throws(() => verifyInstalledArtifact({ artifactBase: f.base, artifact: f.harness === "codex" ? "codex-runtime" : "claude-runtime",
    packageName: BRANDS[1][2], version: BRANDS[1][3], variant: "native-profile" }), /variant invalid/)
})

test("native Profile verifier retains every root ownership and mode guard", (t) => {
  const overrides = new Map()
  simulateRootAdministration(t, overrides)
  const f = profileFixture(t, BRANDS[1])
  for (const file of ["/", "/tmp", f.base, f.root, path.dirname(f.entry), f.entry, f.manifestPath]) {
    for (const change of [{ uid: 1000 }, { mode: fs.lstatSync(file).mode | 0o022 }]) {
      overrides.set(file, change)
      assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, f.options), /ADAPTER_ARTIFACT_UNVERIFIED/, file)
      overrides.delete(file)
    }
  }
  for (const artifactBase of ["relative", `${f.base}/`, `${f.base}/../${path.basename(f.base)}`, `${f.base}\0`]) {
    assert.throws(() => installedLaunchReference(f.harness, artifactBase, { variant: "native-profile" }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  }
  const saved = `${f.entry}.real`
  fs.renameSync(f.entry, saved)
  fs.symlinkSync(saved, f.entry)
  assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, f.options), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("actual user-owned native Profile tree is refused despite a matching manifest", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t, BRANDS[1])
  t.mock.restoreAll()
  fs.chmodSync(f.root, 0o555)
  try {
    assert.notEqual(fs.lstatSync(f.root).uid, 0)
    assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, f.options), /ADAPTER_ARTIFACT_UNVERIFIED/)
  } finally { fs.chmodSync(f.root, 0o755) }
})

test("native profile plan explicitly selects only the Codex extension binding", (t) => {
  simulateRootAdministration(t)
  const codex = profileFixture(t, BRANDS[1])
  const claude = fixture(t, BRANDS[2], codex.base)
  publishManifest(claude)
  const plan = nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessIds: ["codex", "claude-code"],
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: codex.base, nativeProfileHarnesses: ["codex"] })
  assert.equal(plan.args.filter(arg => arg === "--native-profile-harness").length, 1)
  assert.ok(plan.args.includes(`--native-adapter-arg=${codex.entry}`))
  const index = plan.args.indexOf("--native-additional-adapters")
  assert.deepEqual(JSON.parse(plan.args[index + 1]), [{ harnessId: "claude-code", ...claude.launch }])
  for (const nativeProfileHarnesses of ["codex", null, 1, {}]) {
    assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: "codex",
      pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: codex.base, nativeProfileHarnesses }),
    /NATIVE_PROFILE_SELECTION_INVALID/)
  }
  assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: "codex",
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: codex.base, nativeProfileHarnesses: ["pi"] }),
  /NATIVE_PROFILE_SELECTION_INVALID/)
  fs.appendFileSync(codex.entry, "\n// changed\n")
  assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: "codex",
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: codex.base, nativeProfileHarnesses: ["codex"] }),
  /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("multi-brand launch preserves each binding's independently verified installation root", (t) => {
  simulateRootAdministration(t)
  const codex = profileFixture(t, BRANDS[1])
  const claude = fixture(t, BRANDS[2])
  publishManifest(claude)
  const plan = nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessIds: ["codex", "claude-code"],
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: claude.base,
    artifactRoots: { codex: codex.base }, nativeProfileHarnesses: ["codex"] })
  assert.ok(plan.args.includes(`--native-adapter-arg=${codex.entry}`))
  assert.equal(plan.args[plan.args.indexOf("--native-installed-artifact-root") + 1], codex.base)
  assert.deepEqual(JSON.parse(plan.args[plan.args.indexOf("--native-additional-adapters") + 1]),
    [{ harnessId: "claude-code", ...claude.launch, installedArtifactRoot: claude.base }])
  const reversed = nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessIds: ["claude-code", "codex"],
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: claude.base,
    artifactRoots: { codex: codex.base }, nativeProfileHarnesses: ["codex"] })
  assert.deepEqual(JSON.parse(reversed.args[reversed.args.indexOf("--native-additional-adapters") + 1]),
    [{ harnessId: "codex", ...codex.launch, installedArtifactRoot: codex.base }])
  assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessIds: ["codex", "claude-code"],
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: claude.base,
    artifactRoots: { codex: codex.base, unknown: claude.base }, nativeProfileHarnesses: ["codex"] }),
  /NATIVE_ARTIFACT_ROOT_SELECTION_INVALID/)
})

for (const brand of BRANDS) {
  test(`${brand[0]}: simulated root metadata verifies actual content against Python v1`, (t) => {
    simulateRootAdministration(t)
    const f = fixture(t, brand)
    publishManifest(f)
    const python = spawnSync("python3", ["-S", "-c",
      "import json,sys; from ordessa_execution_agents.harness.providers.resolution.artifacts.tree_identity import runtime_artifact_tree_summary; print(json.dumps(runtime_artifact_tree_summary(sys.argv[1])))", f.root], {
      encoding: "utf8", env: { ...process.env, PYTHONPATH: ["packages/execution/agents/src", "packages/infrastructure/src"].map(part => path.join(REPO, part)).join(path.delimiter) },
    })
    assert.equal(python.status, 0, python.stderr)
    assert.deepEqual(installedArtifactSummary(f.root), JSON.parse(python.stdout))
    assert.equal(verifyInstalledArtifact({ artifactBase: f.base, artifact: path.basename(f.root),
      packageName: f.packageName, version: f.version }), f.entry)
    if (f.harness === "pi") {
      // Pi remains visible in default capture but its old installed route is deliberately disabled.
      currentPiRouteRefused(t, f)
    } else {
      assert.equal(resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }).source, "installed-artifact")
      const plan = nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: f.harness,
        pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: f.base })
      assert.equal(Object.isFrozen(plan.args), true)
      assert.deepEqual(plan.args, ["--execution-mode", "native", "--plugin-root", "/opt/ordessa/harness-plugin",
        "--native-harness", f.harness, "--native-adapter-command", process.execPath,
        `--native-adapter-arg=${f.entry}`, "--native-installed-artifact-root", f.base])
    }
    fs.appendFileSync(f.entry, "// tampered\n")
    assert.throws(() => verifyInstalledArtifact({ artifactBase: f.base,
      artifact: path.basename(f.root), packageName: f.packageName, version: f.version }), /installed artifact digest mismatch/)
    if (f.harness === "pi") {
      assert.throws(() => defaultResolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ROUTE_UNBOUND/)
    } else {
      assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
      assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessId: f.harness,
        pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
    }
  })
}

test("multi-brand plan uses individually verified Codex and Claude Code launch references", (t) => {
  simulateRootAdministration(t)
  const first = fixture(t, BRANDS[1])
  const second = fixture(t, BRANDS[2], first.base)
  for (const item of [first, second]) publishManifest(item)
  const plan = nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessIds: ["codex", "claude-code"],
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: first.base })
  const index = plan.args.indexOf("--native-additional-adapters")
  assert.ok(index > 0)
  assert.deepEqual(JSON.parse(plan.args[index + 1]), [
    { harnessId: "claude-code", command: process.execPath, args: [second.entry] },
  ])
  fs.appendFileSync(second.entry, "// tamper one brand\n")
  assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(), harnessIds: ["codex", "claude-code"],
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: first.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("multi-brand selection never accepts ambiguous or duplicate identities", () => {
  for (const harnessIds of [[], ['pi', 'pi'], [null]]) {
    assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(),  harnessIds, pluginRoot: "/opt/ordessa/harness-plugin",
      artifactRoot: "/opt/ordessa/artifacts" }), /NATIVE_HARNESS_SELECTION_INVALID/)
  }
  assert.throws(() => nativeServerPlan({ capturedLaunchText: artifactLaunchText(),  harnessIds: ['pi'], harnessId: 'pi',
    pluginRoot: "/opt/ordessa/harness-plugin", artifactRoot: "/opt/ordessa/artifacts" }),
  /NATIVE_HARNESS_SELECTION_INVALID/)
})

test("installed manifest/brand/argv remain authoritative", (t) => {
  simulateRootAdministration(t)
  const f = fixture(t, BRANDS[1])
  const manifest = manifestFor(f)
  const resolve = () => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base })
  assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/)
  for (const change of [
    { schemaVersion: 2 }, { kind: "agentbox-wrong-runtime-artifact" },
    { adapter: { ...manifest.adapter, version: "9.9.9" } },
    { adapter: { ...manifest.adapter, package: BRANDS[2][2] } },
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
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => resolveInstalledLaunch("unknown", f.launch, { artifactBase: f.base }), /ADAPTER_ROUTE_UNBOUND/)
  assert.throws(() => resolveInstalledLaunch("claude-code", f.launch, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("codex", { ...f.launch, args: [f.entry, "--anything"] }, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("codex", { ...f.launch, command: "/another/node" }, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("codex", f.launch, { artifactBase: `${f.base}/../escape` }), /ADAPTER_LAUNCH_MISMATCH/)
  fs.writeFileSync(path.join(path.dirname(path.dirname(f.entry)), "package.json"),
    JSON.stringify({ name: f.packageName, version: "9.9.9" }))
  publishManifest(f)
  assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, "tree digest alone cannot replace the package pin")
})

test("every ancestor, tree member and sibling manifest require root ownership and protected modes", (t) => {
  const overrides = new Map()
  simulateRootAdministration(t, overrides)
  const f = fixture(t, BRANDS[1])
  publishManifest(f)
  for (const file of ["/", "/tmp", f.base, f.root, path.dirname(f.entry), f.entry, f.manifestPath]) {
    for (const change of [{ uid: 1000 }, { mode: fs.lstatSync(file).mode | 0o022 }]) {
      overrides.set(file, change)
      assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/, file)
      overrides.delete(file)
    }
  }
  fs.symlinkSync(f.entry, path.join(f.root, "linked.js"))
  assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  fs.unlinkSync(path.join(f.root, "linked.js"))
  const fifo = path.join(f.root, "special")
  assert.equal(spawnSync("mkfifo", [fifo]).status, 0)
  assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  fs.unlinkSync(fifo)
  const savedManifest = `${f.base}/saved.json`
  fs.renameSync(f.manifestPath, savedManifest)
  fs.symlinkSync(savedManifest, f.manifestPath)
  assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  fs.unlinkSync(f.manifestPath)
  fs.renameSync(savedManifest, f.manifestPath)
  fs.renameSync(f.root, `${f.root}-real`)
  fs.symlinkSync(`${f.root}-real`, f.root)
  assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("actual user-owned chmod555 tree is refused; old managed route still requires its ro source", (t) => {
  const f = fixture(t, BRANDS[1])
  fs.chmodSync(f.root, 0o555)
  try {
    assert.notEqual(fs.lstatSync(f.root).uid, 0, "this negative proof uses actual user ownership")
    assert.throws(() => installedArtifactSummary(f.root), /untrusted installed asset/)
    assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, { artifactBase: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
    assert.throws(() => resolveManagedLaunch(f.harness, f.launch, { artifactBase: f.base,
      mountInfoText: `1 0 0:1 / / rw - ext4 /dev/test rw\n` }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  } finally { fs.chmodSync(f.root, 0o755) }
})

function entryRun(args, message, environment = {}, launchText = artifactLaunchText()) {
  const result = spawnSync(process.execPath, [ENTRY, ...args], { encoding: "utf8", timeout: 5000,
    input: message ? `${JSON.stringify(message)}\n` : "", env: { ...process.env,
      AGENTBOX_SIDECAR_ISOLATED: "", ...environment, ORDESSA_CAPTURED_LAUNCH_DESCRIPTORS: launchText,
    } })
  assert.equal(result.error, undefined)
  return result.stdout.trim().split("\n").filter(Boolean).map((line) => JSON.parse(line))
}

for (const brand of BRANDS.slice(1)) {
  test(`${brand[0]}: enhanced access startup never accepts client-owned instance scope`, t => {
    simulateRootAdministration(t)
    const f = profileFixture(t, brand)
    const argv = ['--native', '--installed-artifact-root', f.base, '--native-profile-bridge']
    const connect = { op: 'connect', id: 1, harness: f.harness, launch: f.launch }
    for (const key of ['ORDESSA_NATIVE_INSTANCE_DIR', 'ORDESSA_CODEX_MANAGED_ACCOUNT_DIR', 'HOME', 'CODEX_HOME',
      'CLAUDE_CONFIG_DIR', 'XDG_CONFIG_HOME']) {
      const result = entryRun(argv, { ...connect,
        launch: { ...f.launch, environment: { [key]: '/tmp/foreign' } } })
      assert.equal(result.find(row => row.id === 1)?.error.code, 'ADAPTER_ENVIRONMENT_INVALID')
    }
    assert.equal(entryRun(argv, connect).find(row => row.id === 1)?.error.code, 'ADAPTER_ARTIFACT_UNVERIFIED')
    assert.equal(entryRun(['--native', '--native-profile-bridge'], null)[0].error.code, 'SIDECAR_MODE_INVALID')
    assert.equal(entryRun(argv, { ...connect, harness: 'pi' }).find(row => row.id === 1)?.error.code,
      'HARNESS_UNDISCOVERED')
  })
}

test("enhanced startup selects exact route and refuses client instance overrides", (t) => {
  simulateRootAdministration(t) // Fixture manifest only; child process sees real user ownership.
  const f = profileFixture(t, BRANDS[1])
  const argv = ["--native", "--installed-artifact-root", f.base, "--native-profile-bridge"]
  const connect = { op: "connect", id: 1, harness: f.harness, launch: f.launch }
  // Actual user-owned asset: startup selector is accepted, origin still refuses.
  assert.equal(entryRun(argv, connect).find(row => row.id === 1)?.error.code, "ADAPTER_ARTIFACT_UNVERIFIED")
  for (const name of ["ORDESSA_NATIVE_INSTANCE_DIR", "ORDESSA_CODEX_MANAGED_ACCOUNT_DIR", "HOME", "CODEX_HOME",
    "CLAUDE_CONFIG_DIR", "XDG_CONFIG_HOME"]) {
    const result = entryRun(argv, { ...connect, launch: { ...f.launch, environment: { [name]: "/tmp/foreign" } } })
    assert.equal(result.find(row => row.id === 1)?.error.code, "ADAPTER_ENVIRONMENT_INVALID")
  }
  assert.equal(entryRun(["--native", "--native-profile-bridge"], null)[0].error.code, "SIDECAR_MODE_INVALID")
  assert.equal(entryRun(argv, { ...connect, harness: "pi" }).find(row => row.id === 1)?.error.code,
    "HARNESS_UNDISCOVERED")
})

test("startup root is native-only, immutable from connect and never falls back", (t) => {
  const f = fixture(t, BRANDS[1])
  const argv = ["--native", "--installed-artifact-root", f.base]
  const connect = { op: "connect", id: 1, harness: f.harness, launch: f.launch }
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
