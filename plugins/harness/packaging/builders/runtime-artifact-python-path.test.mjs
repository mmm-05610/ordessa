/** Exercise the real Python digest through each builder after the monorepo move. */
import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { createHash } from "node:crypto"
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"
import test from "node:test"

const BRANDS = ["codex", "pi", "claude", "dsh", "qwen", "kilo", "hermes"]
const HERE = import.meta.dirname
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
      const builder = path.join(HERE, `build-${brand}-runtime-artifact.mjs`)
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
      const relocated = path.join(scratch, "empty-repo", "plugins", "harness", "packaging", "builders")
      mkdirSync(relocated, { recursive: true })
      const missingDependencyBuilder = path.join(relocated, path.basename(builder))
      copyFileSync(builder, missingDependencyBuilder)
      assert.throws(() => summarize(missingDependencyBuilder, directory, bin), (error) => {
        assert.match(error.stderr.toString(), new RegExp(`${brand.toUpperCase()}_ARTIFACT_DIGEST_UNAVAILABLE`))
        assert.match(error.stderr.toString(), /No module named 'pacthold_runtime_compat'/)
        return true
      })
    } finally {
      rmSync(scratch, { recursive: true, force: true })
    }
  })
}
