/** ACP launch discovery shares canonical/alias descriptors with Python. */
import { readFileSync } from "node:fs"
import { resolveAcpLaunch, harnessProfile } from "../third_party/harness_remote/bridge/src/harness-profiles.js"
import { AGENTBOX_HARNESS_PROFILES } from "../runtime/profile_extensions.mjs"

const DESCRIPTOR_URL = new URL("../src/ordessa_harness/launch-descriptors.json", import.meta.url)

function routeIsValid(route, required = false) {
  if (route === null && !required) return true
  return route !== null && typeof route === "object" && !Array.isArray(route)
    && Object.keys(route).sort().join(",") === "profile_id,source"
    && ["upstream", "agentbox"].includes(route.source)
    && typeof route.profile_id === "string" && route.profile_id.length > 0
}

function requireOwnProfile(route, ownerID) {
  if (route && route.profile_id !== ownerID) {
    throw new Error("INVALID_LAUNCH_DESCRIPTOR: profile identity mismatch")
  }
}

export function parseLaunchDescriptors(text) {
  const raw = JSON.parse(text)
  if (!raw || typeof raw !== "object" || Array.isArray(raw)
      || Object.keys(raw).sort().join(",") !== "harnesses,schema_version"
      || raw.schema_version !== 1 || !Array.isArray(raw.harnesses)
      || raw.harnesses.length === 0 || raw.harnesses.length > 16) {
    throw new Error("INVALID_LAUNCH_DESCRIPTOR: schema")
  }
  const canonical = new Map()
  const routes = new Map()
  const names = new Set()
  for (const entry of raw.harnesses) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)
        || Object.keys(entry).sort().join(",") !== "aliases,id,launch,registry_version"
        || typeof entry.id !== "string" || !entry.id
        || typeof entry.registry_version !== "string" || !entry.registry_version
        || !Array.isArray(entry.aliases) || !routeIsValid(entry.launch)) {
      throw new Error("INVALID_LAUNCH_DESCRIPTOR: entry")
    }
    if (names.has(entry.id)) throw new Error("INVALID_LAUNCH_DESCRIPTOR: duplicate canonical/alias")
    requireOwnProfile(entry.launch, entry.id)
    names.add(entry.id)
    canonical.set(entry.id, entry)
    if (entry.launch) routes.set(entry.id, { ...entry.launch, canonical: entry.id })
    for (const alias of entry.aliases) {
      if (!alias || typeof alias !== "object" || Array.isArray(alias)
          || Object.keys(alias).sort().join(",") !== "id,launch"
          || typeof alias.id !== "string" || !alias.id || !routeIsValid(alias.launch, true)) {
        throw new Error("INVALID_LAUNCH_DESCRIPTOR: alias")
      }
      if (names.has(alias.id)) throw new Error("INVALID_LAUNCH_DESCRIPTOR: alias is second brand")
      requireOwnProfile(alias.launch, alias.id)
      names.add(alias.id)
      routes.set(alias.id, { ...alias.launch, canonical: entry.id })
    }
  }
  return { canonical, routes }
}

const { canonical: CANONICAL, routes: ROUTES } = parseLaunchDescriptors(readFileSync(DESCRIPTOR_URL, "utf8"))

function profileFor(route) {
  const profile = route.source === "upstream"
    ? harnessProfile(route.profile_id)
    : AGENTBOX_HARNESS_PROFILES[route.profile_id]
  if (!profile) throw new Error(`INVALID_LAUNCH_DESCRIPTOR: missing profile ${route.profile_id}`)
  return profile
}

for (const route of ROUTES.values()) profileFor(route)

/** ACP discovery preserves its historical nine launchable IDs. */
export function listHarnesses() {
  return [...ROUTES.keys()].sort()
}

export function listCanonicalHarnesses() {
  return [...CANONICAL.keys()].sort()
}

export function isKnownHarness(id) {
  return ROUTES.has(id)
}

/** Declaration equality only; does not inspect installed native/adapter versions. */
export function registryIdentityVersionMatches(id, version) {
  const descriptor = CANONICAL.get(id)
  if (!descriptor && ROUTES.has(id)) return null // alias has its own launch pin
  if (!descriptor) return false
  if (version == null) return null
  return version === descriptor.registry_version
}

export function harnessLaunchContext(id, { find } = {}) {
  const route = ROUTES.get(id)
  if (!route) throw new Error(`HARNESS_UNDISCOVERED: ${id}`)
  const profile = profileFor(route)
  return {
    harness: id,
    origin: route.source,
    label: profile.label ?? id,
    ...resolveAcpLaunch(profile, find ? { find } : {}),
  }
}
