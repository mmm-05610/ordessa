import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import { fileURLToPath } from "node:url"
import { captureLaunchCatalog } from "../../../src/ordessa_server/composition/native_channels/launch_catalog.mjs"
import {
  selectedLaunchPorts,
  selectedLaunchProvenancePorts,
} from "../../../src/ordessa_server/composition/native_channels/selected_launch_ports.mjs"
import { bindLaunchPolicy } from "../../../src/ordessa_server/composition/native_channels/launch_policy.mjs"

const selectedPortsPath = fileURLToPath(new URL(
  "../../../src/ordessa_server/composition/native_channels/selected_launch_ports.mjs",
  import.meta.url,
))

test("Pi's old npx launch is explicitly unavailable and cannot fall back", () => {
  const source = readFileSync(selectedPortsPath, "utf8")
  assert.doesNotMatch(source, /launch_pi\.mjs|@automatalabs\/pi-acp/)

  const declarations = new Map(selectedLaunchPorts.map((port) => {
    const value = port()
    return [value.id, value]
  }))
  const pi = declarations.get("pi")
  assert.equal(pi.unavailableReason, "PI_PUBLIC_UNIT_LAUNCH_PORT_UNBOUND")
  assert.equal(pi.profile.id, "pi")
  assert.equal(pi.managed, null)
  assert.equal(pi.legacy, null)
  assert.deepEqual(pi.variants, {})
  assert.equal(pi.profileExtension, null)
  assert.equal(selectedLaunchProvenancePorts[
    selectedLaunchPorts.findIndex((port) => port().id === "pi")
  ](), null)

  const catalog = captureLaunchCatalog(JSON.stringify({
    schema_version: 1,
    harnesses: [{
      id: "pi",
      registry_version: "2.0",
      launch: { source: "upstream", profile_id: "pi" },
      aliases: [],
    }],
  }), selectedLaunchPorts)
  const { installedLaunchReference } = bindLaunchPolicy(catalog)
  assert.throws(
    () => installedLaunchReference("pi", "/runtime/artifacts"),
    (error) => error.code === "ADAPTER_ROUTE_UNBOUND",
  )
})

test("Codex and Claude selected launch providers remain available", () => {
  const declarations = new Map(selectedLaunchPorts.map((port) => {
    const value = port()
    return [value.id, value]
  }))
  for (const id of ["codex", "claude-code"]) {
    const declaration = declarations.get(id)
    assert.equal(declaration.profile.id, id)
    assert.equal(typeof declaration.managed.package, "string")
    assert.equal(typeof declaration.variants.default.entry, "string")
  }
})
