import { parseLaunchDescriptors } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/transport/launch_descriptor.mjs"
import { resolveAcpLaunch } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/transport/launch_resolution.mjs"
function freeze(value) { if (value && typeof value === "object") { for (const item of Object.values(value)) freeze(item); Object.freeze(value) } return value }
export function captureLaunchCatalog(text, ports) {
  if (typeof text !== "string" || !Array.isArray(ports)) throw new Error("CAPTURED_LAUNCH_REQUIRED")
  const { canonical: CANONICAL, routes: ROUTES } = parseLaunchDescriptors(text)
  const declarations = new Map()
  for (const port of ports) {
    if (typeof port !== "function") throw new Error("INVALID_LAUNCH_PORT")
    const fact = freeze(port())
    if (!fact || typeof fact.id !== "string" || declarations.has(fact.id)) throw new Error("INVALID_LAUNCH_PORT")
    declarations.set(fact.id, fact)
  }
  const profileFor = (route) => {
    const fact = declarations.get(route.profile_id)
    if (!fact || fact.origin !== route.source || fact.profile.id !== route.profile_id) throw new Error(`INVALID_LAUNCH_DESCRIPTOR: missing profile ${route.profile_id}`)
    return fact.profile
  }
  for (const route of ROUTES.values()) profileFor(route)
  return Object.freeze({
    listHarnesses: () => [...ROUTES.keys()].sort(),
    listCanonicalHarnesses: () => [...CANONICAL.keys()].sort(),
    isKnownHarness: (id) => ROUTES.has(id),
    declaration: (id) => { const route=ROUTES.get(id); if (!route) throw new Error(`HARNESS_UNDISCOVERED: ${id}`); return declarations.get(route.profile_id) },
    registryIdentityVersionMatches: (id,version) => { const descriptor=CANONICAL.get(id); if (!descriptor && ROUTES.has(id)) return null; if (!descriptor) return false; if (version == null) return null; return version===descriptor.registry_version },
    harnessLaunchContext: (id,{find}={}) => { const route=ROUTES.get(id); if (!route) throw new Error(`HARNESS_UNDISCOVERED: ${id}`); const profile=profileFor(route); return {harness:id,origin:route.source,label:profile.label??id,...resolveAcpLaunch(profile,find?{find}:{})} },
  })
}
