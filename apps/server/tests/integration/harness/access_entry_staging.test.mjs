import { stageAccessEntry, stageAccessEntryManifest } from "../../support/stage_access_entry.mjs"
import { capturedLaunchEnvironment } from "../../support/captured_launch.mjs"
import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { appendFileSync, cpSync, mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import test from "node:test"

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../..")
test("staged access entry has its descriptor and answers discovery", () => {
  assert.equal(typeof stageAccessEntry, "function")
  assert.equal(typeof capturedLaunchEnvironment().ORDESSA_CAPTURED_LAUNCH_DESCRIPTORS, "string")
  const root = mkdtempSync(path.join(tmpdir(), "ordessa-harness-stage-"))
  try {
    const manifest = stageAccessEntryManifest(path.join(root, "bundle"))
    assert.equal(manifest.schema_version, 1)
    assert(manifest.required.includes("apps/server/src/ordessa_server/composition/native_channels/launch_catalog.mjs"))
    for (const relative of manifest.required) {
      assert(!path.isAbsolute(relative) && !relative.split("/").includes(".."))
      assert(readFileSync(path.join(root, "bundle", relative)).length > 0)
    }
    const entry = manifest.entry
    const run = spawnSync(process.execPath, [entry, "--native"], {
      cwd: root, env: capturedLaunchEnvironment(),
      input: '{"id":"discovery","op":"harnesses"}\n',
      encoding: "utf8",
      timeout: 10000,
    })
    assert.equal(run.status, 0, run.stderr)
    const answer = run.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))
      .find((row) => row.id === "discovery")
    assert.equal(answer?.ok, true, run.stdout)
    assert(answer.result.harnesses.includes("claude"))
    assert(answer.result.harnesses.includes("claude-code"))
    assert(answer.result.harnesses.includes("omp"))
    const sourcePeer = path.resolve(repoRoot, "tests", "integration", "acp_orchestration",
      "fixtures", "bidirectional_acp_peer.mjs")
    // The staged entry pins the same content digests as the source checkout
    // (spec 019: the allowlist locks content, not location), so the source
    // checkout's peer file is accepted from a path outside the staged closure.
    // What the stage must still refuse is *content that does not match* — a
    // one-byte tamper below — and content that matches an entry bound to a
    // different brand.
    const controlled = spawnSync(process.execPath, [entry, "--native", "--controlled-test-peer"], {
      cwd: root,
      env: capturedLaunchEnvironment({ AGENTBOX_ACCESS_TEST_MODE: "controlled-peer-v1",
        HD003_LOG: path.join(root, "peer-log") }),
      input: JSON.stringify({ id: "staged-peer", op: "connect", harness: "pi",
        launch: { command: process.execPath, args: [sourcePeer] }, directory: root }) + "\n"
        + JSON.stringify({ id: "staged-release", op: "close" }) + "\n",
      encoding: "utf8", timeout: 10000,
    })
    assert.equal(controlled.status, 0, controlled.stderr)
    const stagedLines = controlled.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))
    const stagedAnswer = stagedLines.find((row) => row.id === "staged-peer")
    assert.equal(stagedAnswer?.ok, true, controlled.stdout)
    assert.equal(stagedAnswer?.result?.launch?.source, "controlled-test-peer")
    const release = stagedLines.find((row) => row.id === "staged-release")
    assert.equal(release?.result?.released, true, controlled.stdout)
    const tampered = path.join(root, "tampered-peer.mjs")
    cpSync(sourcePeer, tampered)
    appendFileSync(tampered, "\n// one comment line of changed content\n")
    const refusal = spawnSync(process.execPath, [entry, "--native", "--controlled-test-peer"], {
      cwd: root,
      env: capturedLaunchEnvironment({ AGENTBOX_ACCESS_TEST_MODE: "controlled-peer-v1" }),
      input: JSON.stringify({ id: "tampered-peer", op: "connect", harness: "pi",
        launch: { command: process.execPath, args: [tampered] }, directory: root }) + "\n",
      encoding: "utf8", timeout: 10000,
    })
    assert.equal(refusal.status, 0, refusal.stderr)
    const tamperLines = refusal.stdout.split("\n").filter(Boolean).map((line) => JSON.parse(line))
    assert.equal(tamperLines.find((row) => row.id === "tampered-peer")?.error?.code,
      "CONTROLLED_PEER_MISMATCH",
      "a one-byte content change refuses the peer in a staged artifact too")
    const missingEnvironment = capturedLaunchEnvironment()
    delete missingEnvironment.ORDESSA_CAPTURED_LAUNCH_DESCRIPTORS
    const missing = spawnSync(process.execPath, [entry, "--native"], {
      cwd: root, env: missingEnvironment, input: '{"id":"discovery","op":"harnesses"}\n',
      encoding: "utf8", timeout: 10000,
    })
    assert.notEqual(missing.status, 0, "a stage missing the descriptor must not advertise brands")
    assert.match(missing.stderr, /CAPTURED_LAUNCH_REQUIRED/)
    assert.doesNotMatch(missing.stdout, /"ok":true/, "a stage missing captured declarations must not advertise brands")
    assert.match(missing.stdout, /CAPTURED_LAUNCH_REQUIRED/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

// Real production staging guard; malformed public resource routes must reject before copying outside the destination.
for (const logical of ["/absolute-resource", "../escaped-resource", "apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs"]) {
  test(`staging refuses malformed or duplicate declared resource ${logical}`, () => {
    const destination = mkdtempSync(path.join(tmpdir(), "ordessa-stage-refusal-"))
    try {
      const program = "from pathlib import Path; import sys; import ordessa_server.composition.native_channels.access_bundle as b; from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog; b.selected_acp_resources=lambda: ((str(Path(sys.argv[2]).parent),((Path(sys.argv[2]).name,Path(sys.executable)),)),); b.stage_access_entry(Path(sys.argv[1]),capture_selected_harness_catalog())"
      const refusal = spawnSync(process.env.ORDESSA_TEST_PYTHON,["-c",program,path.join(destination,"bundle"),logical],{encoding:"utf8",cwd:repoRoot})
      assert.notEqual(refusal.status,0)
      assert.match(refusal.stderr,/invalid explicit ACP resource mapping/)
    } finally { rmSync(destination,{recursive:true,force:true}) }
  })
}
