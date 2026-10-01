/**
 * Builder gates for the kilo runtime artifact.
 *
 * The failures worth catching before they ship: a closure that is quietly
 * incomplete (a launcher that resolves no platform package), the ~200MB AVX2
 * variant riding along next to the baseline one it duplicates, a package that
 * disagrees with the lock, a version other than the pinned one, a native binary
 * published without its execute bit, a symlink or special file inside the copy,
 * a source root that is not an installed-package set, and an output path this
 * build does not own. Each is asserted against a small synthetic
 * installed-package root, so the checks run without touching the reviewed one;
 * the last test builds the real locked closure and proves the artifact identity,
 * determinism and self-containment.
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
  ADAPTER_PACKAGE, ADAPTER_VERSION, ENTRY, EXECUTABLE_FILES, EXCLUDED_ADAPTERS,
  EXCLUDED_VARIANTS, MARKER_CONTENT, MARKER_NAME, build, isRuntimeFile, resolvePackage,
} from "./build-kilo-runtime-artifact.mjs"

const REPO = path.resolve(import.meta.dirname, "..", "..")
// The reviewed runtime root: the same path the builder resolves as its default.
const DEFAULT_SOURCE = path.join(REPO, "packaging", "kilo")
// The real locked closure only exists after `npm ci` in packaging/kilo;
// node_modules is not part of the source tree, so that test skips rather than
// fails.
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
// The variant the executable set is published for, derived from the builder's
// own path so the fixture cannot drift from it.
const BASELINE = [...EXECUTABLE_FILES][0].split("/").slice(1, 3).join("/")
const PLATFORM_PACKAGE = path.join("node_modules", BASELINE)

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
 * A miniature installed-package root with the same shape the real one has: a
 * launcher that declares twelve platform variants as optional dependencies and
 * has no runtime dependencies at all, of which the closure must take the
 * platform package for the build host and record the rest as skipped.
 *
 * The platform package carries the host's own os/cpu, so the fixture resolves
 * the same variant on the machine that runs the test, and the excluded variant
 * is installed on purpose: the exclusion must be structural, not a walk-away
 * that only works when the package happens to be absent.
 */
function fixtureSource({ name = "noop" } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), `kilo-source-${name}-`))
  fixtureRoots.push(root)
  const lock = { lockfileVersion: 3, packages: {} }
  const optionalDependencies = {
    [BASELINE]: ADAPTER_VERSION,
    [EXCLUDED_VARIANTS[0]]: ADAPTER_VERSION,
    "@kilocode/cli-win32-x64": ADAPTER_VERSION,
    "@kilocode/cli-darwin-arm64": ADAPTER_VERSION,
  }
  packageAt(root, `node_modules/${ADAPTER_PACKAGE}`, {
    name: ADAPTER_PACKAGE, version: ADAPTER_VERSION,
    os: ["darwin", "linux", "win32"], cpu: ["arm64", "x64"],
    bin: { kilo: "bin/kilo", kilocode: "bin/kilo" },
    optionalDependencies,
  }, {
    "bin/kilo": "#!/usr/bin/env node\nimport { findBinary } from '../lib/find.js'\n",
    "lib/find.js": "export const findBinary = () => null\n",
    "lib/find.d.ts": "export declare const findBinary: () => string | null\n",
    "lib/find.js.map": "{}\n",
    "README.md": "# kilo\n",
    "postinstall.mjs": "export default 0\n",
  }, lock)
  // The matching platform package, published with the execute bit the build
  // must preserve.
  packageAt(root, PLATFORM_PACKAGE, {
    name: BASELINE, version: ADAPTER_VERSION, os: [process.platform], cpu: [process.arch],
  }, {
    "bin/kilo": "#!/bin/true\nnative kilo\n",
    "bin/bwrap": "#!/bin/true\nbwrap\n",
    "bin/kilo-sandbox-seccomp": "#!/bin/true\nseccomp\n",
    "bin/console": "#!/bin/true\nconsole\n",
    "LICENSE": "MIT\n",
  }, lock)
  for (const platform of EXCLUDED_VARIANTS) {
    packageAt(root, `node_modules/${platform}`, {
      name: platform, version: ADAPTER_VERSION, os: [process.platform], cpu: [process.arch],
    }, { "bin/kilo": "duplicated avx2 payload\n" }, lock)
  }
  // A platform package for another target: installed, in the lock, and never
  // selected because the closure filters on os/cpu.
  packageAt(root, "node_modules/@kilocode/cli-somewhere-else-x64", {
    name: "@kilocode/cli-somewhere-else-x64", version: ADAPTER_VERSION,
    os: ["not-a-real-platform"], cpu: ["not-a-real-cpu"],
  }, { "bin/kilo": "elsewhere\n" }, lock)
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  return { root, lock }
}

/** A scratch output outside the repository, removed with the test that made it. */
function scratchFor(t, name) {
  const parent = mkdtempSync(path.join(tmpdir(), `kilo-out-${name}-`))
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

test("builds the closure, keeps the native payload, and is deterministic", (t) => {
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
  assert.equal(one.kind, "agentbox-kilo-runtime-artifact")
  assert.match(one.treeDigest, /^sha256:[0-9a-f]{64}$/)
  assert.match(one.sourceLockDigest, /^sha256:[0-9a-f]{64}$/)
  assert.deepEqual(one.adapter, {
    package: ADAPTER_PACKAGE, version: ADAPTER_VERSION, entry: ENTRY,
  })
  // Exactly the launcher and the platform package for this host.
  assert.deepEqual(
    one.packages.map((item) => `${item.name}@${item.version}`).sort(),
    [`@kilocode/cli@${ADAPTER_VERSION}`, `${BASELINE}@${ADAPTER_VERSION}`].sort(),
  )
  for (const item of one.packages) {
    assert.equal(lock.packages[item.path].version, item.version)
  }
  // The excluded AVX2 variant is dropped by rule, and reported as such even
  // though it was installed; the other targets are dropped by the platform filter.
  for (const excluded of EXCLUDED_VARIANTS) {
    assert.ok(!one.packages.some((item) => item.name === excluded), `${excluded} must not be packaged`)
  }
  assert.ok(one.optionalSkipped.some((item) => item.name === EXCLUDED_VARIANTS[0]
    && item.reason === "excluded-variant"))
  assert.ok(one.optionalSkipped.some((item) => item.name === "@kilocode/cli-darwin-arm64"
    && item.reason === "not-installed"))
  // The native binaries are spawned directly out of a read-only tree, so the
  // execute bit is part of the published artifact; everything else is read-only.
  for (const relative of EXECUTABLE_FILES) {
    assert.equal(statSync(path.join(first, relative)).mode & 0o777, 0o555,
      `${relative} must stay executable`)
  }
  assert.equal(statSync(path.join(first, "node_modules", BASELINE, "LICENSE")).mode & 0o777, 0o444)
  assert.equal(statSync(path.join(first, ENTRY)).mode & 0o777, 0o444)
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(readFileSync(path.join(first, MARKER_NAME), "utf8"), MARKER_CONTENT)
  // Non-runtime files and the other platform's payload are not carried.
  for (const relative of ["lib/find.d.ts", "lib/find.js.map", "README.md"]) {
    assert.throws(() => statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, relative)), /ENOENT/,
      `${relative} should have been excluded`)
  }
  assert.throws(
    () => statSync(path.join(first, "node_modules", EXCLUDED_VARIANTS[0], "bin/kilo")), /ENOENT/,
    "the excluded variant must not travel")
  assert.throws(
    () => statSync(path.join(first, "node_modules/@kilocode/cli-somewhere-else-x64")), /ENOENT/,
    "another target's platform package must not travel")
})

test("a package version that disagrees with the lock fails loudly", (t) => {
  const { root } = fixtureSource({ name: "drift" })
  const manifestPath = path.join(root, PLATFORM_PACKAGE, "package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "7.7.3"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  expectBuildError(() => build({ output: scratchFor(t, "drift"), source: root }),
    "KILO_LOCK_VERSION_MISMATCH")
})

test("a package the lock does not record fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "unrecorded" })
  delete lock.packages[PLATFORM_PACKAGE]
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(() => build({ output: scratchFor(t, "unrecorded"), source: root }),
    "KILO_LOCK_ENTRY_MISSING")
})

test("a launcher version other than the pinned one fails loudly", (t) => {
  const { root } = fixtureSource({ name: "version" })
  const manifestPath = path.join(root, "node_modules", ADAPTER_PACKAGE, "package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "7.7.3"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  // The lock follows the disk, so the refusal is about the pin and not the lock.
  const lock = JSON.parse(readFileSync(path.join(root, "package-lock.json"), "utf8"))
  lock.packages[`node_modules/${ADAPTER_PACKAGE}`].version = "7.7.3"
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(() => build({ output: scratchFor(t, "version"), source: root }),
    "KILO_ADAPTER_VERSION_MISMATCH")
})

test("a missing platform package is recorded as skipped, not shipped as an empty payload", (t) => {
  const { root } = fixtureSource({ name: "noplatform" })
  rmSync(path.join(root, PLATFORM_PACKAGE), { recursive: true })
  // The launcher has no runtime dependency on it, so the build still succeeds
  // without the payload - which is exactly the hole worth naming here.
  const built = build({ output: scratchFor(t, "noplatform"), source: root })
  assert.deepEqual(built.packages.map((item) => item.name), [ADAPTER_PACKAGE])
  assert.ok(built.optionalSkipped.some((item) => item.name === BASELINE
    && item.reason === "not-installed"))
  // The manifest is honest about it, and the entry the deployment spawns is the
  // launcher that resolves the binary at run time.
  assert.equal(statSync(path.join(built.output, ENTRY)).isFile(), true)
})

test("a source root without the installed launcher fails loudly", (t) => {
  const { root } = fixtureSource({ name: "noentry" })
  rmSync(path.join(root, "node_modules", ADAPTER_PACKAGE), { recursive: true })
  expectBuildError(() => build({ output: scratchFor(t, "noentry"), source: root }),
    "KILO_CLOSURE_ENTRY_MISSING")
})

test("an absent source is refused with a clear error, not an empty artifact", (t) => {
  const { root } = fixtureSource({ name: "absent" })
  const missingDirectory = path.join(root, "no-such-root")
  const noLock = path.join(root, "no-lock")
  mkdirSync(noLock, { recursive: true })
  for (const [label, source] of [["a directory that does not exist", missingDirectory],
    ["a directory with no package-lock.json", noLock]]) {
    const output = scratchFor(t, "absent")
    const error = expectBuildError(() => build({ output, source }), "KILO_SOURCE_INVALID")
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

test("another family's adapter installed in the kilo root fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "foreign" })
  const foreign = EXCLUDED_ADAPTERS[0]
  packageAt(root, `node_modules/${foreign}`, { name: foreign, version: "0.5.0" },
    { "index.js": "export default 1\n" }, lock)
  expectBuildError(() => build({ output: scratchFor(t, "foreign"), source: root }),
    "KILO_ARTIFACT_UNRELATED_PACKAGE")
})

test("a symlink in the closure fails loudly", (t) => {
  const { root } = fixtureSource({ name: "symlink" })
  symlinkSync("/etc/passwd", path.join(root, PLATFORM_PACKAGE, "escape"))
  expectBuildError(() => build({ output: scratchFor(t, "symlink"), source: root }),
    "KILO_ARTIFACT_SHAPE_INVALID")
})

test("a special file in the closure fails loudly", (t) => {
  const { root } = fixtureSource({ name: "fifo" })
  execFileSync("mkfifo", [path.join(root, PLATFORM_PACKAGE, "pipe")])
  expectBuildError(() => build({ output: scratchFor(t, "fifo"), source: root }),
    "KILO_ARTIFACT_SHAPE_INVALID")
})

test("a lock without a package map fails loudly", (t) => {
  const { root } = fixtureSource({ name: "nolock" })
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify({ lockfileVersion: 3 }))
  expectBuildError(() => build({ output: scratchFor(t, "nolock"), source: root }), "KILO_LOCK_INVALID")
})

test("output policy refuses the repository, relative paths and user config roots", (t) => {
  const { root } = fixtureSource({ name: "policy" })
  expectBuildError(() => build({ output: "relative/artifact", source: root }), "KILO_OUTPUT_NOT_ABSOLUTE")
  expectBuildError(() => build({ output: path.join(REPO, "artifact"), source: root }),
    "KILO_OUTPUT_INSIDE_REPOSITORY")
  // `REPO` here is plugins/harness, the root the builders themselves resolve, so
  // the refusal covers a scratch directory anywhere inside the plugin as well.
  expectBuildError(() => build({ output: path.join(REPO, "packaging", "kilo", "artifact"), source: root }),
    "KILO_OUTPUT_INSIDE_REPOSITORY")
  expectBuildError(() => build({ output: path.join(process.env.HOME, ".agentbox", "artifact"), source: root }),
    "KILO_OUTPUT_RESERVED")
  expectBuildError(() => build({ output: "/", source: root }), "KILO_OUTPUT_UNSAFE")
})

test("an unmarked output is never deleted, and an owned one needs --replace", (t) => {
  const { root } = fixtureSource({ name: "target" })
  const output = scratchFor(t, "target")
  mkdirSync(output)
  const keep = path.join(output, "user-file")
  writeFileSync(keep, "must survive")
  expectBuildError(() => build({ output, source: root }), "KILO_OUTPUT_NOT_OWNED")
  assert.equal(readFileSync(keep, "utf8"), "must survive")

  rmSync(keep)
  const built = build({ output, source: root })
  expectBuildError(() => build({ output, source: root }), "KILO_OUTPUT_EXISTS")
  const rebuilt = build({ output, source: root, replace: true })
  assert.equal(rebuilt.treeDigest, built.treeDigest, "a rebuild must be the same artifact")
  assert.equal(statSync(path.join(output, EXECUTABLE_FILES.values().next().value)).mode & 0o777, 0o555,
    "a rebuild must keep the native execute bit")
})

test("the copy filter keeps what a running adapter loads", () => {
  for (const kept of ["bin/kilo", "package.json", "lib/find.js", "lib/find.mjs",
    "node_modules/a/node_modules/b/index.js"]) {
    assert.equal(isRuntimeFile(kept), true, `${kept} is a runtime file`)
  }
  // Declarations and source maps, every TypeScript source extension (a `.d.mts`
  // declaration is a TypeScript source by that rule), documentation, npm's bin
  // farm and lockfiles are all dropped.
  for (const dropped of ["lib/find.d.ts", "lib/find.js.map", "lib/find.mjs.map", "dist/index.d.mts",
    "README.md", "guide.markdown", "lib/find.ts", "lib/find.mts", "lib/find.cts", "lib/find.tsx",
    "docs/guide.md", "examples/demo.js", ".bin/kilo", "a/.bin/kilo", "package-lock.json",
    "a/b/package-lock.json", "a/b/.package-lock.json"]) {
    assert.equal(isRuntimeFile(dropped), false, `${dropped} is not a runtime file`)
  }
})

test("the package lookup is bounded to the runtime root it is given", () => {
  const { root } = fixtureSource({ name: "lookup" })
  assert.equal(resolvePackage(ADAPTER_PACKAGE, root, root),
    path.join(root, "node_modules", ADAPTER_PACKAGE))
  assert.equal(resolvePackage(BASELINE, path.join(root, "node_modules", ADAPTER_PACKAGE), root),
    path.join(root, PLATFORM_PACKAGE))
  assert.equal(resolvePackage("not-installed", root, root), null)
})

test("the real locked kilo closure builds, is deterministic and is self-contained", {
  skip: HAS_LOCKED_SOURCE ? false : "run `npm ci` in plugins/harness/packaging/kilo first",
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
  // The launcher is the only dependency, plus the one platform package npm
  // installed for this host.
  assert.equal(one.packages.find((item) => item.name === ADAPTER_PACKAGE).version, ADAPTER_VERSION)
  assert.equal(one.packages.length, 2)
  const platform = one.packages.find((item) => item.name !== ADAPTER_PACKAGE)
  assert.ok(platform, "the platform package the launcher resolves must be packaged")
  for (const foreign of EXCLUDED_ADAPTERS) {
    assert.ok(!one.packages.some((item) => item.name === foreign), `${foreign} must not be packaged`)
  }
  // The AVX2 variant never travels, and the build says why.
  for (const excluded of EXCLUDED_VARIANTS) {
    assert.ok(!one.packages.some((item) => item.name === excluded), `${excluded} must not be packaged`)
    assert.ok(one.optionalSkipped.some((item) => item.name === excluded
      && item.reason === "excluded-variant"), `${excluded} must be recorded as excluded by rule`)
  }
  // The entry the deployment spawns is present, and the native payload keeps
  // its execute bit when the installed platform is the baseline variant.
  assert.equal(statSync(path.join(first, ENTRY)).isFile(), true)
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(readFileSync(path.join(first, MARKER_NAME), "utf8"), MARKER_CONTENT)
  for (const relative of EXECUTABLE_FILES) {
    if (!existsSync(path.join(first, relative))) continue
    assert.equal(statSync(path.join(first, relative)).mode & 0o777, 0o555,
      `${relative} must stay executable`)
  }
  assert.throws(() => statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, "README.md")), /ENOENT/,
    "README.md should have been excluded")
})
