/**
 * Builder gates for the dsh runtime artifact.
 *
 * The failures worth catching before they ship: a closure that is quietly
 * incomplete (the adapter spawning something that is not in the tree), a
 * package that disagrees with the lock, a version other than the pinned one, a
 * symlink or special file inside the copy, a source root that is not an
 * installed-package set, and an output path this build does not own. Each is
 * asserted against a small synthetic installed-package root, so the checks run
 * without touching the reviewed one; the last test builds the real locked
 * closure and proves the artifact identity, determinism and self-containment.
 *
 * The synthetic roots are only ever the *input* to the builder. The digest is
 * never stubbed: every build here goes through the reviewed Python
 * `runtime_artifact_tree_summary` the builder calls, so a green run is a real
 * digest, not a stand-in.
 */
import { execFileSync } from "node:child_process"
import {
  chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync,
  symlinkSync, writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import test, { after } from "node:test"
import assert from "node:assert/strict"

import {
  ADAPTER_PACKAGE, ADAPTER_VERSION, ENTRY, EXCLUDED_ADAPTERS, MARKER_CONTENT,
  MARKER_NAME, build, isRuntimeFile, resolvePackage,
} from "./build-dsh-runtime-artifact.mjs"

const REPO = path.resolve(import.meta.dirname, "..", "..")
// The reviewed runtime root: the same path the builder resolves as its default.
const DEFAULT_SOURCE = path.join(REPO, "packaging", "dsh")
// The real locked closure only exists after `npm ci` in packaging/dsh; node_modules
// is not part of the source tree, so that test skips rather than fails.
const HAS_LOCKED_SOURCE = existsSync(path.join(DEFAULT_SOURCE, "node_modules", ADAPTER_PACKAGE, "package.json"))

// Every fixture root and every scratch output is temporary state; none of it
// survives the file, including the read-only published trees.
const fixtureRoots = []
// Symlinks are skipped, never followed: a fixture that plants one to prove the
// builder refuses it must not have its cleanup chmod a file outside the tree.
const makeWritable = (directory) => {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const location = path.join(directory, entry.name)
    if (entry.isSymbolicLink()) continue
    if (entry.isDirectory()) makeWritable(location)
    else chmodSync(location, 0o644)
  }
  chmodSync(directory, 0o755)
}
after(() => {
  for (const root of fixtureRoots) {
    try {
      makeWritable(root)
      rmSync(root, { recursive: true, force: true })
    } catch {
      // A leftover temp directory is noise, not a test failure.
    }
  }
})

function packageAt(root, relative, manifest, files = {}, lock = null) {
  const directory = path.join(root, relative)
  mkdirSync(directory, { recursive: true })
  writeFileSync(path.join(directory, "package.json"), JSON.stringify(manifest))
  for (const [file, content] of Object.entries(files)) {
    mkdirSync(path.dirname(path.join(directory, file)), { recursive: true })
    writeFileSync(path.join(directory, file), content)
  }
  if (lock && relative) lock.packages[relative] = { version: manifest.version }
  return directory
}

/**
 * A miniature installed-package root with the same shape the real one has: an
 * entry package that is the pinned adapter, a declared dependency that must
 * travel with it, an optional dependency that is not installed (so the build
 * records it as skipped rather than inventing it), and a lock that records
 * exactly what is on disk.
 */
function fixtureSource({ name = "noop" } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), `dsh-source-${name}-`))
  fixtureRoots.push(root)
  const lock = { lockfileVersion: 3, packages: {} }
  packageAt(root, `node_modules/${ADAPTER_PACKAGE}`, {
    name: ADAPTER_PACKAGE, version: ADAPTER_VERSION,
    bin: { dsh: "lib/bin.js" },
    dependencies: { "@agentclientprotocol/sdk": "^1.4.0", "ms": "^2.1.3" },
    optionalDependencies: { sharp: "^0.33.0" },
  }, {
    "lib/bin.js": "#!/usr/bin/env node\nimport './main.js'\n",
    "lib/main.js": "export const run = () => 0\n",
    "lib/main.d.ts": "export declare const run: () => number\n",
    "lib/main.js.map": "{}\n",
    "README.md": "# dsh\n",
    "docs/guide.md": "guide\n",
  }, lock)
  packageAt(root, "node_modules/@agentclientprotocol/sdk", {
    name: "@agentclientprotocol/sdk", version: "1.4.0",
  }, { "dist/index.js": "export default 1\n" }, lock)
  packageAt(root, "node_modules/ms", {
    name: "ms", version: "2.1.3",
  }, { "index.js": "module.exports = 1\n", "package-lock.json": "{}\n" }, lock)
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  return { root, lock }
}

/** A scratch output outside the repository, removed with the test that made it. */
function scratchFor(t, name) {
  const parent = mkdtempSync(path.join(tmpdir(), `dsh-out-${name}-`))
  fixtureRoots.push(parent)
  t.after(() => {
    if (!existsSync(parent)) return
    try {
      makeWritable(parent)
      rmSync(parent, { recursive: true, force: true })
    } catch {
      // The final sweep after the file handles anything left behind.
    }
  })
  return path.join(parent, "artifact")
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

test("builds the locked closure from the source root, and is deterministic", (t) => {
  const { root, lock } = fixtureSource({ name: "happy" })
  const first = scratchFor(t, "happy-1")
  const second = scratchFor(t, "happy-2")
  const one = build({ output: first, source: root })
  const two = build({ output: second, source: root })
  assert.equal(one.treeDigest, two.treeDigest)
  assert.equal(one.entries, two.entries)
  assert.equal(one.bytes, two.bytes)
  assert.deepEqual(
    readFileSync(`${first}.manifest.json`, "utf8"),
    readFileSync(`${second}.manifest.json`, "utf8"),
    "two builds of one input must produce the same manifest",
  )
  // The manifest is a v1 document with a digest the reviewed implementation
  // produced, and it names the pinned entry and lock.
  assert.equal(one.schemaVersion, 1)
  assert.equal(one.kind, "agentbox-dsh-runtime-artifact")
  assert.match(one.treeDigest, /^sha256:[0-9a-f]{64}$/)
  assert.match(one.sourceLockDigest, /^sha256:[0-9a-f]{64}$/)
  assert.deepEqual(one.adapter, {
    package: ADAPTER_PACKAGE, version: ADAPTER_VERSION, entry: ENTRY,
  })
  // Exactly the closure, no more: the declared dependency travels, the optional
  // one is recorded as not installed instead of being invented.
  assert.deepEqual(
    one.packages.map((item) => `${item.name}@${item.version}`).sort(),
    ["@agentclientprotocol/sdk@1.4.0", "@deepseek-ai/dsh@0.1.5-rc.1", "ms@2.1.3"],
  )
  assert.deepEqual(one.optionalSkipped, [{ by: ADAPTER_PACKAGE, name: "sharp", reason: "not-installed" }])
  // Every packaged path is recorded in the lock, with the version on disk.
  for (const item of one.packages) {
    assert.equal(lock.packages[item.path].version, item.version)
  }
  // The entry point and the runtime files are where the deployment expects them;
  // the excluded families of file are not carried.
  assert.equal(statSync(path.join(first, ENTRY)).isFile(), true)
  for (const relative of ["lib/main.d.ts", "lib/main.js.map", "README.md", "docs/guide.md"]) {
    assert.throws(() => statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, relative)), /ENOENT/,
      `${relative} should have been excluded`)
  }
  assert.throws(() => statSync(path.join(first, "node_modules/ms/package-lock.json")), /ENOENT/,
    "a nested lockfile is not a runtime file")
  assert.deepEqual(one.excluded.directories, [".bin", "docs", "examples"])
  assert.deepEqual(one.excluded.rules, ["d.ts", "source-maps", "typescript-sources", "documentation"])
  assert.ok(one.excluded.skippedFiles > 0, "the excluded files must be counted, not silently dropped")
  // Read-only publication and the owner marker.
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(statSync(path.join(first, ENTRY)).mode & 0o777, 0o444)
  assert.equal(readFileSync(path.join(first, MARKER_NAME), "utf8"), MARKER_CONTENT)
})

test("a package version that disagrees with the lock fails loudly", (t) => {
  const { root } = fixtureSource({ name: "drift" })
  const manifestPath = path.join(root, "node_modules/ms/package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "2.1.9"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  expectBuildError(() => build({ output: scratchFor(t, "drift"), source: root }),
    "DSH_LOCK_VERSION_MISMATCH")
})

test("a package the lock does not record fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "unrecorded" })
  delete lock.packages["node_modules/ms"]
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(() => build({ output: scratchFor(t, "unrecorded"), source: root }),
    "DSH_LOCK_ENTRY_MISSING")
})

test("an adapter version other than the pinned one fails loudly", (t) => {
  const { root } = fixtureSource({ name: "version" })
  const manifestPath = path.join(root, "node_modules", ADAPTER_PACKAGE, "package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "0.1.6-rc.1"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  // The lock follows the disk, so the refusal is about the pin and not the lock.
  const lock = JSON.parse(readFileSync(path.join(root, "package-lock.json"), "utf8"))
  lock.packages[`node_modules/${ADAPTER_PACKAGE}`].version = "0.1.6-rc.1"
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(() => build({ output: scratchFor(t, "version"), source: root }),
    "DSH_ADAPTER_VERSION_MISMATCH")
})

test("a missing required dependency fails loudly", (t) => {
  const { root } = fixtureSource({ name: "missing" })
  rmSync(path.join(root, "node_modules/@agentclientprotocol/sdk"), { recursive: true })
  expectBuildError(() => build({ output: scratchFor(t, "missing"), source: root }),
    "DSH_CLOSURE_DEPENDENCY_MISSING")
})

test("a source root without the installed adapter fails loudly", (t) => {
  const { root } = fixtureSource({ name: "noentry" })
  rmSync(path.join(root, "node_modules", ADAPTER_PACKAGE), { recursive: true })
  expectBuildError(() => build({ output: scratchFor(t, "noentry"), source: root }),
    "DSH_CLOSURE_ENTRY_MISSING")
})

test("an absent source is refused with a clear error, not an empty artifact", (t) => {
  const { root } = fixtureSource({ name: "absent" })
  const missingDirectory = path.join(root, "no-such-root")
  const noLock = path.join(root, "no-lock")
  mkdirSync(noLock, { recursive: true })
  for (const [label, source] of [["a directory that does not exist", missingDirectory],
    ["a directory with no package-lock.json", noLock]]) {
    const output = scratchFor(t, "absent")
    const error = expectBuildError(() => build({ output, source }), "DSH_SOURCE_INVALID")
    assert.match(error.message, /has no package-lock\.json/,
      `${label} must be refused with the reason`)
    assert.ok(error.message.includes(source), `${label} must name the source it refused`)
    // A refusal leaves nothing behind: no tree, no manifest, no staging
    // directory that a later reader could mistake for an artifact.
    assert.equal(existsSync(output), false, `${label} must not publish a tree`)
    assert.equal(existsSync(`${output}.manifest.json`), false, `${label} must not write a manifest`)
    assert.deepEqual(
      readdirSync(path.dirname(output)).filter((name) => name.includes(".building-")),
      [], `${label} must not leave a staging directory behind`)
  }
})

test("another family's adapter installed in the dsh root fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "foreign" })
  const foreign = EXCLUDED_ADAPTERS[0]
  packageAt(root, `node_modules/${foreign}`, { name: foreign, version: "0.5.0" },
    { "index.js": "export default 1\n" }, lock)
  expectBuildError(() => build({ output: scratchFor(t, "foreign"), source: root }),
    "DSH_ARTIFACT_UNRELATED_PACKAGE")
})

test("a symlink in the closure fails loudly", (t) => {
  const { root } = fixtureSource({ name: "symlink" })
  symlinkSync("/etc/passwd", path.join(root, "node_modules/ms/escape.js"))
  expectBuildError(() => build({ output: scratchFor(t, "symlink"), source: root }),
    "DSH_ARTIFACT_SHAPE_INVALID")
})

test("a special file in the closure fails loudly", (t) => {
  const { root } = fixtureSource({ name: "fifo" })
  execFileSync("mkfifo", [path.join(root, "node_modules/ms/pipe")])
  expectBuildError(() => build({ output: scratchFor(t, "fifo"), source: root }),
    "DSH_ARTIFACT_SHAPE_INVALID")
})

test("a lock without a package map fails loudly", (t) => {
  const { root } = fixtureSource({ name: "nolock" })
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify({ lockfileVersion: 3 }))
  expectBuildError(() => build({ output: scratchFor(t, "nolock"), source: root }), "DSH_LOCK_INVALID")
})

test("output policy refuses the repository, relative paths and user config roots", (t) => {
  const { root } = fixtureSource({ name: "policy" })
  expectBuildError(() => build({ output: "relative/artifact", source: root }), "DSH_OUTPUT_NOT_ABSOLUTE")
  expectBuildError(() => build({ output: path.join(REPO, "artifact"), source: root }),
    "DSH_OUTPUT_INSIDE_REPOSITORY")
  // `REPO` here is plugins/harness, the root the builders themselves resolve, so
  // the refusal covers a scratch directory anywhere inside the plugin as well.
  expectBuildError(() => build({ output: path.join(REPO, "packaging", "dsh", "artifact"), source: root }),
    "DSH_OUTPUT_INSIDE_REPOSITORY")
  expectBuildError(() => build({ output: path.join(process.env.HOME, ".agentbox", "artifact"), source: root }),
    "DSH_OUTPUT_RESERVED")
  expectBuildError(() => build({ output: "/", source: root }), "DSH_OUTPUT_UNSAFE")
})

test("an unmarked output is never deleted, and an owned one needs --replace", (t) => {
  const { root } = fixtureSource({ name: "target" })
  const output = scratchFor(t, "target")
  mkdirSync(output)
  const keep = path.join(output, "user-file")
  writeFileSync(keep, "must survive")
  expectBuildError(() => build({ output, source: root }), "DSH_OUTPUT_NOT_OWNED")
  assert.equal(readFileSync(keep, "utf8"), "must survive")

  rmSync(keep)
  const built = build({ output, source: root })
  expectBuildError(() => build({ output, source: root }), "DSH_OUTPUT_EXISTS")
  const rebuilt = build({ output, source: root, replace: true })
  assert.equal(rebuilt.treeDigest, built.treeDigest, "a rebuild must be the same artifact")
  assert.equal(statSync(output).mode & 0o777, 0o555)
})

test("the copy filter keeps what a running adapter loads", () => {
  for (const kept of ["lib/bin.js", "package.json", "bin/kilo", "lib/main.mjs",
    "lib/main.js.map.map", "node_modules/a/node_modules/b/index.js"]) {
    assert.equal(isRuntimeFile(kept), true, `${kept} is a runtime file`)
  }
  // Declarations and source maps, every TypeScript source extension (a `.d.mts`
  // declaration is a TypeScript source by that rule), documentation, npm's bin
  // farm and lockfiles are all dropped.
  for (const dropped of ["lib/main.d.ts", "lib/main.js.map", "lib/main.mjs.map", "dist/index.d.mts",
    "README.md", "guide.markdown", "lib/main.ts", "lib/main.mts", "lib/main.cts", "lib/main.tsx",
    "docs/guide.md", "examples/demo.js", ".bin/kilo", "a/.bin/kilo", "package-lock.json",
    "a/b/package-lock.json", "a/b/.package-lock.json"]) {
    assert.equal(isRuntimeFile(dropped), false, `${dropped} is not a runtime file`)
  }
})

test("the package lookup is bounded to the runtime root it is given", () => {
  const { root } = fixtureSource({ name: "lookup" })
  assert.equal(resolvePackage(ADAPTER_PACKAGE, root, root),
    path.join(root, "node_modules", ADAPTER_PACKAGE))
  // A lookup that would walk out of the runtime root reports nothing rather
  // than reaching into an outer installation.
  assert.equal(resolvePackage("@agentclientprotocol/sdk", path.join(root, "node_modules", "ms"), root),
    path.join(root, "node_modules", "@agentclientprotocol/sdk"))
  assert.equal(resolvePackage("not-installed", root, root), null)
})

test("the real locked dsh closure builds, is deterministic and is self-contained", {
  skip: HAS_LOCKED_SOURCE ? false : "run `npm ci` in plugins/harness/packaging/dsh first",
}, (t) => {
  const first = scratchFor(t, "real-1")
  const second = scratchFor(t, "real-2")
  const one = build({ output: first, source: DEFAULT_SOURCE })
  const two = build({ output: second, source: DEFAULT_SOURCE })
  assert.equal(one.treeDigest, two.treeDigest)
  assert.equal(one.entries, two.entries)
  assert.equal(one.bytes, two.bytes)
  assert.equal(one.sourceLockDigest, two.sourceLockDigest)
  assert.deepEqual(
    readFileSync(`${first}.manifest.json`, "utf8"),
    readFileSync(`${second}.manifest.json`, "utf8"),
    "two builds of the locked closure must produce the same manifest",
  )
  assert.equal(one.schemaVersion, 1)
  assert.match(one.treeDigest, /^sha256:[0-9a-f]{64}$/)
  assert.match(one.sourceLockDigest, /^sha256:[0-9a-f]{64}$/)
  assert.equal(one.adapter.package, ADAPTER_PACKAGE)
  assert.equal(one.adapter.version, ADAPTER_VERSION)
  assert.ok(one.entries > 0 && one.bytes > 0)
  // The pins the builder exists to hold.
  assert.equal(one.packages.find((item) => item.name === ADAPTER_PACKAGE).version, ADAPTER_VERSION)
  const sdk = one.packages.filter((item) => item.name === "@agentclientprotocol/sdk")
  assert.equal(sdk.length, 1)
  assert.equal(sdk[0].version, "1.4.0", "dsh needs ACP SDK 1.4.x, not the 1.3.0 the shared root pins")
  for (const foreign of EXCLUDED_ADAPTERS) {
    assert.ok(!one.packages.some((item) => item.name === foreign), `${foreign} must not be packaged`)
  }
  // The artifact carries the entry point the deployment spawns, and nothing of
  // another family's root.
  assert.equal(statSync(path.join(first, ENTRY)).isFile(), true)
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(readFileSync(path.join(first, MARKER_NAME), "utf8"), MARKER_CONTENT)
  for (const relative of ["README.md"]) {
    assert.throws(() => statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, relative)), /ENOENT/,
      `${relative} should have been excluded`)
  }
})
