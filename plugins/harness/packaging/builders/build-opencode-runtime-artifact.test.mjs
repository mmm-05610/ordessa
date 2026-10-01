/**
 * Builder gates for the OpenCode runtime artifact.
 *
 * OpenCode is the first of the four rollout harnesses whose entry is not a
 * JavaScript module at all. `opencode-ai` ships no library: its `postinstall`
 * places the platform's native ELF at `bin/opencode.exe` and links it to the
 * platform package's own copy. That makes three failures possible that the
 * dsh and kilo gates cannot express — the builder verifying a binary it never
 * runs install-time code to produce, the platform package being *pinned*
 * rather than inferred from `process.platform` (four published packages share
 * `linux`/`x64` and differ only by libc and CPU baseline), and a read-only
 * sealing pass that would otherwise strip the exec bit off the one file the
 * whole artifact exists to run.
 *
 * The synthetic roots are only ever the *input* to the builder. The tree digest
 * is never stubbed: every build goes through the reviewed Python
 * `runtime_artifact_tree_summary`, so a green run is a real digest.
 */
import { execFileSync } from "node:child_process"
import {
  chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync,
  truncateSync, writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import test, { after } from "node:test"
import assert from "node:assert/strict"

import {
  ADAPTER_PACKAGE, ADAPTER_VERSION, ENTRY, EXCLUDED_ADAPTERS, EXCLUDED_PLATFORM_PACKAGES,
  MARKER_CONTENT, MARKER_NAME, NATIVE_BINARY, NATIVE_BINARY_BYTES, TARGET_PLATFORM,
  assertOutputPolicy, build, clearTarget, isOwnedArtifact, isRuntimeFile, platformPackageIsTargeted,
} from "./build-opencode-runtime-artifact.mjs"

const REPO = path.resolve(import.meta.dirname, "..", "..")
// The reviewed runtime root: the same path the builder resolves as its default.
const DEFAULT_SOURCE = path.join(REPO, "packaging", "opencode")
// The real locked closure only exists after `npm ci` in packaging/opencode;
// node_modules is not part of the source tree, so that test skips rather than fails.
const HAS_LOCKED_SOURCE = existsSync(path.join(DEFAULT_SOURCE, "node_modules", ADAPTER_PACKAGE, "package.json"))

// Every fixture root and every scratch output is temporary state; none of it
// survives the file, including the read-only published trees.
const fixtureRoots = []
const makeWritable = (directory) => {
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const location = path.join(directory, entry.name)
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
 * The binary the fixture must place at the entry path. It is sparse, so it costs
 * no real blocks, but it is `NATIVE_BINARY_BYTES` long on purpose: the size gate
 * is the only cheap way to notice that the pinned package's binary changed, and a
 * fixture that quietly used a short file would make that gate untested.
 */
function placeNativeBinary(root, bytes = NATIVE_BINARY_BYTES) {
  const file = path.join(root, NATIVE_BINARY)
  mkdirSync(path.dirname(file), { recursive: true })
  truncateSync(file, bytes)
  writeFileSync(file, "ELF-ish\n", { flag: "r+" })
  return file
}

/** Every platform package the pinned adapter declares, as the real lock has them. */
const ALL_PLATFORMS = [
  "opencode-linux-x64", "opencode-linux-x64-baseline", "opencode-linux-x64-baseline-musl",
  "opencode-linux-x64-musl", "opencode-linux-arm64", "opencode-linux-arm64-musl",
  "opencode-darwin-x64", "opencode-darwin-x64-baseline", "opencode-darwin-arm64",
  "opencode-windows-x64", "opencode-windows-x64-baseline", "opencode-windows-arm64",
]

/**
 * A miniature installed-package root with the shape the real one has: the
 * pinned adapter, the full platform matrix declared as optional dependencies,
 * the pinned platform package installed, and a lock recording exactly what is
 * on disk. `installed` overrides which platform packages are actually present,
 * so a test can plant the wrong sibling or none at all.
 */
function fixtureSource({ name = "noop", installed = [TARGET_PLATFORM.package], native = true } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), `opencode-source-${name}-`))
  fixtureRoots.push(root)
  const lock = { lockfileVersion: 3, packages: {} }
  const optionalDependencies = {}
  for (const platform of ALL_PLATFORMS) optionalDependencies[platform] = TARGET_PLATFORM.version
  // When the fixture is told there is no binary, it must plant none at all: an
  // empty file at the entry path is a different failure (wrong size) and would
  // make the absent-binary gate untested.
  const files = {
    "lib/index.mjs": "export const version = 1\n",
    "lib/index.d.ts": "export declare const version: number\n",
    "README.md": "# opencode\n",
    "postinstall.mjs": "throw new Error('install scripts must never run at build time')\n",
  }
  if (native) files["bin/opencode.exe"] = ""
  packageAt(root, `node_modules/${ADAPTER_PACKAGE}`, {
    name: ADAPTER_PACKAGE, version: ADAPTER_VERSION, bin: { opencode: "bin/opencode.exe" },
    optionalDependencies,
  }, files, lock)
  if (native) placeNativeBinary(root)
  for (const platform of installed) {
    packageAt(root, `node_modules/${platform}`, {
      name: platform, version: TARGET_PLATFORM.version, os: ["linux"], cpu: ["x64"],
    }, { "bin/opencode": "" }, lock)
  }
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  return { root, lock }
}

/** A scratch output outside the repository, removed with the test that made it. */
function scratchFor(t, name) {
  const parent = mkdtempSync(path.join(tmpdir(), `opencode-out-${name}-`))
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
  assert.deepEqual(
    readFileSync(`${first}.manifest.json`, "utf8"),
    readFileSync(`${second}.manifest.json`, "utf8"),
    "two builds of one input must produce the same manifest",
  )
  assert.equal(one.schemaVersion, 1)
  assert.equal(one.kind, "agentbox-opencode-runtime-artifact")
  assert.match(one.treeDigest, /^sha256:[0-9a-f]{64}$/)
  assert.match(one.sourceLockDigest, /^sha256:[0-9a-f]{64}$/)
  // The adapter block names the entry; the native block records what has to run,
  // and which platform package it was taken from.
  assert.deepEqual(one.adapter, { package: ADAPTER_PACKAGE, version: ADAPTER_VERSION, entry: ENTRY })
  assert.equal(one.nativeBinary.path, NATIVE_BINARY)
  assert.equal(one.nativeBinary.bytes, NATIVE_BINARY_BYTES)
  assert.match(one.nativeBinary.sha256, /^sha256:[0-9a-f]{64}$/)
  assert.equal(one.nativeBinary.platformPackage, TARGET_PLATFORM.package)
  assert.deepEqual(
    { os: one.nativeBinary.os, cpu: one.nativeBinary.cpu, libc: one.nativeBinary.libc },
    { os: TARGET_PLATFORM.os, cpu: TARGET_PLATFORM.cpu, libc: TARGET_PLATFORM.libc },
  )
  // Exactly the closure: the adapter and the one pinned platform package.
  assert.deepEqual(
    one.packages.map((item) => item.name).sort(),
    [ADAPTER_PACKAGE, TARGET_PLATFORM.package].sort(),
  )
  for (const item of one.packages) assert.equal(lock.packages[item.path].version, item.version)
  // The eleven other platforms are recorded as deliberately not taken, with the
  // reason, rather than silently dropped.
  assert.equal(one.optionalSkipped.length, ALL_PLATFORMS.length - 1)
  for (const item of one.optionalSkipped) assert.equal(item.reason, "not-installed")
  // The entry travels, the install script and the excluded file families do not.
  assert.equal(statSync(path.join(first, ENTRY)).isFile(), true)
  assert.throws(() => statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, "postinstall.mjs")), /ENOENT/,
    "the install script that would produce the binary must not ride in the artifact")
  for (const relative of ["lib/index.d.ts", "README.md"]) {
    assert.throws(() => statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, relative)), /ENOENT/,
      `${relative} should have been excluded`)
  }
  // Sealing, and specifically what sealing must NOT do to the entry.
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(statSync(path.join(first, ENTRY)).mode & 0o777, 0o555,
    "a 0444 entry would make the artifact unrunnable")
  assert.equal(statSync(path.join(first, "node_modules", ADAPTER_PACKAGE, "lib", "index.mjs")).mode & 0o777, 0o444)
  assert.equal(readFileSync(path.join(first, MARKER_NAME), "utf8"), MARKER_CONTENT)
})

test("the platform is pinned, never inferred from the machine running the build", () => {
  // os/cpu alone cannot separate these: all four are linux/x64, and picking by
  // them would ship a musl or baseline build under a glibc x86-64 pin.
  for (const name of ALL_PLATFORMS) {
    assert.equal(platformPackageIsTargeted(name), name === TARGET_PLATFORM.package, name)
  }
  assert.deepEqual(
    [...EXCLUDED_PLATFORM_PACKAGES].sort(),
    ALL_PLATFORMS.filter((name) => name !== TARGET_PLATFORM.package).sort(),
    "every published variant except the pinned one must be named as excluded",
  )
})

test("a closure without the pinned platform package fails loudly", (t) => {
  const { root } = fixtureSource({ name: "no-platform", installed: [] })
  const error = expectBuildError(
    () => build({ output: scratchFor(t, "no-platform"), source: root }),
    "OPENCODE_PLATFORM_PACKAGE_MISSING",
  )
  assert.match(error.message, /never infers a platform/)
})

test("a sibling linux/x64 platform package installed alongside the pinned one is excluded, not shipped", (t) => {
  const { root } = fixtureSource({
    name: "sibling", installed: [TARGET_PLATFORM.package, "opencode-linux-x64-musl", "opencode-darwin-arm64"],
  })
  const output = scratchFor(t, "sibling")
  const built = build({ output, source: root })
  assert.deepEqual(
    built.packages.map((item) => item.name).sort(),
    [ADAPTER_PACKAGE, TARGET_PLATFORM.package].sort(),
  )
  const reasons = Object.fromEntries(built.optionalSkipped.map((item) => [item.name, item.reason]))
  assert.equal(reasons["opencode-linux-x64-musl"], "not-the-pinned-platform")
  assert.equal(reasons["opencode-darwin-arm64"], "not-the-pinned-platform")
  assert.equal(reasons["opencode-linux-x64-baseline"], "not-installed")
  assert.throws(() => statSync(path.join(output, "node_modules", "opencode-linux-x64-musl")), /ENOENT/)
})

test("the native binary is verified, and never produced by running the install script", (t) => {
  // Absent: the builder must say so rather than build an artifact with no binary.
  const absent = fixtureSource({ name: "no-binary", native: false })
  const missing = expectBuildError(
    () => build({ output: scratchFor(t, "no-binary"), source: absent.root }),
    "OPENCODE_NATIVE_BINARY_MISSING",
  )
  assert.match(missing.message, /npm ci/)

  // Present but the wrong size: that is a different package version wearing the
  // right version number, so it must be refused rather than shipped.
  const wrongSize = fixtureSource({ name: "short-binary" })
  truncateSync(path.join(wrongSize.root, NATIVE_BINARY), NATIVE_BINARY_BYTES - 1)
  expectBuildError(
    () => build({ output: scratchFor(t, "short-binary"), source: wrongSize.root }),
    "OPENCODE_NATIVE_BINARY_SIZE_MISMATCH",
  )

  // The install script is present in the fixture and would throw if it ran.
  const { root } = fixtureSource({ name: "no-scripts" })
  const output = scratchFor(t, "no-scripts")
  build({ output, source: root })
  assert.equal(existsSync(path.join(output, "node_modules", ADAPTER_PACKAGE, "postinstall.mjs")), false)
})

test("the sealed entry is the binary the manifest describes", (t) => {
  const { root } = fixtureSource({ name: "identity" })
  const output = scratchFor(t, "identity")
  const built = build({ output, source: root })
  const entry = path.join(output, ENTRY)
  assert.equal(statSync(entry).size, built.nativeBinary.bytes)
  // Read the file the way the verifier will, and compare with the recorded digest.
  const digest = execFileSync("sha256sum", [entry], { encoding: "utf8" }).split(" ")[0]
  assert.equal(built.nativeBinary.sha256, `sha256:${digest}`)
})

test("a package version that disagrees with the lock fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "drift" })
  lock.packages[`node_modules/${TARGET_PLATFORM.package}`].version = "1.18.20"
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(() => build({ output: scratchFor(t, "drift"), source: root }), "OPENCODE_LOCK_VERSION_MISMATCH")
})

test("a package the lock does not record fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "unrecorded" })
  delete lock.packages[`node_modules/${TARGET_PLATFORM.package}`]
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(() => build({ output: scratchFor(t, "unrecorded"), source: root }), "OPENCODE_LOCK_ENTRY_MISSING")
})

test("an adapter version other than the pinned one fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "adapter-version" })
  const manifestPath = path.join(root, "node_modules", ADAPTER_PACKAGE, "package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "1.18.20"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  // The lock has to agree with disk, or the earlier gate would catch this and
  // the adapter-version gate below it would stay untested.
  lock.packages[`node_modules/${ADAPTER_PACKAGE}`].version = "1.18.20"
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(
    () => build({ output: scratchFor(t, "adapter-version"), source: root }),
    "OPENCODE_ADAPTER_VERSION_MISMATCH",
  )
})

test("another family's adapter installed in the opencode root fails loudly", (t) => {
  const { root, lock } = fixtureSource({ name: "foreign" })
  packageAt(root, `node_modules/${EXCLUDED_ADAPTERS[0]}`, {
    name: EXCLUDED_ADAPTERS[0], version: "1.0.0",
  }, { "index.js": "export default 1\n" }, lock)
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  expectBuildError(
    () => build({ output: scratchFor(t, "foreign"), source: root }),
    "OPENCODE_ARTIFACT_UNRELATED_PACKAGE",
  )
})

test("an absent source is refused with a clear error, not an empty artifact", (t) => {
  expectBuildError(
    () => build({ output: scratchFor(t, "absent"), source: path.join(tmpdir(), "opencode-does-not-exist-xyz") }),
    "OPENCODE_SOURCE_INVALID",
  )
})

test("output policy refuses the repository, relative paths and user config roots", () => {
  assert.throws(() => assertOutputPolicy("relative/path"), { code: "OPENCODE_OUTPUT_NOT_ABSOLUTE" })
  assert.throws(() => assertOutputPolicy(REPO), { code: "OPENCODE_OUTPUT_INSIDE_REPOSITORY" })
  assert.throws(() => assertOutputPolicy(path.join(REPO, "out")), { code: "OPENCODE_OUTPUT_INSIDE_REPOSITORY" })
  assert.throws(() => assertOutputPolicy(path.join(REPO, "node_modules", "oc")), { code: "OPENCODE_OUTPUT_INSIDE_REPOSITORY" })
  assert.throws(() => assertOutputPolicy("/"), { code: "OPENCODE_OUTPUT_UNSAFE" })
  for (const reserved of [".config", ".local"]) {
    assert.throws(() => assertOutputPolicy(path.join(process.env.HOME, reserved, "ordessa")), { code: "OPENCODE_OUTPUT_RESERVED" })
  }
  assert.equal(assertOutputPolicy("/var/tmp/opencode-artifact"), "/var/tmp/opencode-artifact")
})

test("an unmarked output is never deleted, and an owned one needs --replace", (t) => {
  const foreign = scratchFor(t, "foreign-output")
  mkdirSync(foreign, { recursive: true })
  writeFileSync(path.join(foreign, "someone-elses-file"), "keep me\n")
  expectBuildError(() => clearTarget(foreign, { replace: false }), "OPENCODE_OUTPUT_NOT_OWNED")
  expectBuildError(() => clearTarget(foreign, { replace: true }), "OPENCODE_OUTPUT_NOT_OWNED")
  assert.equal(readFileSync(path.join(foreign, "someone-elses-file"), "utf8"), "keep me\n")

  const owned = scratchFor(t, "owned-output")
  mkdirSync(owned, { recursive: true })
  writeFileSync(path.join(owned, MARKER_NAME), MARKER_CONTENT)
  writeFileSync(path.join(owned, "stale"), "x")
  assert.equal(isOwnedArtifact(owned), true)
  expectBuildError(() => clearTarget(owned, { replace: false }), "OPENCODE_OUTPUT_EXISTS")
  clearTarget(owned, { replace: true })
  assert.equal(existsSync(owned), false)
})

test("the copy filter keeps what a running binary loads", () => {
  for (const kept of [ENTRY, "lib/index.mjs", "bin/opencode"]) assert.equal(isRuntimeFile(kept), true, kept)
  for (const dropped of [
    "lib/index.d.ts", "lib/index.js.map", "src/main.ts", "README.md", "docs/guide.markdown",
    "package-lock.json", ".package-lock.json", "postinstall.mjs", "node_modules/.bin/opencode",
    "examples/basic/main.js",
  ]) assert.equal(isRuntimeFile(dropped), false, dropped)
})

test("the real locked opencode closure builds, is deterministic and its sealed entry runs", { skip: !HAS_LOCKED_SOURCE ? "run `npm ci` in plugins/harness/packaging/opencode first" : false }, (t) => {
  const first = scratchFor(t, "real-1")
  const second = scratchFor(t, "real-2")
  const one = build({ output: first, source: DEFAULT_SOURCE })
  const two = build({ output: second, source: DEFAULT_SOURCE })
  assert.equal(one.treeDigest, two.treeDigest)
  assert.deepEqual(readFileSync(`${first}.manifest.json`, "utf8"), readFileSync(`${second}.manifest.json`, "utf8"))

  assert.equal(one.adapter.version, ADAPTER_VERSION)
  assert.equal(one.nativeBinary.bytes, NATIVE_BINARY_BYTES)
  assert.equal(one.nativeBinary.platformPackage, TARGET_PLATFORM.package)
  // Self-contained: the artifact carries the platform package it was built for
  // and none of the other eleven, and nothing points outside the tree.
  assert.equal(one.packages.some((item) => item.name === TARGET_PLATFORM.package), true)
  for (const excluded of EXCLUDED_PLATFORM_PACKAGES) {
    assert.equal(existsSync(path.join(first, "node_modules", excluded)), false, excluded)
    assert.equal(one.packages.some((item) => item.name === excluded), false, excluded)
  }
  // The seal must not cost the artifact its ability to run: the entry is the
  // native ELF opencode-ai's postinstall placed, and it reports its version.
  assert.equal(statSync(path.join(first, ENTRY)).mode & 0o111, 0o111, "the sealed entry lost its exec bit")
  assert.match(execFileSync(path.join(first, ENTRY), ["--version"], { encoding: "utf8", timeout: 120_000 }).trim(),
    new RegExp(`^${ADAPTER_VERSION.replace(/\./g, "\\.")}`))
})