import { stageBuilderModuleClosure } from "../support/builder_dependency_fixture.mjs"
/** Exercise the real Python digest through each builder after the monorepo move. */
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import { copyFileSync, existsSync, readdirSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"
import test from "node:test"

const BRANDS = ["codex", "pi", "claude", "dsh", "qwen", "kilo", "hermes"]
const HERE = import.meta.dirname
const BUILDERS = Object.freeze({"codex":new URL("../../../plugins/harness/codex/tooling/build-runtime-artifact.mjs",import.meta.url),"claude":new URL("../../../plugins/harness/claude-code/tooling/build-runtime-artifact.mjs",import.meta.url),"pi":new URL("../../../plugins/harness/pi/tooling/build-runtime-artifact.mjs",import.meta.url),"dsh":new URL("../../../plugins/harness/dsh/tooling/build-runtime-artifact.mjs",import.meta.url),"qwen":new URL("../../../plugins/harness/qwen/tooling/build-runtime-artifact.mjs",import.meta.url),"kilo":new URL("../../../plugins/harness/kilo/tooling/build-runtime-artifact.mjs",import.meta.url),"hermes":new URL("../../../plugins/harness/hermes/tooling/build-runtime-artifact.mjs",import.meta.url),"opencode":new URL("../../../plugins/harness/opencode/tooling/build-runtime-artifact.mjs",import.meta.url)})
const sourceRoot = path.resolve(HERE,"../../..")
const python = execFileSync("python3", ["-c", "import sys; print(sys.executable)"], { encoding: "utf8" }).trim()

function summarize(builder, directory, interpreterBin) {
  return JSON.parse(execFileSync(process.execPath, ["--input-type=module", "-e", `
    const { treeSummary } = await import(${JSON.stringify(pathToFileURL(builder).href)});
    console.log(JSON.stringify(treeSummary(${JSON.stringify(directory)})));
  `], {
    encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PATH: interpreterBin, PYTHONPATH: "", PYTHONNOUSERSITE: "1" },
  }))
}

// Independent encoding of one regular file, according to the runtime-artifact v1 contract.
function expectedDigest(name, content) {
  const count = Buffer.alloc(8); count.writeBigUInt64BE(1n)
  const nameBytes = Buffer.from(name)
  const nameLength = Buffer.alloc(4); nameLength.writeUInt32BE(nameBytes.length)
  const size = Buffer.alloc(8); size.writeBigUInt64BE(BigInt(Buffer.byteLength(content)))
  return "sha256:" + createHash("sha256").update(Buffer.concat([
    Buffer.from("agentbox-runtime-artifact-tree-v1\n"), count, Buffer.from("f"),
    nameLength, nameBytes, size, createHash("sha256").update(content).digest(),
  ])).digest("hex")
}

for (const brand of BRANDS) {
  test(`${brand}: current monorepo imports compute a real digest and fail closed`, () => {
    const scratch = mkdtempSync(path.join(tmpdir(), `ordessa-${brand}-digest-path-`))
    try {
      const directory = path.join(scratch, "fixture")
      const bin = path.join(scratch, "bin")
      mkdirSync(directory); mkdirSync(bin)
      // -S prevents editable installs/user sites from masking a missing source dependency.
      const quotedPython = "'" + python.replaceAll("'", "'\\''") + "'"
      writeFileSync(path.join(bin, "python3"), `#!/bin/sh\nexec ${quotedPython} -S "$@"\n`, { mode: 0o755 })
      const content = "export default 1\n"
      writeFileSync(path.join(directory, "entry.js"), content)
      const builder = BUILDERS[brand].pathname
      assert.deepEqual(summarize(builder, directory, bin), {
        digest: expectedDigest("entry.js", content), entries: 1, bytes: Buffer.byteLength(content),
      })
      writeFileSync(path.join(directory, "entry.js"), "changed\n")
      assert.notEqual(summarize(builder, directory, bin).digest, expectedDigest("entry.js", content))
      symlinkSync("entry.js", path.join(directory, "escape.js"))
      assert.throws(() => summarize(builder, directory, bin), (error) => {
        assert.match(error.stderr.toString(), new RegExp(`${brand.toUpperCase()}_ARTIFACT_DIGEST_UNAVAILABLE`))
        assert.match(error.stderr.toString(), /RUNTIME_ARTIFACT_ENTRY_INVALID/)
        return true
      })
      // A relocated builder with no source packages must refuse; it cannot use a legacy install.
      const emptyRoot = path.join(scratch,'empty-repo')
      const missingDependencyBuilder = stageBuilderModuleClosure(sourceRoot,builder,emptyRoot)
      // JS resources now share the owner directory and can create a Python namespace.
      // The complete Python implementation must still be absent in this counterexample.
      const pythonFiles = root => readdirSync(root, { withFileTypes: true }).flatMap(item => {
        const member = path.join(root, item.name)
        return item.isDirectory() ? pythonFiles(member) : /\.pyc?$/u.test(item.name) ? [member] : []
      })
      assert.deepEqual(pythonFiles(emptyRoot), [])
      const namespace = path.join(emptyRoot, 'packages/execution/agents/src/ordessa_execution_agents')
      const expectedMissing = existsSync(namespace)
        ? 'ordessa_execution_agents.harness.providers' : 'ordessa_execution_agents'
      assert.equal(existsSync(path.join(namespace, '__init__.py')), false)
      assert.equal(existsSync(path.join(namespace, 'harness/providers/resolution/artifacts/tree_identity.py')), false)
      assert.throws(() => summarize(missingDependencyBuilder, directory, bin), (error) => {
        assert.match(error.stderr.toString(), new RegExp(`${brand.toUpperCase()}_ARTIFACT_DIGEST_UNAVAILABLE`))
        const missing = error.stderr.toString().match(/ModuleNotFoundError: No module named '([^']+)'/u)
        assert.ok(missing, 'the original missing-Python dependency diagnosis must remain explicit')
        assert.equal(missing[1], expectedMissing)
        return true
      })
    } finally {
      rmSync(scratch, { recursive: true, force: true })
    }
  })
}
