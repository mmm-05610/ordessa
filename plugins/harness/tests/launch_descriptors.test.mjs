import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import {
  harnessLaunchContext, registryIdentityVersionMatches, isKnownHarness,
  listCanonicalHarnesses, listHarnesses, parseLaunchDescriptors,
} from "../harnesses/index.mjs"

const descriptorURL = new URL("../src/ordessa_harness/launch-descriptors.json", import.meta.url)
const source = JSON.parse(readFileSync(descriptorURL, "utf8"))

test("canonical source has eight brands; aliases remain launchable, not brands", () => {
  assert.deepEqual(listCanonicalHarnesses(),
    ["claude-code", "codex", "dsh", "hermes", "kilo", "opencode", "pi", "qwen"])
  assert.equal(listHarnesses().length, 9)
  assert.equal(isKnownHarness("claude"), true)
  assert.equal(isKnownHarness("omp"), true)
  assert.equal(isKnownHarness("opencode"), false) // no JS ACP launch route yet
  assert.equal(registryIdentityVersionMatches("codex", "2.0"), true)
  assert.equal(registryIdentityVersionMatches("codex", "999.0"), false)
  assert.equal(registryIdentityVersionMatches("codex", undefined), null)
  assert.equal(registryIdentityVersionMatches("omp", "2.0"), null)
})

test("alias routes preserve their existing upstream and managed launches", () => {
  const find = () => null
  assert.equal(harnessLaunchContext("claude", { find }).origin, "upstream")
  assert.equal(harnessLaunchContext("claude", { find }).command, "npx")
  assert.equal(harnessLaunchContext("claude-code", { find }).origin, "agentbox")
  assert.equal(harnessLaunchContext("omp", { find }).command, "omp")
  assert.deepEqual(harnessLaunchContext("dsh", { find }).args, ["--profile", "acp"])
  assert.throws(() => harnessLaunchContext("opencode"), /HARNESS_UNDISCOVERED/)
})

test("manifest rejects alias as second brand and malformed routes", () => {
  const secondBrand = structuredClone(source)
  secondBrand.harnesses.push({ ...secondBrand.harnesses[0], id: "claude", aliases: [] })
  assert.throws(() => parseLaunchDescriptors(JSON.stringify(secondBrand)), /alias is second brand|duplicate canonical/)
  const badRoute = structuredClone(source)
  badRoute.harnesses[0].launch.source = "shell"
  assert.throws(() => parseLaunchDescriptors(JSON.stringify(badRoute)), /INVALID_LAUNCH_DESCRIPTOR/)
  const crossBrand = structuredClone(source)
  crossBrand.harnesses[0].launch.profile_id = "pi"
  assert.throws(() => parseLaunchDescriptors(JSON.stringify(crossBrand)), /profile identity mismatch/)
  const crossAlias = structuredClone(source)
  crossAlias.harnesses[1].aliases[0].launch.profile_id = "codex"
  assert.throws(() => parseLaunchDescriptors(JSON.stringify(crossAlias)), /profile identity mismatch/)
  const booleanVersion = structuredClone(source)
  booleanVersion.schema_version = true
  assert.throws(() => parseLaunchDescriptors(JSON.stringify(booleanVersion)), /INVALID_LAUNCH_DESCRIPTOR/)
})
