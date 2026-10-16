/**
 * Builder gates for the Codex runtime artifact.
 *
 * The failures worth catching before they ship: a closure that is quietly
 * incomplete (the adapter spawning a Codex CLI that is not in the tree), a
 * package that disagrees with the lock, a native package that describes another
 * target, an executable bit flattened to read-only, a tree that is not a plain
 * file tree, and an output path this build does not own. Each is asserted
 * against a small synthetic runtime root, so the checks run without touching the
 * reviewed one (a real build is ~315 MB and belongs to the chain gate).
 */
import { execFileSync } from "node:child_process"
import { mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync, chmodSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import test from "node:test"
import assert from "node:assert/strict"

import { build, NATIVE_TARGET } from "../../tooling/build-runtime-artifact.mjs"

const REPO = path.resolve(import.meta.dirname, "../../..")

function packageAt(root, relative, manifest) {
  const directory = path.join(root, relative)
  mkdirSync(directory, { recursive: true })
  writeFileSync(path.join(directory, "package.json"), JSON.stringify(manifest))
  return directory
}

/** A miniature runtime root with the same shape the real one has. */
function fixtureRuntime({ name = "noop" } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), `codex-runtime-fixture-${name}-`))
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
  add("node_modules/@agentclientprotocol/codex-acp", {
    name: "@agentclientprotocol/codex-acp", version: "1.1.14",
    dependencies: { "@agentclientprotocol/sdk": "^1.3.0", "@openai/codex": "^0.147.0", "diff": "^9.0.0" },
  }, {
    "dist/index.js": "export default 1\n", "dist/index.d.ts": "export default 1\n",
    "README.md": "# adapter\n", "dist/index.js.map": "{}\n",
  })
  add("node_modules/@agentclientprotocol/codex-acp/node_modules/@agentclientprotocol/sdk", {
    name: "@agentclientprotocol/sdk", version: "1.3.0",
  })
  add("node_modules/diff", { name: "diff", version: "9.0.0" })
  add("node_modules/@openai/codex", {
    name: "@openai/codex", version: "0.147.0",
    optionalDependencies: {
      "@openai/codex-linux-x64": "npm:@openai/codex@0.147.0-linux-x64",
      "@openai/codex-win32-x64": "npm:@openai/codex@0.147.0-win32-x64",
    },
  }, { "bin/codex.js": "// launcher\n" })
  add("node_modules/@openai/codex-linux-x64", {
    name: "@openai/codex", version: "0.147.0-linux-x64", os: ["linux"], cpu: ["x64"],
  }, {
    "vendor/x86_64-unknown-linux-musl/codex-package.json": JSON.stringify({
      layoutVersion: 1, version: "0.147.0", target: NATIVE_TARGET, variant: "codex",
      entrypoint: "bin/codex", resourcesDir: "codex-resources", pathDir: "codex-path",
    }),
    "vendor/x86_64-unknown-linux-musl/bin/codex": "#!/bin/true\nnative\n",
    "vendor/x86_64-unknown-linux-musl/codex-path/rg": "#!/bin/true\nrg\n",
    "vendor/x86_64-unknown-linux-musl/codex-resources/bwrap": "#!/bin/true\nbwrap\n",
    "README.md": "native package\n",
  })
  add("node_modules/@openai/codex-win32-x64", {
    name: "@openai/codex", version: "0.147.0-win32-x64", os: ["win32"], cpu: ["x64"],
  })
  chmodSync(path.join(root, "node_modules/@openai/codex-linux-x64/vendor",
    NATIVE_TARGET, "bin/codex"), 0o755)
  // Present in the tree, reachable only from Pi, and therefore excluded.
  add("node_modules/@automatalabs/pi-acp", {
    name: "@automatalabs/pi-acp", version: "0.5.0",
    dependencies: { "@earendil-works/pi-coding-agent": "0.84.2" },
  })
  add("node_modules/@earendil-works/pi-coding-agent", {
    name: "@earendil-works/pi-coding-agent", version: "0.84.2" })
  add("node_modules/@agentclientprotocol/codex-acp/example.ts", {
    name: "@agentclientprotocol/codex-acp", version: "1.1.14" })
  writeFileSync(path.join(root, "package-lock.json"), JSON.stringify(lock))
  return root
}

function outputFor(name) {
  return path.join(mkdtempSync(path.join(tmpdir(), `codex-runtime-out-${name}-`)), "artifact")
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

test("builds the closure, keeps the native payload, and is deterministic", () => {
  const source = fixtureRuntime({ name: "happy" })
  const first = outputFor("happy-1")
  const second = outputFor("happy-2")
  const one = build({ output: first, source })
  const two = build({ output: second, source })
  assert.equal(one.treeDigest, two.treeDigest)
  assert.equal(one.entries, two.entries)
  assert.equal(one.bytes, two.bytes)
  assert.deepEqual(
    readFileSync(`${first}.manifest.json`, "utf8"),
    readFileSync(`${second}.manifest.json`, "utf8"),
    "two builds of one input must produce the same manifest",
  )
  assert.deepEqual(
    one.packages.map((item) => `${item.name}@${item.version}`).sort(),
    ["@agentclientprotocol/codex-acp@1.1.14", "@agentclientprotocol/sdk@1.3.0",
     "@openai/codex@0.147.0", "@openai/codex@0.147.0-linux-x64", "diff@9.0.0"],
  )
  // The native payload travels with the adapter that spawns it.
  assert.deepEqual(one.native, {
    package: "@openai/codex-linux-x64", version: "0.147.0-linux-x64", target: NATIVE_TARGET,
    entrypoint: "bin/codex", cliVersion: "0.147.0",
  })
  assert.equal(statSync(path.join(first, "node_modules/@openai/codex-linux-x64/vendor",
    NATIVE_TARGET, "bin/codex")).mode & 0o777, 0o555, "the native binary must stay executable")
  assert.equal(statSync(path.join(first, "node_modules/@openai/codex-linux-x64/vendor",
    NATIVE_TARGET, "codex-path/rg")).mode & 0o777, 0o444)
  // Other platforms and the other harnesses' payloads never enter this artifact.
  assert.ok(!one.packages.some((item) => item.version.includes("win32")))
  assert.ok(!one.packages.some((item) => item.name.startsWith("@earendil-works")))
  assert.ok(!one.packages.some((item) => item.name === "@automatalabs/pi-acp"))
  assert.deepEqual(one.excluded.piOnlyPackages.sort(), [
    "node_modules/@automatalabs/pi-acp", "node_modules/@earendil-works/pi-coding-agent",
  ].sort())
  // Non-runtime files, npm's symlink farm and hidden lockfiles are dropped.
  for (const relative of ["dist/index.d.ts", "dist/index.js.map", "README.md"]) {
    assert.throws(
      () => statSync(path.join(first, "node_modules/@agentclientprotocol/codex-acp", relative)),
      /ENOENT/, `${relative} should have been excluded`,
    )
  }
  assert.throws(
    () => statSync(path.join(first, "node_modules/@openai/codex-linux-x64/README.md")), /ENOENT/)
  // The published tree is read-only and carries its owner marker.
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(statSync(path.join(first, "node_modules/@agentclientprotocol/codex-acp/dist/index.js")).mode & 0o777, 0o444)
  assert.match(readFileSync(path.join(first, ".agentbox-codex-runtime-artifact"), "utf8"), /r1/)
})

test("a missing required dependency fails loudly", () => {
  const source = fixtureRuntime({ name: "missing" })
  rmSync(path.join(source, "node_modules/@openai/codex"), { recursive: true })
  expectBuildError(() => build({ output: outputFor("missing"), source }), "CODEX_CLOSURE_DEPENDENCY_MISSING")
})

test("a package version that disagrees with the lock fails loudly", () => {
  const source = fixtureRuntime({ name: "drift" })
  const manifestPath = path.join(source, "node_modules/diff/package.json")
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"))
  manifest.version = "9.0.9"
  writeFileSync(manifestPath, JSON.stringify(manifest))
  expectBuildError(() => build({ output: outputFor("drift"), source }), "CODEX_LOCK_VERSION_MISMATCH")
})

test("a native package that describes another target fails loudly", () => {
  const source = fixtureRuntime({ name: "native" })
  const metadataPath = path.join(source, "node_modules/@openai/codex-linux-x64/vendor",
    NATIVE_TARGET, "codex-package.json")
  const metadata = JSON.parse(readFileSync(metadataPath, "utf8"))
  metadata.version = "0.150.0"
  writeFileSync(metadataPath, JSON.stringify(metadata))
  expectBuildError(() => build({ output: outputFor("native"), source }), "CODEX_NATIVE_METADATA_DRIFT")
})

test("a non-executable native binary fails loudly", () => {
  const source = fixtureRuntime({ name: "binary" })
  chmodSync(path.join(source, "node_modules/@openai/codex-linux-x64/vendor",
    NATIVE_TARGET, "bin/codex"), 0o644)
  expectBuildError(() => build({ output: outputFor("binary"), source }), "CODEX_NATIVE_BINARY_INVALID")
})

test("a symlink anywhere in the closure fails loudly", () => {
  const source = fixtureRuntime({ name: "symlink" })
  symlinkSync("/etc/passwd", path.join(source, "node_modules/diff/escape"))
  expectBuildError(() => build({ output: outputFor("symlink"), source }), "CODEX_ARTIFACT_SHAPE_INVALID")
})

test("output policy refuses the repository, relative paths and user config roots", () => {
  const source = fixtureRuntime({ name: "policy" })
  expectBuildError(() => build({ output: "relative/artifact", source }), "CODEX_OUTPUT_NOT_ABSOLUTE")
  expectBuildError(() => build({ output: path.join(REPO, "artifact"), source }), "CODEX_OUTPUT_INSIDE_REPOSITORY")
  expectBuildError(() => build({ output: path.join(process.env.HOME, ".codex", "artifact"), source }),
    "CODEX_OUTPUT_RESERVED")
  expectBuildError(() => build({ output: path.join(process.env.HOME, ".config", "codex"), source }),
    "CODEX_OUTPUT_RESERVED")
  expectBuildError(() => build({ output: "/", source }), "CODEX_OUTPUT_UNSAFE")
})

test("an unmarked output is never deleted, and an owned one needs --replace", () => {
  const source = fixtureRuntime({ name: "target" })
  const output = outputFor("target")
  mkdirSync(output)
  const keep = path.join(output, "user-file")
  writeFileSync(keep, "must survive")
  expectBuildError(() => build({ output, source }), "CODEX_OUTPUT_NOT_OWNED")
  assert.equal(readFileSync(keep, "utf8"), "must survive")

  rmSync(keep)
  build({ output, source })
  expectBuildError(() => build({ output, source }), "CODEX_OUTPUT_EXISTS")
  const rebuilt = build({ output, source, replace: true })
  assert.match(rebuilt.treeDigest, /^sha256:[0-9a-f]{64}$/)
})

test("a fixture fifo in the closure fails loudly", () => {
  const source = fixtureRuntime({ name: "fifo" })
  const fifo = path.join(source, "node_modules/diff/pipe")
  execFileSync("mkfifo", [fifo])
  expectBuildError(() => build({ output: outputFor("fifo"), source }), "CODEX_ARTIFACT_SHAPE_INVALID")
})
