import assert from "node:assert/strict"
import fs from "node:fs"
import path from "node:path"
import { tmpdir } from "node:os"
import { spawnSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import test from "node:test"
import { installedArtifactSummary, verifyInstalledArtifact } from "../../runtime/native-artifact-policy.mjs"
import { installedLaunchReference, resolveInstalledLaunch, resolveManagedLaunch } from "../../runtime/access-launch.mjs"
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

function profileFixture(t, sharedBase) {
  const f = fixture(t, ["pi", "pi-profile-runtime", BRANDS[0][2], BRANDS[0][3]], sharedBase)
  // Include the actual audited extension modules, retaining the upstream entry.
  const directory = path.dirname(f.entry)
  for (const [source, target] of [["entry.mjs", "ordessa-profile.mjs"],
    ["server.mjs", "ordessa-profile-server.mjs"], ["configuration-query.mjs", "ordessa-configuration-query.mjs"]]) {
    fs.copyFileSync(fileURLToPath(new URL(`../../packaging/pi-profile/${source}`, import.meta.url)),
      path.join(directory, target))
  }
  f.entry = path.join(directory, "ordessa-profile.mjs")
  f.launch.args = [f.entry]
  f.options = { artifactBase: f.base, variant: "pi-profile" }
  const manifest = manifestFor(f)
  manifest.kind = "agentbox-pi-runtime-artifact"
  manifest.adapter.entry = `node_modules/${f.packageName}/dist/ordessa-profile.mjs`
  manifest.ordessaExtension = { id: "pi-profile", version: 1,
    configurationQuery: "_ordessa/session/configuration", instanceDirectoryRequired: true }
  f.manifest = manifest
  publishManifest(f, manifest)
  return f
}

for (const brand of BRANDS.slice(1)) {
  test(`${brand[0]}: native Profile assets require explicit selection and exact extension provenance`, t => {
    simulateRootAdministration(t)
    const f = fixture(t, brand)
    const manifest = manifestFor(f)
    const original = f.entry
    f.entry = path.join(path.dirname(original), 'ordessa-profile.mjs')
    fs.copyFileSync(new URL('../../packaging/native-profile/entry.mjs', import.meta.url), f.entry)
    f.launch.args = [f.entry]
    manifest.adapter.entry = `node_modules/${f.packageName}/dist/ordessa-profile.mjs`
    Object.assign(manifest, installedArtifactSummary(f.root))
    manifest.treeDigest = manifest.digest; delete manifest.digest
    manifest.extension = { id: `${f.harness}-profile`, version: 1,
      configurationQuery: '_ordessa/session/configuration', instanceDirectoryRequired: true,
      upstreamSourceDigest: 'sha256:' + (f.harness === 'codex'
        ? '9634b5457e44d55471d0969bcc5a2a1d4cbb83ba637eaf023d34d2e975fd7db8'
        : '36a33a984624541ea013c085f5bd1d982294cfe70beb42826752f62bdc538d64') }
    publishManifest(f, manifest)
    assert.throws(() => installedLaunchReference(f.harness, f.base), /ADAPTER_ARTIFACT_UNVERIFIED/)
    const options = { artifactBase: f.base, variant: 'native-profile' }
    assert.deepEqual(resolveInstalledLaunch(f.harness, f.launch, options),
      { ...f.launch, source: 'installed-artifact', version: f.version })
    const enhancedPlan = nativeServerPlan({ harnessId: f.harness,
      pluginRoot: '/opt/ordessa/harness-plugin', artifactRoot: f.base,
      nativeProfileHarnesses: [f.harness] })
    const flag = enhancedPlan.args.indexOf('--native-profile-harness')
    assert.equal(enhancedPlan.args[flag + 1], f.harness)
    assert.ok(enhancedPlan.args.includes(`--native-adapter-arg=${f.entry}`))
    assert.throws(() => nativeServerPlan({ harnessId: f.harness,
      pluginRoot: '/opt/ordessa/harness-plugin', artifactRoot: f.base }), /ADAPTER_ARTIFACT_UNVERIFIED/)
    for (const delta of [{ id: 'pi-profile' }, { version: 2 },
      { instanceDirectoryRequired: false }, { upstreamSourceDigest: 'invalid' },
      { upstreamSourceDigest: `sha256:${'b'.repeat(64)}` }, { extra: true }]) {
      publishManifest(f, { ...manifest, extension: { ...manifest.extension, ...delta } })
      assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, options), /ADAPTER_ARTIFACT_UNVERIFIED/)
    }
    publishManifest(f, { ...manifest, extension: undefined })
    assert.throws(() => resolveInstalledLaunch(f.harness, f.launch, options), /ADAPTER_ARTIFACT_UNVERIFIED/)
    publishManifest(f, { ...manifest, extension: undefined,
      adapter: { ...manifest.adapter, entry: `node_modules/${f.packageName}/dist/index.js` } })
    assert.deepEqual(installedLaunchReference(f.harness, f.base).args, [original])
  })
}

test('native Profile selection cannot select a different, duplicated or invalid brand', () => {
  for (const nativeProfileHarnesses of [true, ['pi'], ['claude-code'], ['codex', 'codex'], [{}]]) {
    assert.throws(() => nativeServerPlan({ harnessId: 'codex', pluginRoot: '/opt/ordessa/harness-plugin',
      artifactRoot: '/opt/ordessa/artifacts', nativeProfileHarnesses }), /NATIVE_PROFILE_SELECTION_INVALID/)
  }
})

test("Pi enhanced entry requires explicit variant; default and read-only routes do not adopt it", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t)
  assert.deepEqual(installedLaunchReference("pi", f.base, { variant: "pi-profile" }),
    { ...f.launch, source: "installed-artifact", version: "0.5.0" })
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, { artifactBase: f.base }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveManagedLaunch("pi", f.launch, { artifactBase: f.base,
    mountInfoText: "1 0 0:1 / / ro - ext4 /dev/test ro\n" }), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => installedLaunchReference("pi", f.base), /ADAPTER_ARTIFACT_UNVERIFIED/,
    "absence of default asset must not fall back to enhanced")
  const original = fixture(t, BRANDS[0], f.base)
  publishManifest(original)
  assert.deepEqual(installedLaunchReference("pi", f.base).args, [original.entry])
  assert.throws(() => resolveInstalledLaunch("pi", original.launch, f.options), /ADAPTER_LAUNCH_MISMATCH/)
  assert.throws(() => resolveInstalledLaunch("pi", { ...f.launch,
    args: [path.join(path.dirname(f.entry), "index.js")] }, f.options), /ADAPTER_LAUNCH_MISMATCH/)
})

test("enhanced manifest identity, extension metadata and entire tree remain authoritative", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t)
  const resolve = () => resolveInstalledLaunch("pi", f.launch, f.options)
  for (const change of [
    { kind: "agentbox-pi-profile-runtime-artifact" },
    { adapter: { ...f.manifest.adapter, entry: `node_modules/${f.packageName}/dist/index.js` } },
    { adapter: { ...f.manifest.adapter, entry: "../ordessa-profile.mjs" } },
    { adapter: { ...f.manifest.adapter, version: "9.9.9" } },
    { adapter: { ...f.manifest.adapter, package: BRANDS[1][2] } },
    { ordessaExtension: undefined }, { ordessaExtension: {} },
    ...[{ id: "other" }, { version: 2 }, { configurationQuery: "session/set_config_option" },
      { instanceDirectoryRequired: false }, { extra: true }].map(delta => (
      { ordessaExtension: { ...f.manifest.ordessaExtension, ...delta } })),
    { treeDigest: `sha256:${"0".repeat(64)}` }, { sourceLockDigest: "invalid" },
    { entries: f.manifest.entries + 1 }, { bytes: f.manifest.bytes + 1 },
  ]) {
    publishManifest(f, { ...f.manifest, ...change })
    assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, JSON.stringify(change))
  }
  publishManifest(f, f.manifest)
  for (const name of ["index.js", "ordessa-profile.mjs", "ordessa-profile-server.mjs", "ordessa-configuration-query.mjs"]) {
    const file = path.join(path.dirname(f.entry), name)
    const original = fs.readFileSync(file)
    fs.appendFileSync(file, "\n// changed module\n")
    assert.throws(resolve, /ADAPTER_ARTIFACT_UNVERIFIED/, name)
    fs.writeFileSync(file, original)
  }
  assert.equal(resolve().version, "0.5.0")
})

test("enhanced route rejects unsupported brands, unexpected argv and unknown variants", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t)
  for (const harness of ["codex", "claude-code", "claude", "unknown"]) {
    assert.throws(() => resolveInstalledLaunch(harness, f.launch, f.options), /ADAPTER_ROUTE_UNBOUND/)
    assert.throws(() => installedLaunchReference(harness, f.base, { variant: "pi-profile" }), /ADAPTER_ROUTE_UNBOUND/)
  }
  for (const variant of [null, true, "enhanced", "../pi-profile"]) {
    assert.throws(() => resolveInstalledLaunch("pi", f.launch, { ...f.options, variant }), /ADAPTER_ROUTE_UNBOUND/)
  }
  for (const launch of [{ ...f.launch, command: "/another/node" },
    { ...f.launch, args: [f.entry, "--anything"] }, { ...f.launch, args: [path.join(f.root, "arbitrary.mjs")] }]) {
    assert.throws(() => resolveInstalledLaunch("pi", launch, f.options), /ADAPTER_LAUNCH_MISMATCH/)
  }
  assert.throws(() => verifyInstalledArtifact({ artifactBase: f.base, artifact: "codex-runtime",
    packageName: BRANDS[1][2], version: BRANDS[1][3], variant: "pi-profile" }), /variant invalid/)
})

test("enhanced installed source retains every root ownership and mode guard", (t) => {
  const overrides = new Map()
  simulateRootAdministration(t, overrides)
  const f = profileFixture(t)
  for (const file of ["/", "/tmp", f.base, f.root, path.dirname(f.entry), f.entry, f.manifestPath,
    path.join(path.dirname(f.entry), "ordessa-configuration-query.mjs")]) {
    for (const change of [{ uid: 1000 }, { mode: fs.lstatSync(file).mode | 0o022 }]) {
      overrides.set(file, change)
      assert.throws(() => resolveInstalledLaunch("pi", f.launch, f.options), /ADAPTER_ARTIFACT_UNVERIFIED/, file)
      overrides.delete(file)
    }
  }
  for (const artifactBase of ["relative", `${f.base}/`, `${f.base}/../${path.basename(f.base)}`, `${f.base}\0`]) {
    assert.throws(() => installedLaunchReference("pi", artifactBase, { variant: "pi-profile" }), /ADAPTER_ARTIFACT_UNVERIFIED/)
  }
  const saved = `${f.entry}.real`
  fs.renameSync(f.entry, saved)
  fs.symlinkSync(saved, f.entry)
  assert.throws(() => resolveInstalledLaunch("pi", f.launch, f.options), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("actual user-owned enhanced tree is refused even with matching manifest and protected modes", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t)
  t.mock.restoreAll()
  fs.chmodSync(f.root, 0o555)
  try {
    assert.notEqual(fs.lstatSync(f.root).uid, 0)
    assert.throws(() => resolveInstalledLaunch("pi", f.launch, f.options), /ADAPTER_ARTIFACT_UNVERIFIED/)
  } finally { fs.chmodSync(f.root, 0o755) }
})

test("native enhanced plan is explicit and may replace only the selected Pi binding", (t) => {
  simulateRootAdministration(t)
  const f = profileFixture(t)
  const codex = fixture(t, BRANDS[1], f.base)
  publishManifest(codex)
  const plan = nativeServerPlan({ harnessIds: ["codex", "pi"], pluginRoot: "/opt/ordessa/harness-plugin",
    artifactRoot: f.base, piProfileBridge: true })
  assert.equal(plan.args.filter(arg => arg === "--native-pi-profile-bridge").length, 1)
  assert.ok(plan.args.includes(`--native-adapter-arg=${codex.entry}`))
  const index = plan.args.indexOf("--native-additional-adapters")
  assert.deepEqual(JSON.parse(plan.args[index + 1]), [{ harnessId: "pi", ...f.launch }])
  for (const piProfileBridge of ["true", null, 1, {}]) {
    assert.throws(() => nativeServerPlan({ harnessId: "pi", pluginRoot: "/opt/ordessa/harness-plugin",
      artifactRoot: f.base, piProfileBridge }), /NATIVE_PI_PROFILE_SELECTION_INVALID/)
  }
  assert.throws(() => nativeServerPlan({ harnessId: "codex", pluginRoot: "/opt/ordessa/harness-plugin",
    artifactRoot: f.base, piProfileBridge: true }), /NATIVE_PI_PROFILE_SELECTION_INVALID/)
  fs.appendFileSync(f.entry, "\n// changed\n")
  assert.throws(() => nativeServerPlan({ harnessId: "pi", pluginRoot: "/opt/ordessa/harness-plugin",
    artifactRoot: f.base, piProfileBridge: true }), /ADAPTER_ARTIFACT_UNVERIFIED/)
})

test("multi-brand launch preserves each binding's independently verified installation root", (t) => {
  simulateRootAdministration(t)
  const pi = profileFixture(t), codex = fixture(t, BRANDS[1])
  publishManifest(codex)
  const plan = nativeServerPlan({ harnessIds: ['pi', 'codex'],
    pluginRoot: '/opt/ordessa/harness-plugin', artifactRoot: codex.base,
    artifactRoots: { pi: pi.base }, piProfileBridge: true })
  assert.ok(plan.args.includes(`--native-adapter-arg=${pi.entry}`))
  assert.equal(plan.args[plan.args.indexOf('--native-installed-artifact-root') + 1], pi.base)
  assert.deepEqual(JSON.parse(plan.args[plan.args.indexOf('--native-additional-adapters') + 1]),
    [{ harnessId: 'codex', ...codex.launch, installedArtifactRoot: codex.base }])
  const reversed = nativeServerPlan({ harnessIds: ['codex', 'pi'],
    pluginRoot: '/opt/ordessa/harness-plugin', artifactRoot: codex.base,
    artifactRoots: { pi: pi.base }, piProfileBridge: true })
  assert.deepEqual(JSON.parse(reversed.args[reversed.args.indexOf('--native-additional-adapters') + 1]),
    [{ harnessId: 'pi', ...pi.launch, installedArtifactRoot: pi.base }])
  assert.throws(() => nativeServerPlan({ harnessIds: ['pi', 'codex'],
    pluginRoot: '/opt/ordessa/harness-plugin', artifactRoot: codex.base,
    artifactRoots: { pi: pi.base, unknown: codex.base }, piProfileBridge: true }), /NATIVE_ARTIFACT_ROOT_SELECTION_INVALID/)
})

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

for (const brand of BRANDS.slice(1)) {
  test(`${brand[0]}: enhanced access startup never accepts client-owned instance scope`, t => {
    const f = fixture(t, brand)
    const argv = ['--native', '--installed-artifact-root', f.base, '--native-profile-bridge']
    const connect = { op: 'connect', id: 1, harness: f.harness, launch: f.launch }
    for (const key of ['ORDESSA_NATIVE_INSTANCE_DIR', 'ORDESSA_CODEX_MANAGED_ACCOUNT_DIR', 'HOME', 'CODEX_HOME',
      'CLAUDE_CONFIG_DIR', 'XDG_CONFIG_HOME']) {
      const result = entryRun(argv, { ...connect,
        launch: { ...f.launch, environment: { [key]: '/tmp/foreign' } } })
      assert.equal(result.find(row => row.id === 1)?.error.code, 'ADAPTER_ENVIRONMENT_INVALID')
    }
    assert.equal(entryRun(argv, connect).find(row => row.id === 1)?.error.code, 'ADAPTER_LAUNCH_MISMATCH')
    assert.equal(entryRun(['--native', '--native-profile-bridge'], null)[0].error.code, 'SIDECAR_MODE_INVALID')
    assert.equal(entryRun(argv, { ...connect, harness: 'pi' }).find(row => row.id === 1)?.error.code,
      'ADAPTER_ROUTE_UNBOUND')
  })
}

test("enhanced startup selects exact route and refuses client instance overrides", (t) => {
  simulateRootAdministration(t) // Fixture manifest only; child process sees real user ownership.
  const f = profileFixture(t)
  const argv = ["--native", "--installed-artifact-root", f.base, "--pi-profile-bridge"]
  const connect = { op: "connect", id: 1, harness: "pi", launch: f.launch }
  // Actual user-owned asset: startup selector is accepted, origin still refuses.
  assert.equal(entryRun(argv, connect).find(row => row.id === 1)?.error.code, "ADAPTER_ARTIFACT_UNVERIFIED")
  for (const name of ["ORDESSA_PI_INSTANCE_DIR", "PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR"]) {
    const result = entryRun(argv, { ...connect, launch: { ...f.launch, environment: { [name]: "/tmp/foreign" } } })
    assert.equal(result.find(row => row.id === 1)?.error.code, "ADAPTER_ENVIRONMENT_INVALID")
  }
  assert.equal(entryRun(["--native", "--pi-profile-bridge"], null)[0].error.code, "SIDECAR_MODE_INVALID")
  assert.equal(entryRun(argv, { ...connect, harness: "codex" }).find(row => row.id === 1)?.error.code,
    "ADAPTER_ROUTE_UNBOUND")
})

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
