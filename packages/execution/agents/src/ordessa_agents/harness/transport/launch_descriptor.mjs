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

