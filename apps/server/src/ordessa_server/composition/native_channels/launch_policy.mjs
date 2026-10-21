import { realpathSync, readFileSync } from "node:fs"
import path from "node:path"
import { verifyInstalledArtifact } from "../../../../../../packages/execution/agents/src/ordessa_agents/harness/providers/resolution/_deployment/native-artifact-policy.mjs"
class LaunchRefusal extends Error { constructor(code) { super(code); this.code=code } }
function onReadOnlyMount(file, mountInfoText = null) {
  if (process.platform !== "linux") return false
  const decoded = (value) => value.replace(/\\([0-7]{3})/g, (_, octal) =>
    String.fromCharCode(Number.parseInt(octal, 8)))
  const rows = (mountInfoText ?? readFileSync("/proc/self/mountinfo", "utf8")).split("\n")
  let best = null
  for (const row of rows) {
    const fields = row.split(" ")
    if (fields.length < 6) continue
    const mountpoint = decoded(fields[4])
    if ((file === mountpoint || file.startsWith(`${mountpoint === "/" ? "" : mountpoint}/`))
        && (!best || mountpoint.length > best.mountpoint.length)) {
      best = { mountpoint, options: fields[5] }
    }
  }
  return best?.options.split(",").includes("ro") === true
}

function sameArgs(actual, expected) {
  return Array.isArray(actual) && actual.length === expected.length
    && actual.every((arg, index) => arg === expected[index])
}

function under(root, file) {
  try { return realpathSync(file).startsWith(`${realpathSync(root)}${path.sep}`) }
  catch { return false }
}


export function bindLaunchPolicy(catalog) {
  const { harnessLaunchContext, listHarnesses, registryIdentityVersionMatches }=catalog
  function pinFor(harness,discovered) {
    const fact=catalog.declaration(harness),spec=fact.managed
    if (!spec) throw new LaunchRefusal("ADAPTER_ROUTE_UNBOUND")
    if (spec.pinMode === "direct") {
      const version=spec.version
      if (!registryIdentityVersionMatches(harness,version) || discovered.harness!==harness || discovered.origin!==fact.origin || discovered.command!==spec.binary || discovered.args.length!==0) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
      return version
    }
    const packageArg=`--package=${spec.package}@`,pinned=discovered.args?.find(arg=>arg.startsWith(packageArg))
    if (discovered.harness!==harness || discovered.origin!==fact.origin || !["npx","npx.cmd"].includes(discovered.command) || !pinned || discovered.args.at(-1)!==spec.binary) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
    const version=pinned.slice(packageArg.length)
    if (!/^\d+\.\d+\.\d+$/.test(version)) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
    return version
  }
  function installedSpec(harness,variant) {
    let fact
    try { fact=catalog.declaration(harness) } catch { throw new LaunchRefusal("ADAPTER_ROUTE_UNBOUND") }
    const variantSpec=fact.variants[variant]
    if (!fact.managed || !variantSpec || (variant!=="default" && !fact.nativeExtension && !fact.profileExtension)) throw new LaunchRefusal("ADAPTER_ROUTE_UNBOUND")
    const extensionPolicy=variant==="default" ? null : fact.nativeExtension ? {...fact.nativeExtension,mode:"native",variant} : {...fact.profileExtension,mode:"profile",variant}
    return {...fact.managed,...variantSpec,extensionPolicy}
  }
  function resolveManagedLaunch(harness,launch,{artifactBase="/runtime/artifacts",mountInfoText=null}={}) {
    const spec=catalog.declaration(harness).managed
    if (!spec) return null
    const version=pinFor(harness,harnessLaunchContext(harness,{find:()=>null}))
    const artifactRoot=path.join(artifactBase,spec.artifact),artifactEntry=path.join(artifactRoot,"node_modules",spec.package,"dist/index.js")
    if (launch.command===process.execPath && launch.args?.length===1 && launch.args[0]===artifactEntry) {
      try {
        const root=realpathSync(artifactRoot),entry=realpathSync(artifactEntry),manifestPath=realpathSync(path.join(artifactRoot,"node_modules",spec.package,"package.json"))
        if (!entry.startsWith(`${root}${path.sep}`) || !manifestPath.startsWith(`${root}${path.sep}`)) throw new Error("outside artifact")
        if (![root,entry,manifestPath].every(file=>onReadOnlyMount(file,mountInfoText))) throw new Error("artifact mount is writable")
        const manifest=JSON.parse(readFileSync(manifestPath,"utf8"))
        if (manifest.name!==spec.package || manifest.version!==version) throw new Error("pin mismatch")
      } catch { throw new LaunchRefusal("ADAPTER_ARTIFACT_UNVERIFIED") }
      return {command:process.execPath,args:[artifactEntry],source:"managed-artifact",version}
    }
    throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
  }
  function resolveInstalledLaunch(harness,launch,{artifactBase,variant="default"}={}) {
    const spec=installedSpec(harness,variant),version=pinFor(harness,harnessLaunchContext(harness,{find:()=>null}))
    const expectedEntry=typeof artifactBase==="string" ? path.join(artifactBase,spec.artifact,"node_modules",spec.package,spec.entry) : null
    if (launch.command!==process.execPath || launch.args?.length!==1 || launch.args[0]!==expectedEntry) throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
    try { const entry=verifyInstalledArtifact({artifactBase,artifact:spec.artifact,packageName:spec.package,version,variant,extensionPolicy:spec.extensionPolicy}); return {command:process.execPath,args:[entry],source:"installed-artifact",version} }
    catch { throw new LaunchRefusal("ADAPTER_ARTIFACT_UNVERIFIED") }
  }
  function installedLaunchReference(harness,artifactBase,{variant="default"}={}) {
    const spec=installedSpec(harness,variant)
    if (typeof artifactBase!=="string") throw new LaunchRefusal("ADAPTER_ARTIFACT_UNVERIFIED")
    return resolveInstalledLaunch(harness,{command:process.execPath,args:[path.join(artifactBase,spec.artifact,"node_modules",spec.package,spec.entry)]},{artifactBase,variant})
  }
  function resolveLegacyLaunch(harness,launch,environment) {
    const descriptor=harnessLaunchContext(harness,{find:()=>null}),fact=catalog.declaration(harness)
    if (descriptor.harness!==harness) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
    const artifact=fact.legacy
    if (artifact) {
      const routeArgs=artifact.command.startsWith(artifact.root)?artifact.args:artifact.args.slice(1)
      if (!sameArgs(routeArgs,descriptor.args)) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
      if (launch.command!==artifact.command || !sameArgs(launch.args??[],artifact.args) || !under(artifact.root,artifact.args[0].startsWith(artifact.root)?artifact.args[0]:artifact.command)) throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
      return {command:artifact.command,args:artifact.args,source:"legacy-artifact-route"}
    }
    if (fact.pythonRoute) {
      const spec=fact.pythonRoute
      if (!sameArgs(descriptor.args,["acp"])) throw new LaunchRefusal("ADAPTER_DESCRIPTOR_DRIFT")
      if (launch.command!==spec.command || !sameArgs(launch.args??[],spec.args) || environment.PYTHONPATH!==spec.site || !under(spec.site,`${spec.site}/${spec.moduleFile}`)) throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
      return {command:launch.command,args:launch.args,source:"legacy-artifact-route"}
    }
    if (fact.nativeRoute) {
      if (launch.command!==descriptor.command || !sameArgs(launch.args??[],descriptor.args)) throw new LaunchRefusal("ADAPTER_LAUNCH_MISMATCH")
      return {command:descriptor.command,args:descriptor.args,source:"legacy-profile-route"}
    }
    throw new LaunchRefusal("ADAPTER_ROUTE_UNBOUND")
  }
  return Object.freeze({resolveManagedLaunch,resolveInstalledLaunch,resolveLegacyLaunch,installedLaunchReference,
    allowsPythonPath:(harness,key)=>key!=="PYTHONPATH"||catalog.declaration(harness).allowsPythonPath,
    launchDiscovery:()=>({harnesses:listHarnesses()})})
}
