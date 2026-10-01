/**
 * Builder gates for the Hermes runtime artifact.
 *
 * The interesting failures are the ones that would otherwise ship: a closure
 * that is quietly incomplete, an installed version that does not satisfy the
 * specifier that pulled it in, an extra that rides along, a tree that is not a
 * plain file tree, and an output path this build does not own. Each is asserted
 * against a small synthetic installed-package root, so the checks are exercised
 * without touching the reviewed one; one test additionally builds the real
 * installed closure and proves the artifact is self-contained.
 */
import { execFileSync, spawnSync } from "node:child_process"
import {
  chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, symlinkSync, writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import test from "node:test"
import assert from "node:assert/strict"

import {
  DEFAULT_FALLBACK_SOURCES, ENTRY_DISTRIBUTION, ENTRY_EXTRAS, SOURCE_ENVIRONMENT_VARIABLE,
  assertOutputPolicy, assertSourcePolicy, build, indexDistributions, resolveClosure, resolveSource,
  selfCheck,
} from "./build-hermes-runtime-artifact.mjs"

const REPO = path.resolve(import.meta.dirname, "..", "..")

function metadataText(name, version, { requires = [], extras = [], topLevel = [] } = {}) {
  return [
    "Metadata-Version: 2.4",
    `Name: ${name}`,
    `Version: ${version}`,
    ...requires.map((item) => `Requires-Dist: ${item}`),
    ...extras.map((item) => `Provides-Extra: ${item}`),
    "Requires-Python: >=3.11",
    "",
    ...(topLevel.length ? topLevel.join("\n") + "\n" : ""),
  ].join("\n")
}

/** One installed wheel-shaped distribution: metadata, RECORD, package files. */
function addDistribution(root, {
  project, version, requires = [], extras = [], modules = {}, topLevel = [], withRecord = true,
}) {
  const info = path.join(root, `${project.replace(/-/g, "_")}-${version}.dist-info`)
  mkdirSync(info, { recursive: true })
  writeFileSync(path.join(info, "METADATA"), metadataText(project, version, { requires, extras, topLevel: [] }))
  writeFileSync(path.join(info, "top_level.txt"), topLevel.join("\n") + "\n")
  const record = []
  record.push(`${project.replace(/-/g, "_")}-${version}.dist-info/METADATA,,`)
  record.push(`${project.replace(/-/g, "_")}-${version}.dist-info/top_level.txt,,`)
  for (const [relative, content] of Object.entries(modules)) {
    const location = path.join(root, relative)
    mkdirSync(path.dirname(location), { recursive: true })
    writeFileSync(location, content)
    record.push(`${relative},sha256:0,${content.length}`)
  }
  if (withRecord) writeFileSync(path.join(info, "RECORD"), record.join("\n") + "\n")
  return { root, info }
}

/** One installed platform (egg-info) distribution: metadata and a module tree. */
function addEggDistribution(root, {
  project, version, requires = [], modules = {}, topLevel = [],
}) {
  const info = path.join(root, `${project.replace(/-/g, "_")}-${version}.egg-info`)
  mkdirSync(info, { recursive: true })
  writeFileSync(path.join(info, "PKG-INFO"), metadataText(project, version, { requires, topLevel: [] }))
  writeFileSync(path.join(info, "top_level.txt"), topLevel.join("\n") + "\n")
  for (const [relative, content] of Object.entries(modules)) {
    const location = path.join(root, relative)
    mkdirSync(path.dirname(location), { recursive: true })
    writeFileSync(location, content)
  }
  return { root, info }
}

/** A miniature installed-package set with the same shape the real one has. */
function fixtureSource({ name = "noop" } = {}) {
  const root = mkdtempSync(path.join(tmpdir(), `hermes-source-${name}-`))
  const fallback = mkdtempSync(path.join(tmpdir(), `hermes-fallback-${name}-`))
  const entryFiles = {
    "hermes_cli/__init__.py": "__version__ = '0.19.0'\n",
    "hermes_cli/main.py": "def main():\n    from acp_adapter.entry import main as acp_main\n    return acp_main\n",
    "acp_adapter/__init__.py": "\n",
    "acp_adapter/entry.py": "def main(argv=None):\n    import acp\n    return acp\n",
  }
  addDistribution(root, {
    project: ENTRY_DISTRIBUTION, version: "0.19.0",
    requires: [
      "openai==2.24.0",
      'distro<2,>=1.7.0; sys_platform != "win32"',
      "tzdata==2025.3; sys_platform == \"win32\"",
      'agent-client-protocol==0.9.0; extra == "acp"',
      'pytest==9.0.2; extra == "dev"',
    ],
    extras: ["acp", "dev"],
    modules: entryFiles, topLevel: ["hermes_cli", "acp_adapter"],
  })
  addDistribution(root, {
    project: "acp-adapter", version: "1.0.0", modules: { "acp_adapter/__init__.py": "\n" }, topLevel: ["acp_adapter"],
  })
  addDistribution(root, {
    project: "openai", version: "2.24.0",
    requires: ['distro>=1.7.0,<2; sys_platform != "win32"', "six==1.16.0"],
    modules: { "openai/__init__.py": "\n", "openai/_base_client.py": "import distro\n" }, topLevel: ["openai"],
  })
  addDistribution(root, {
    project: "agent-client-protocol", version: "0.9.0", requires: ["pydantic>=2.7"],
    modules: { "acp/__init__.py": "\n", "acp/connection.py": "\n" }, topLevel: ["acp"],
  })
  addDistribution(root, { project: "pydantic", version: "2.13.4", modules: { "pydantic/__init__.py": "\n" }, topLevel: ["pydantic"] })
  addDistribution(root, {
    project: "pytest", version: "9.0.2", modules: { "_pytest/__init__.py": "\n" }, topLevel: ["_pytest"],
  })
  addDistribution(root, { project: "tzdata", version: "2025.3", modules: { "tzdata/__init__.py": "\n" }, topLevel: ["tzdata"] })
  // Only the platform root has these two, one wheel-shaped and one egg-shaped.
  addDistribution(fallback, {
    project: "distro", version: "1.9.0", modules: { "distro/__init__.py": "", "distro/distro.py": "\n" }, topLevel: ["distro"],
  })
  addEggDistribution(fallback, {
    project: "six", version: "1.16.0", modules: { "six.py": "def moves(): return None\n" }, topLevel: ["six"],
  })
  // An unrelated tool and its exclusive closure: the exclusion probe must find it.
  addDistribution(root, {
    project: "flask", version: "3.1.3", requires: ["werkzeug>=3.1", "itsdangerous>=2.2"],
    modules: { "flask/__init__.py": "\n" }, topLevel: ["flask"],
  })
  addDistribution(root, { project: "werkzeug", version: "3.1.3", modules: { "werkzeug/__init__.py": "\n" }, topLevel: ["werkzeug"] })
  addDistribution(root, { project: "itsdangerous", version: "2.2.0", modules: { "itsdangerous/__init__.py": "\n" }, topLevel: ["itsdangerous"] })
  // Installed, reachable from nothing: it must never ride along.
  addDistribution(root, {
    project: "boto3", version: "1.43.71", modules: { "boto3/__init__.py": "x = 1\n" }, topLevel: ["boto3"],
  })
  return { root, fallback, entryFiles }
}

function outputFor(name) {
  return path.join(mkdtempSync(path.join(tmpdir(), `hermes-out-${name}-`)), "artifact")
}

function expectBuildError(fn, code) {
  try {
    fn()
  } catch (error) {
    assert.equal(error.code, code, `expected ${code}, got ${error.code}: ${error.message}`)
    return
  }
  assert.fail(`expected ${code}`)
}

test("builds the closure, excludes extras and cache, and is deterministic", () => {
  const { root, fallback } = fixtureSource({ name: "happy" })
  const first = outputFor("happy-1")
  const second = outputFor("happy-2")
  const one = build({ output: first, source: root, fallbackSources: [fallback] })
  const two = build({ output: second, source: root, fallbackSources: [fallback] })
  assert.equal(one.treeDigest, two.treeDigest)
  assert.equal(one.entries, two.entries)
  assert.equal(one.bytes, two.bytes)
  assert.deepEqual(
    readFileSync(`${first}.manifest.json`, "utf8"),
    readFileSync(`${second}.manifest.json`, "utf8"),
    "two builds of one input must produce the same manifest",
  )
  assert.deepEqual(
    one.packages.map((item) => item.name).sort(),
    ["agent-client-protocol", "distro", "hermes-agent", "openai", "pydantic", "six"],
  )
  // Extras this artifact does not provide, and win32-only requirements, stay out.
  assert.ok(!one.packages.some((item) => item.name === "pytest"))
  assert.ok(!one.packages.some((item) => item.name === "tzdata"))
  assert.ok(one.excluded.extrasOnlyNames.includes("pytest"))
  assert.ok(one.excluded.win32OnlyRequirements.includes("tzdata"))
  // The unrelated reference contributes only its own exclusive packages.
  assert.deepEqual(one.excluded.unrelatedOnlyPackages, ["flask", "itsdangerous", "werkzeug"])
  assert.ok(!one.packages.some((item) => item.name === "boto3"))
  // The platform root is a declared fallback, and it is recorded per package.
  assert.deepEqual(
    one.packages.filter((item) => item.fallback).map((item) => item.name).sort(),
    ["distro", "six"],
  )
  assert.deepEqual(
    one.packages.filter((item) => item.filesFrom === "top-level").map((item) => item.name).sort(),
    ["six"],
  )
  // The entry point and the overlay files are where the deployment expects them.
  assert.equal(statSync(path.join(first, "site-packages", "hermes_cli", "main.py")).isFile(), true)
  const overlays = readFileSync(
    path.join(first, "site-packages", "agentbox_hermes_bootstrap.py"), "utf8",
  )
  assert.match(overlays, /AGENTBOX_HERMES_BOOTSTRAP_HOME_MISSING/)
  assert.match(readFileSync(path.join(first, "site-packages", "sitecustomize.py"), "utf8"), /agentbox_hermes_bootstrap/)
  assert.deepEqual(one.overlays.map((item) => item.name),
    ["agentbox_hermes_bootstrap.py", "sitecustomize.py"])
  // Read-only publication, owner marker, and no cache files anywhere.
  assert.equal(statSync(first).mode & 0o777, 0o555)
  assert.equal(statSync(path.join(first, "site-packages", "hermes_cli", "main.py")).mode & 0o777, 0o444)
  assert.match(readFileSync(path.join(first, ".agentbox-hermes-runtime-artifact"), "utf8"), /r1/)
  assert.equal(existsSync(path.join(first, "site-packages", "hermes_cli", "__pycache__")), false)
  assert.equal(existsSync(path.join(first, "site-packages", "boto3")), false)
})

test("a missing required dependency fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "missing" })
  rmSync(path.join(root, "openai-2.24.0.dist-info"), { recursive: true })
  expectBuildError(() => build({ output: outputFor("missing"), source: root, fallbackSources: [fallback] }),
    "HERMES_CLOSURE_DEPENDENCY_MISSING")
})

test("a version that does not satisfy its pin fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "drift" })
  // The installed distribution is 2.25.0 while the entry pins `==2.24.0`, and
  // the declared-deviation table does not cover it.
  const info = path.join(root, "openai-2.24.0.dist-info")
  writeFileSync(path.join(info, "METADATA"), metadataText("openai", "2.25.0", {
    requires: ['distro>=1.7.0,<2; sys_platform != "win32"', "six==1.16.0"],
  }))
  const renamed = path.join(root, "openai-2.25.0.dist-info")
  mkdirSync(renamed)
  rmSync(renamed, { recursive: true })
  // Move the metadata directory by walking it, so the dist-info name and the
  // declared version agree.
  mkdirSync(renamed)
  for (const item of ["METADATA", "top_level.txt", "RECORD"]) {
    const from = path.join(info, item)
    if (existsSync(from)) {
      writeFileSync(path.join(renamed, item), readFileSync(from, "utf8"))
      rmSync(from)
    }
  }
  rmSync(info, { recursive: true })
  expectBuildError(() => build({ output: outputFor("drift"), source: root, fallbackSources: [fallback] }),
    "HERMES_CLOSURE_VERSION_MISMATCH")
})

test("an entry version other than the pinned one fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "entry" })
  const info = path.join(root, "hermes_agent-0.19.0.dist-info")
  writeFileSync(path.join(info, "METADATA"), metadataText(ENTRY_DISTRIBUTION, "0.20.0", {
    requires: ["openai==2.24.0"], extras: ["acp"],
  }))
  expectBuildError(() => build({ output: outputFor("entry"), source: root, fallbackSources: [fallback] }),
    "HERMES_ENTRY_VERSION_MISMATCH")
})

test("a missing entry distribution fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "noentry" })
  rmSync(path.join(root, "hermes_agent-0.19.0.dist-info"), { recursive: true })
  expectBuildError(() => build({ output: outputFor("noentry"), source: root, fallbackSources: [fallback] }),
    "HERMES_CLOSURE_ENTRY_MISSING")
})

test("an entry extra that is not declared fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "noextra" })
  const info = path.join(root, "hermes_agent-0.19.0.dist-info")
  writeFileSync(path.join(info, "METADATA"), metadataText(ENTRY_DISTRIBUTION, "0.19.0", {
    requires: ["openai==2.24.0", 'agent-client-protocol==0.9.0; extra == "acp"'],
  }))
  expectBuildError(() => build({ output: outputFor("noextra"), source: root, fallbackSources: [fallback] }),
    "HERMES_CLOSURE_ENTRY_EXTRA_UNKNOWN")
})

test("a distribution the artifact does not provide an extra for stays out", () => {
  const { root, fallback } = fixtureSource({ name: "extraonly" })
  const info = path.join(root, "hermes_agent-0.19.0.dist-info")
  writeFileSync(path.join(info, "METADATA"), metadataText(ENTRY_DISTRIBUTION, "0.19.0", {
    requires: [
      "openai==2.24.0",
      'agent-client-protocol==0.9.0; extra == "acp"',
      'boto3==1.43.71; extra == "dev"',
    ],
    extras: ["acp", "dev"],
  }))
  const built = build({ output: outputFor("extraonly"), source: root, fallbackSources: [fallback] })
  assert.ok(!built.packages.some((item) => item.name === "boto3"))
  assert.ok(built.excluded.extrasOnlyNames.includes("boto3"))
})

test("the unrelated-tool probe names what it would have caught", () => {
  const { root, fallback } = fixtureSource({ name: "unrelated" })
  const built = build({ output: outputFor("unrelated"), source: root, fallbackSources: [fallback] })
  // flask is installed with its own exclusive closure; the probe records every
  // distribution that belongs only to it, and none of them is in the artifact.
  assert.deepEqual(built.excluded.unrelatedOnlyPackages, ["flask", "itsdangerous", "werkzeug"])
  const selectedNames = new Set(built.packages.map((item) => item.name))
  for (const name of built.excluded.unrelatedOnlyPackages) {
    assert.ok(!selectedNames.has(name), `${name} must not be packaged`)
  }
  assert.deepEqual(built.excluded.extrasDelta, ["agent-client-protocol", "pydantic"])
})

test("a direct reference in the metadata fails loudly", () => {
  // A requirement that names a URL cannot be resolved from installed
  // distributions, and it may not be silently skipped either.
  const { root, fallback } = fixtureSource({ name: "direct" })
  const info = path.join(root, "hermes_agent-0.19.0.dist-info")
  writeFileSync(path.join(info, "METADATA"), metadataText(ENTRY_DISTRIBUTION, "0.19.0", {
    requires: [
      "openai==2.24.0",
      'agent-client-protocol==0.9.0; extra == "acp"',
      'boto3 @ https://example.invalid/boto3-1.2.3-py3-none-any.whl; extra == "acp"',
    ],
    extras: ["acp"],
  }))
  expectBuildError(() => build({ output: outputFor("direct"), source: root, fallbackSources: [fallback] }),
    "HERMES_CLOSURE_DIRECT_REFERENCE_UNSUPPORTED")
})

test("the entry point must import the module its extra provides", () => {
  const { root, fallback } = fixtureSource({ name: "entryimport" })
  const entry = path.join(root, "hermes_cli", "main.py")
  writeFileSync(entry, "def main():\n    return 0\n")
  expectBuildError(() => build({ output: outputFor("entryimport"), source: root, fallbackSources: [fallback] }),
    "HERMES_CLOSURE_ENTRY_EXTRA_UNUSED")
})

test("a symlink in the closure fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "symlink" })
  symlinkSync("/etc/passwd", path.join(root, "openai", "escape.py"))
  const record = path.join(root, "openai-2.24.0.dist-info", "RECORD")
  writeFileSync(record, readFileSync(record, "utf8") + "openai/escape.py,sha256:0,9\n")
  expectBuildError(() => build({ output: outputFor("symlink"), source: root, fallbackSources: [fallback] }),
    "HERMES_ARTIFACT_SHAPE_INVALID")
})

test("a special file in the closure fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "fifo" })
  execFileSync("mkfifo", [path.join(root, "openai", "pipe.py")])
  const record = path.join(root, "openai-2.24.0.dist-info", "RECORD")
  writeFileSync(record, readFileSync(record, "utf8") + "openai/pipe.py,sha256:0,0\n")
  expectBuildError(() => build({ output: outputFor("fifo"), source: root, fallbackSources: [fallback] }),
    "HERMES_ARTIFACT_SHAPE_INVALID")
})

test("a recorded file that is not installed fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "record" })
  const record = path.join(root, "openai-2.24.0.dist-info", "RECORD")
  writeFileSync(record, readFileSync(record, "utf8") + "openai/vanished.py,sha256:0,3\n")
  writeFileSync(path.join(root, "openai", "vanished.py"), "x = 1\n")
  rmSync(path.join(root, "openai", "vanished.py"))
  expectBuildError(() => build({ output: outputFor("record"), source: root, fallbackSources: [fallback] }),
    "HERMES_SOURCE_FILE_MISSING")
})

test("a distribution with neither RECORD nor top_level fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "norecord" })
  rmSync(path.join(root, "openai-2.24.0.dist-info", "RECORD"))
  rmSync(path.join(root, "openai-2.24.0.dist-info", "top_level.txt"))
  expectBuildError(() => build({ output: outputFor("norecord"), source: root, fallbackSources: [fallback] }),
    "HERMES_SOURCE_RECORD_MISSING")
})

test("two paths that differ only by case are refused", () => {
  const { root, fallback } = fixtureSource({ name: "case" })
  const record = path.join(root, "openai-2.24.0.dist-info", "RECORD")
  writeFileSync(path.join(root, "openai", "Case.py"), "a = 1\n")
  writeFileSync(path.join(root, "openai", "case.py"), "b = 2\n")
  writeFileSync(record, readFileSync(record, "utf8")
    + "openai/Case.py,sha256:0,6\nopenai/case.py,sha256:0,6\n")
  expectBuildError(() => build({ output: outputFor("case"), source: root, fallbackSources: [fallback] }),
    "HERMES_ARTIFACT_PATH_CONFLICT")
})

test("a tree beyond the artifact byte bound fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "bounds" })
  const oversized = path.join(root, "openai", "huge.bin")
  execFileSync("truncate", ["-s", String(1024 * 1024 * 1024 + 1), oversized])
  const record = path.join(root, "openai-2.24.0.dist-info", "RECORD")
  writeFileSync(record, readFileSync(record, "utf8")
    + `openai/huge.bin,sha256:0,${1024 * 1024 * 1024 + 1}\n`)
  expectBuildError(() => build({ output: outputFor("bounds"), source: root, fallbackSources: [fallback] }),
    "HERMES_ARTIFACT_OUTSIDE_BOUNDS")
})

test("output policy refuses the repository, relative paths and user config roots", () => {
  const { root, fallback } = fixtureSource({ name: "policy" })
  expectBuildError(() => build({ output: "relative/artifact", source: root, fallbackSources: [fallback] }),
    "HERMES_OUTPUT_NOT_ABSOLUTE")
  expectBuildError(() => build({ output: path.join(REPO, "artifact"), source: root, fallbackSources: [fallback] }),
    "HERMES_OUTPUT_INSIDE_REPOSITORY")
  expectBuildError(() => build({
    output: path.join(process.env.HOME, ".hermes", "artifact"), source: root, fallbackSources: [fallback],
  }), "HERMES_OUTPUT_RESERVED")
  expectBuildError(() => build({ output: "/", source: root, fallbackSources: [fallback] }), "HERMES_OUTPUT_UNSAFE")
})

test("an unmarked output is never deleted, and an owned one needs --replace", () => {
  const { root, fallback } = fixtureSource({ name: "target" })
  const output = outputFor("target")
  mkdirSync(output)
  const keep = path.join(output, "user-file")
  writeFileSync(keep, "must survive")
  expectBuildError(() => build({ output, source: root, fallbackSources: [fallback] }), "HERMES_OUTPUT_NOT_OWNED")
  assert.equal(readFileSync(keep, "utf8"), "must survive")

  rmSync(keep)
  build({ output, source: root, fallbackSources: [fallback] })
  expectBuildError(() => build({ output, source: root, fallbackSources: [fallback] }), "HERMES_OUTPUT_EXISTS")
  const rebuilt = build({ output, source: root, fallbackSources: [fallback], replace: true })
  assert.match(rebuilt.treeDigest, /^sha256:[0-9a-f]{64}$/)
  assert.equal(statSync(output).mode & 0o777, 0o555)
})

test("a source root that is not an installed-package directory fails loudly", () => {
  const { root, fallback } = fixtureSource({ name: "source" })
  expectBuildError(() => build({
    output: outputFor("source"), source: path.join(root, "no-such-root"), fallbackSources: [fallback],
  }), "HERMES_SOURCE_INVALID")
})

// -- where the source comes from ---------------------------------------------

/** The builder's CLI, run as a real process with a controlled environment. */
function runCli(args, { env = {}, inherit = true } = {}) {
  const childEnv = { ...(inherit ? process.env : {}) , ...env }
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete childEnv[key]
  }
  const result = spawnSync(process.execPath, [
    path.join(import.meta.dirname, "build-hermes-runtime-artifact.mjs"), ...args,
  ], { encoding: "utf8", env: childEnv })
  assert.equal(result.error, undefined, `the builder did not run: ${result.error}`)
  return { status: result.status, report: JSON.parse(result.stdout.trim().split("\n").at(-1)) }
}

test("with no source at all the build refuses and names the variable", () => {
  const { root, fallback } = fixtureSource({ name: "unset" })
  const output = outputFor("unset")
  let message = ""
  try {
    build({ output, fallbackSources: [fallback], env: {} })
    assert.fail("expected a refusal without a declared source")
  } catch (error) {
    assert.equal(error.code, "HERMES_SOURCE_UNSET")
    message = error.message
  }
  // The message must tell the operator exactly what to set, and must not point
  // at some other machine's path or a binary as if either were a source.
  assert.match(message, new RegExp(SOURCE_ENVIRONMENT_VARIABLE))
  assert.match(message, /--source/)
  assert.doesNotMatch(message, /\/(home|root|usr|opt|tmp|mnt)\//, "the refusal must not name a path to fall back to")
  // Fail-closed: the refusal happens before any output is touched.
  assert.equal(existsSync(output), false)
  // Non-vacuity: the same fixture builds the moment the variable is declared.
  const declared = build({ output, fallbackSources: [fallback], env: { [SOURCE_ENVIRONMENT_VARIABLE]: root } })
  assert.deepEqual(declared.entry.sourceRoots, [root, fallback])
})

test("resolveSource prefers an explicit source and otherwise only the variable", () => {
  const env = { [SOURCE_ENVIRONMENT_VARIABLE]: "/declared/site-packages" }
  assert.equal(resolveSource("/explicit/site-packages", { env }), "/explicit/site-packages")
  assert.equal(resolveSource(undefined, { env }), "/declared/site-packages")
  assert.equal(resolveSource("   ", { env }), "/declared/site-packages")
  // Unset and blank are the same refusal; neither yields a guessed path.
  for (const declared of [undefined, "", "   "]) {
    assert.throws(() => resolveSource(undefined, { env: { [SOURCE_ENVIRONMENT_VARIABLE]: declared } }),
      (error) => error.code === "HERMES_SOURCE_UNSET"
        && error.message.includes(SOURCE_ENVIRONMENT_VARIABLE))
  }
})

test("an explicit source is honoured even when the variable points elsewhere", () => {
  const { root, fallback } = fixtureSource({ name: "explicit" })
  // The variable names the fallback root, which holds no hermes-agent at all.
  const env = { [SOURCE_ENVIRONMENT_VARIABLE]: fallback }
  // Control: with only the variable, the build refuses - so a later success
  // cannot be explained by the variable happening to be usable.
  expectBuildError(() => build({
    output: outputFor("explicit-env"), fallbackSources: [fallback], env,
  }), "HERMES_CLOSURE_ENTRY_MISSING")
  const built = build({ output: outputFor("explicit-source"), source: root, fallbackSources: [fallback], env })
  assert.deepEqual(built.entry.sourceRoots, [root, fallback])
  assert.equal(built.entry.package, ENTRY_DISTRIBUTION)
})

test("the CLI refuses without --source or the variable, and builds with either", () => {
  const { root, fallback } = fixtureSource({ name: "cli" })
  const refused = runCli(["--output", outputFor("cli-unset"), "--fallback-source", fallback, "--json"],
    { env: { [SOURCE_ENVIRONMENT_VARIABLE]: undefined } })
  assert.equal(refused.status, 1)
  assert.equal(refused.report.code, "HERMES_SOURCE_UNSET")
  assert.ok(refused.report.error.includes(SOURCE_ENVIRONMENT_VARIABLE), refused.report.error)

  const declared = outputFor("cli-env")
  const fromVariable = runCli(["--output", declared, "--fallback-source", fallback, "--no-self-check", "--json"],
    { env: { [SOURCE_ENVIRONMENT_VARIABLE]: root } })
  assert.equal(fromVariable.status, 0, fromVariable.report.error ?? "")
  assert.equal(fromVariable.report.result, "HERMES_RUNTIME_ARTIFACT_BUILT")
  assert.match(fromVariable.report.treeDigest, /^sha256:[0-9a-f]{64}$/)

  // --source still works on its own, and takes precedence over the variable.
  const explicit = outputFor("cli-source")
  const fromArgument = runCli(["--output", explicit, "--source", root, "--fallback-source", fallback,
    "--no-self-check", "--json"], { env: { [SOURCE_ENVIRONMENT_VARIABLE]: fallback } })
  assert.equal(fromArgument.status, 0, fromArgument.report.error ?? "")
  assert.equal(fromArgument.report.treeDigest, fromVariable.report.treeDigest)
})

test("an unset variable is never filled in from PATH or from the home directory", () => {
  const { root, fallback } = fixtureSource({ name: "no-guess" })
  const bin = mkdtempSync(path.join(tmpdir(), "hermes-bin-"))
  const sentinel = path.join(bin, "ran")
  // A `hermes` binary first on PATH that records that it was executed, plus HOME
  // pointing at a directory that holds a complete installed-package set. The
  // real PATH follows, because the reviewed digest itself runs `python3`.
  writeFileSync(path.join(bin, "hermes"), `#!/bin/sh\ntouch ${JSON.stringify(sentinel)}\nexit 0\n`, { mode: 0o755 })
  const pathWithBinary = `${bin}${path.delimiter}${process.env.PATH ?? ""}`
  const output = outputFor("no-guess")
  const refused = runCli(["--output", output, "--fallback-source", fallback, "--json"],
    { env: { [SOURCE_ENVIRONMENT_VARIABLE]: undefined, PATH: pathWithBinary, HOME: root } })
  assert.equal(refused.status, 1)
  assert.equal(refused.report.code, "HERMES_SOURCE_UNSET")
  // Neither the executable nor the home directory was used as the source.
  assert.equal(existsSync(sentinel), false, "the builder must not run a hermes binary from PATH")
  assert.equal(existsSync(output), false, "a refused build must not create its output")
  // Non-vacuity: the same environment builds once the variable is declared.
  // HOME is a directory without any installed packages here, so the success
  // comes from the declared variable and from nowhere else.
  const declared = runCli(["--output", outputFor("no-guess-ok"), "--fallback-source", fallback, "--no-self-check", "--json"],
    { env: { PATH: pathWithBinary, HOME: mkdtempSync(path.join(tmpdir(), "hermes-home-")), [SOURCE_ENVIRONMENT_VARIABLE]: root } })
  assert.equal(declared.status, 0, declared.report.error ?? "")
  assert.equal(existsSync(sentinel), false)
})

test("the builder carries no machine-local default source", () => {
  const source = readFileSync(new URL("./build-hermes-runtime-artifact.mjs", import.meta.url), "utf8")
  // The defect under repair: one developer's home directory baked in as a
  // default, which made the builder build from a path that exists on one
  // machine only. No literal per-user path may appear at all.
  assert.doesNotMatch(source, /["'`]\/home\/[^"'`\s]*["'`]/, "no machine-local home path may be hardcoded")
  assert.doesNotMatch(source, /\/Users\/[^"'`\s]*/, "no macOS per-user path may be hardcoded")
  assert.doesNotMatch(source, /DEFAULT_SOURCE/, "the hardcoded default source constant must be gone")
  assert.match(source, /ORDESSA_HERMES_SOURCE/)
})

// -- what the source root itself may be --------------------------------------

test("a symlinked source root is refused", () => {
  const { root, fallback } = fixtureSource({ name: "symlink-root" })
  const link = path.join(mkdtempSync(path.join(tmpdir(), "hermes-link-")), "site-packages")
  symlinkSync(root, link)
  expectBuildError(() => build({ output: outputFor("symlink-root"), source: link, fallbackSources: [fallback] }),
    "HERMES_SOURCE_SYMLINK")
  // Non-vacuity: the directory the link points at is a perfectly good source.
  const built = build({ output: outputFor("symlink-target"), source: root, fallbackSources: [fallback] })
  assert.deepEqual(built.entry.sourceRoots, [root, fallback])
  // A symlinked fallback root is refused the same way, and says which one.
  const linkFallback = path.join(mkdtempSync(path.join(tmpdir(), "hermes-link-fb-")), "dist-packages")
  symlinkSync(fallback, linkFallback)
  try {
    build({ output: outputFor("symlink-fallback"), source: root, fallbackSources: [linkFallback] })
    assert.fail("expected a symlinked fallback root to be refused")
  } catch (error) {
    assert.equal(error.code, "HERMES_SOURCE_SYMLINK")
    assert.match(error.message, /--fallback-source/)
  }
})

test("a source path that escapes its declared root is refused", () => {
  const { root, fallback } = fixtureSource({ name: "escape" })
  // A traversal that resolves back into the fixture root is still an escape
  // attempt: it names a path the operator did not declare.
  const traversal = `${fallback}${path.sep}..${path.sep}${path.basename(root)}`
  assert.equal(path.resolve(traversal), root, "the fixture must actually resolve to the source root")
  expectBuildError(() => build({
    output: outputFor("escape"), source: traversal, fallbackSources: [fallback],
  }), "HERMES_SOURCE_ESCAPES_ROOT")
  // Non-vacuity: the same directory, declared plainly, builds.
  assert.deepEqual(build({ output: outputFor("escape-ok"), source: root, fallbackSources: [fallback] })
    .entry.sourceRoots, [root, fallback])
  // Whole-filesystem and whole-home roots are refused outright.
  expectBuildError(() => build({ output: outputFor("escape-root"), source: "/", fallbackSources: [fallback] }),
    "HERMES_SOURCE_UNSAFE")
  expectBuildError(() => build({
    output: outputFor("escape-home"), source: root, fallbackSources: [fallback], env: { HOME: root },
  }), "HERMES_SOURCE_UNSAFE")
  expectBuildError(() => build({
    output: outputFor("escape-relative"), source: "site-packages", fallbackSources: [fallback],
  }), "HERMES_SOURCE_NOT_ABSOLUTE")
  // The guard itself is exported and behaves the same way on its own.
  assert.equal(assertSourcePolicy(`${root}${path.sep}.`), root)
  assert.throws(() => assertSourcePolicy(path.join(root, "no-such-root")),
    (error) => error.code === "HERMES_SOURCE_INVALID")
})

// -- output policy, checked at its own guard and through build() -------------

test("output policy is enforced before a source is read", () => {
  const { fallback } = fixtureSource({ name: "policy-order" })
  // The guard is the one the builder already had; nothing is added beside it.
  assert.equal(assertOutputPolicy(path.join(tmpdir(), "hermes-policy-ok")), path.join(tmpdir(), "hermes-policy-ok"))
  assert.throws(() => assertOutputPolicy("relative/artifact"),
    (error) => error.code === "HERMES_OUTPUT_NOT_ABSOLUTE")
  assert.throws(() => assertOutputPolicy(path.join(REPO, "artifact")),
    (error) => error.code === "HERMES_OUTPUT_INSIDE_REPOSITORY")
  assert.throws(() => assertOutputPolicy("/"),
    (error) => error.code === "HERMES_OUTPUT_UNSAFE")
  assert.throws(() => assertOutputPolicy(path.join(process.env.HOME, ".local", "artifact")),
    (error) => error.code === "HERMES_OUTPUT_RESERVED")
  // build() runs the output guard first: with no declared source at all, an
  // unusable output is still reported as an output failure, not as a source one.
  for (const [output, code] of [
    ["relative/artifact", "HERMES_OUTPUT_NOT_ABSOLUTE"],
    [path.join(REPO, "artifact"), "HERMES_OUTPUT_INSIDE_REPOSITORY"],
    ["/", "HERMES_OUTPUT_UNSAFE"],
  ]) {
    expectBuildError(() => build({ output, fallbackSources: [fallback], env: {} }), code)
  }
})

/** A fixture whose entry pins rich==14.3.3 and whose roots carry rich 15.0.0. */
function fixtureWithRichDeviation(name, where) {
  const { root, fallback } = fixtureSource({ name })
  // `rich==14.3.3` is the one entry in DECLARED_PIN_DEVIATIONS.
  writeFileSync(path.join(root, "hermes_agent-0.19.0.dist-info", "METADATA"),
    metadataText(ENTRY_DISTRIBUTION, "0.19.0", {
      requires: ["openai==2.24.0", "rich==14.3.3", 'agent-client-protocol==0.9.0; extra == "acp"'],
      extras: ["acp"],
    }))
  addDistribution(where === "fallback" ? fallback : root, {
    project: "rich", version: "15.0.0",
    modules: { "rich/__init__.py": "VERSION = '15.0.0'\n" }, topLevel: ["rich"],
  })
  return { root, fallback }
}

/**
 * A declared pin deviation is anchored to the source this build was told to
 * read, never to a path baked into the builder.
 */
test("a declared pin deviation applies only to the declared source root", () => {
  const { root, fallback } = fixtureWithRichDeviation("deviation", "primary")
  // The build declares `root` as its primary source, so the deviation is
  // recorded - against the root the package actually came from.
  const built = build({ output: outputFor("deviation"), source: root, fallbackSources: [fallback] })
  assert.deepEqual(built.pinDeviations.map((item) => [item.project, item.installed, item.root]),
    [["rich", "15.0.0", root]])
  const index = indexDistributions([root, fallback])
  assert.deepEqual(resolveClosure({ index, extras: ENTRY_EXTRAS, primaryRoot: root }).deviations
    .map((item) => [item.project, item.root]), [["rich", root]])
  // The same tree under a different declared source, or under none at all, is
  // an unsatisfied pin - a deviation never travels to a root nobody declared.
  for (const primaryRoot of [path.join(tmpdir(), "hermes-other-root-"), undefined]) {
    assert.throws(
      () => resolveClosure({ index, extras: ENTRY_EXTRAS, primaryRoot }),
      (error) => error.code === "HERMES_CLOSURE_VERSION_MISMATCH",
      `a declared deviation must not apply to ${primaryRoot}`,
    )
  }
  // And a rich installed only in a fallback root is refused outright, even
  // though the declared primary source is the same one as above.
  const elsewhere = fixtureWithRichDeviation("deviation-fallback", "fallback")
  expectBuildError(() => build({
    output: outputFor("deviation-fallback"), source: elsewhere.root, fallbackSources: [elsewhere.fallback],
  }), "HERMES_CLOSURE_VERSION_MISMATCH")
})

/**
 * The reviewed installed closure, when an operator has declared where Hermes is
 * installed. Skipped otherwise: this build refuses to guess that location, so
 * there is nothing to build without `ORDESSA_HERMES_SOURCE` (or `--source`).
 */
const REVIEWED_SOURCE = process.env[SOURCE_ENVIRONMENT_VARIABLE]

test("the reviewed installed closure builds and is self-contained", { skip: !REVIEWED_SOURCE }, () => {
  const output = outputFor("real")
  chmodSync(path.dirname(output), 0o755)
  const built = build({ output, fallbackSources: DEFAULT_FALLBACK_SOURCES })
  assert.equal(built.entry.package, ENTRY_DISTRIBUTION)
  assert.match(built.treeDigest, /^sha256:[0-9a-f]{64}$/)
  assert.ok(built.packages.some((item) => item.name === "agent-client-protocol"),
    "the entry point's own extra must be in the artifact")
  assert.deepEqual(built.entry.extras, ["acp"])
  assert.equal(built.packages.find((item) => item.name === ENTRY_DISTRIBUTION).version, "0.19.0")
  const resolved = selfCheck(output)
  for (const location of Object.values(resolved)) {
    assert.ok(String(location).startsWith(path.join(output, "site-packages") + path.sep),
      `${location} must resolve inside the artifact`)
  }
})
