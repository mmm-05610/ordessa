/**
 * Builder gates for the Pi runtime artifact.
 *
 * The interesting failures are the ones that would otherwise ship: a closure
 * that is quietly incomplete, a package that disagrees with the lock, a tree
 * that is not a plain file tree, and an output path this build does not own.
 * Each of those is asserted against a small synthetic runtime root, so the
 * checks are exercised without touching the reviewed one.
 */
import { execFileSync } from "node:child_process"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import test from "node:test"
import assert from "node:assert/strict"

import { build, ENTRY, PROFILE_ENTRY } from "./build-pi-runtime-artifact.mjs"

const REPO = path.resolve(import.meta.dirname, "..", "..")

function packageAt(root, relative, manifest) {
  const directory = path.join(root, relative)
  mkdirSync(directory, { recursive: true })
  writeFileSync(path.join(directory, "package.json"), JSON.stringify(manifest))
  return directory
}

/** A miniature runtime root with the same shape the real one has. */
function fixtureRuntime({ name = "noop" } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), `pi-runtime-fixture-${name}-`))
  const lock = { lockfileVersion: 3, packages: {} }
  const add = (relative, manifest, files = { "index.js": "export default 1\n" }) => {
    const directory = packageAt(root, relative, manifest)
    for (const [file, content] of Object.entries(files)) {
      mkdirSync(path.dirname(path.join(directory, file)), { recursive: true })
      writeFileSync(path.join(directory, file), content)
    }
    lock.packages[relative] = { version: manifest.version }
    return directory
  }
  add("node_modules/@automatalabs/pi-acp", {
    name: "@automatalabs/pi-acp", version: "0.5.0",
    dependencies: { "@earendil-works/pi-coding-agent": "0.84.2" },
  }, { "index.js": "export default 1\n", "index.d.ts": "export default 1\n", "index.js.map": "{}\n" })
  add("node_modules/@earendil-works/pi-coding-agent", {
    name: "@earendil-works/pi-coding-agent", version: "0.84.2",
    dependencies: { "@earendil-works/pi-ai": "^0.84.2" },
    optionalDependencies: { "@mariozechner/clipboard": "0.3.9" },
  })
  add("node_modules/@earendil-works/pi-ai", {
    name: "@earendil-works/pi-ai", version: "0.84.2",
  })
  add("node_modules/@mariozechner/clipboard", {
    name: "@mariozechner/clipboard", version: "0.3.9", os: ["linux"], cpu: ["x64"],
  })
  add("node_modules/@mariozechner/clipboard-win32-x64-msvc", {
    name: "@mariozechner/clipboard-win32-x64-msvc", version: "0.3.9", os: ["win32"], cpu: ["x64"],
  })
  // Present in the tree, reachable only from codex, and therefore excluded.
  add("node_modules/@agentclientprotocol/codex-acp", {
    name: "@agentclientprotocol/codex-acp", version: "1.1.14",
    dependencies: { "@openai/codex": "0.147.0" },
  })
  add("node_modules/@openai/codex", { name: "@openai/codex", version: "0.147.0" })
  add("node_modules/.bin-fixture", { name: "bin-fixture", version: "1.0.0" })
  mkdirSync(path.join(root, "node_modules", "@automatalabs", "pi-acp", ".bin"), { recursive: true })
  symlinkSync("index.js", path.join(root, "node_modules", "@automatalabs", "pi-acp", ".bin", "pi-acp"))
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  return root
}

function outputFor(name) {
  return path.join(mkdtempSync(path.join(tmpdir(), `pi-runtime-out-${name}-`)), "artifact")
}

function expectBuildError(fn, code) {
  try {
    fn()
  } catch (error) {
    assert.equal(error.code, code, `expected ${code}, got ${error.code}: ${error.message}`)
    return error
  }
  assert.fail(`expected ${code}, but the build succeeded`)
}

test("builds the closure, excludes non-runtime files, and is deterministic", () => {
  const source = fixtureRuntime({ name: "happy" })
  const first = outputFor("happy-1")
  const second = outputFor("happy-2")
  const one = build({ output: first, source })
  const two = build({ output: second, source })
  assert.equal(one.treeDigest, two.treeDigest)
  assert.equal(one.entries, two.entries)
  assert.deepEqual(
    readFileSync(`${first}.manifest.json`, "utf8"),
    readFileSync(`${second}.manifest.json`, "utf8"),
    "two builds of one input must produce the same manifest",
  )
  assert.deepEqual(
    one.packages.map((item) => item.name).sort(),
    [
      "@automatalabs/pi-acp", "@earendil-works/pi-ai", "@earendil-works/pi-coding-agent",
      "@mariozechner/clipboard",
    ],
  )
  // Platform-filtered and codex-only packages never enter the Pi artifact.
  assert.ok(!one.packages.some((item) => item.name.includes("win32")))
  assert.ok(!one.packages.some((item) => item.name === "@openai/codex"))
  assert.deepEqual(one.excluded.codexOnlyPackages.sort(),
    ["node_modules/@agentclientprotocol/codex-acp", "node_modules/@openai/codex"])
  // Non-runtime files, npm's symlink farm and hidden lockfiles are dropped.
  const walk = (directory) => readFileSync
  for (const relative of ["index.d.ts", "index.js.map"]) {
    assert.throws(
      () => statSync(path.join(first, "node_modules/@automatalabs/pi-acp", relative)),
      /ENOENT/, `${relative} should have been excluded`,
    )
  }
  assert.throws(() => statSync(path.join(first, "node_modules/@automatalabs/pi-acp/.bin")), /ENOENT/)
  // The published tree is read-only and carries its owner marker.
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(statSync(path.join(first, "node_modules/@automatalabs/pi-acp/index.js")).mode & 0o777, 0o444)
  assert.match(readFileSync(path.join(first, ".agentbox-pi-runtime-artifact"), "utf8"), /r1/)
  void walk
})

test("a missing required dependency fails loudly", () => {
  const source = fixtureRuntime({ name: "missing" })
  rmSync(path.join(source, "node_modules/@earendil-works/pi-ai"), { recursive: true })
  expectBuildError(() => build({ output: outputFor("missing"), source }), "PI_CLOSURE_DEPENDENCY_MISSING")
})

test('Profile bridge is an explicit reproducible variant, not an upstream-entry replacement', () => {
  const source = fixtureRuntime({ name: 'profile' })
  const normal = build({ source, output: outputFor('normal') })
  const enhanced = build({ source, output: outputFor('profile') , profileBridge: true })
  const again = build({ source, output: outputFor('profile-again'), profileBridge: true })
  assert.equal(normal.adapter.entry, ENTRY)
  assert.equal(normal.ordessaExtension, undefined)
  assert.equal(enhanced.adapter.entry, PROFILE_ENTRY)
  assert.equal(enhanced.ordessaExtension.instanceDirectoryRequired, true)
  assert.notEqual(normal.treeDigest, enhanced.treeDigest)
  assert.equal(enhanced.treeDigest, again.treeDigest)
  assert.equal(readFileSync(path.join(enhanced.output, 'node_modules/@automatalabs/pi-acp/index.js'), 'utf8'),
    readFileSync(path.join(normal.output, 'node_modules/@automatalabs/pi-acp/index.js'), 'utf8'))
  for (const name of ['ordessa-profile.mjs', 'ordessa-profile-server.mjs', 'ordessa-configuration-query.mjs',
    'ordessa-configuration-operation.mjs', 'ordessa-creation.mjs'])
    assert.equal(statSync(path.join(enhanced.output, 'node_modules/@automatalabs/pi-acp/dist', name)).mode & 0o777, 0o444)
})

test("a package version that disagrees with the lock fails loudly", () => {
  const source = fixtureRuntime({ name: "drift" })
  const manifestPath = path.join(source, "node_modules/@earendil-works/pi-ai/package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "0.84.9"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  expectBuildError(() => build({ output: outputFor("drift"), source }), "PI_LOCK_VERSION_MISMATCH")
})

test("a package the lock does not record fails loudly", () => {
  const source = fixtureRuntime({ name: "unlocked" })
  const lockPath = path.join(source, "package-lock.json")
  const lock = JSON.parse(readFileSync(lockPath, "utf8"))
  delete lock.packages["node_modules/@earendil-works/pi-ai"]
  writeFileSync(lockPath, JSON.stringify(lock))
  expectBuildError(() => build({ output: outputFor("unlocked"), source }), "PI_LOCK_ENTRY_MISSING")
})

test("an adapter version other than the pinned one fails loudly", () => {
  const source = fixtureRuntime({ name: "adapter" })
  const manifestPath = path.join(source, "node_modules/@automatalabs/pi-acp/package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "0.6.0"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  const lockPath = path.join(source, "package-lock.json")
  const lock = JSON.parse(readFileSync(lockPath, "utf8"))
  lock.packages["node_modules/@automatalabs/pi-acp"].version = "0.6.0"
  writeFileSync(lockPath, JSON.stringify(lock))
  expectBuildError(() => build({ output: outputFor("adapter"), source }), "PI_ADAPTER_VERSION_MISMATCH")
})

test("a symlink anywhere in the closure fails loudly", () => {
  const source = fixtureRuntime({ name: "symlink" })
  symlinkSync("/etc/passwd", path.join(source, "node_modules/@earendil-works/pi-ai/escape"))
  expectBuildError(() => build({ output: outputFor("symlink"), source }), "PI_ARTIFACT_SHAPE_INVALID")
})

test("a special file in the closure fails loudly", () => {
  const source = fixtureRuntime({ name: "fifo" })
  const fifo = path.join(source, "node_modules/@earendil-works/pi-ai/pipe")
  execFileSync("mkfifo", [fifo])
  expectBuildError(() => build({ output: outputFor("fifo"), source }), "PI_ARTIFACT_SHAPE_INVALID")
})

test("a package reachable only from codex fails loudly", () => {
  const source = fixtureRuntime({ name: "unrelated" })
  const manifestPath = path.join(source, "node_modules/@automatalabs/pi-acp/package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.dependencies["@openai/codex"] = "0.147.0"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  expectBuildError(() => build({ output: outputFor("unrelated"), source }), "PI_ARTIFACT_UNRELATED_PACKAGE")
})

test("a tree beyond the artifact byte bound fails loudly", () => {
  const source = fixtureRuntime({ name: "bounds" })
  const oversized = path.join(source, "node_modules/@earendil-works/pi-ai/huge.bin")
  const handle = execFileSync("truncate", ["-s", String(1024 * 1024 * 1024 + 1), oversized])
  void handle
  expectBuildError(() => build({ output: outputFor("bounds"), source }), "PI_ARTIFACT_OUTSIDE_BOUNDS")
})

test("output policy refuses the repository, relative paths and user config roots", () => {
  const source = fixtureRuntime({ name: "policy" })
  expectBuildError(() => build({ output: "relative/artifact", source }), "PI_OUTPUT_NOT_ABSOLUTE")
  expectBuildError(() => build({ output: path.join(REPO, "artifact"), source }), "PI_OUTPUT_INSIDE_REPOSITORY")
  expectBuildError(() => build({ output: path.join(process.env.HOME, ".config", "pi"), source }), "PI_OUTPUT_RESERVED")
  expectBuildError(() => build({ output: "/", source }), "PI_OUTPUT_UNSAFE")
})

test("an unmarked output is never deleted, and an owned one needs --replace", () => {
  const source = fixtureRuntime({ name: "target" })
  const output = outputFor("target")
  mkdirSync(output)
  const keep = path.join(output, "user-file")
  writeFileSync(keep, "must survive")
  expectBuildError(() => build({ output, source }), "PI_OUTPUT_NOT_OWNED")
  assert.equal(readFileSync(keep, "utf8"), "must survive")

  rmSync(keep)
  build({ output, source })
  expectBuildError(() => build({ output, source }), "PI_OUTPUT_EXISTS")
  const rebuilt = build({ output, source, replace: true })
  assert.match(rebuilt.treeDigest, /^sha256:[0-9a-f]{64}$/)
})
