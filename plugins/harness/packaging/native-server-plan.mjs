/** Harness-owned launch reference: callers select a brand, never its bridge internals. */
import path from 'node:path'
import { installedLaunchReference } from '../runtime/access-launch.mjs'

export function nativeServerPlan({ harnessId, harnessIds, pluginRoot, artifactRoot, artifactRoots = {}, piProfileBridge = false,
  nativeProfileHarnesses = [] }) {
  if (typeof pluginRoot !== 'string' || !path.isAbsolute(pluginRoot)
      || path.resolve(pluginRoot) !== pluginRoot || pluginRoot.includes('\0')) {
    throw new Error('NATIVE_PLUGIN_ROOT_INVALID')
  }
  const selected = harnessIds ?? [harnessId]
  if (!Array.isArray(selected) || selected.length === 0 || selected.length > 32
      || selected.some(id => typeof id !== 'string' || !id)
      || new Set(selected).size !== selected.length
      || (harnessIds && harnessId !== undefined)) throw new Error('NATIVE_HARNESS_SELECTION_INVALID')
  if (typeof piProfileBridge !== 'boolean' || (piProfileBridge && !selected.includes('pi'))) {
    throw new Error('NATIVE_PI_PROFILE_SELECTION_INVALID')
  }
  if (!Array.isArray(nativeProfileHarnesses) || new Set(nativeProfileHarnesses).size !== nativeProfileHarnesses.length
      || nativeProfileHarnesses.some(id => !['codex', 'claude-code'].includes(id) || !selected.includes(id)))
    throw new Error('NATIVE_PROFILE_SELECTION_INVALID')
  if (!artifactRoots || typeof artifactRoots !== 'object' || Array.isArray(artifactRoots)
      || Object.keys(artifactRoots).some(id => !selected.includes(id)))
    throw new Error('NATIVE_ARTIFACT_ROOT_SELECTION_INVALID')
  const rootFor = id => Object.hasOwn(artifactRoots, id) ? artifactRoots[id] : artifactRoot
  const bindings = selected.map(id => ({ harnessId: id, installedArtifactRoot: rootFor(id), ...installedLaunchReference(id, rootFor(id),
    { variant: piProfileBridge && id === 'pi' ? 'pi-profile'
      : nativeProfileHarnesses.includes(id) ? 'native-profile' : 'default' }) }))
  const launch = bindings[0]
  return Object.freeze({ args: Object.freeze([
    '--execution-mode', 'native', '--plugin-root', pluginRoot, '--native-harness', launch.harnessId,
    '--native-adapter-command', launch.command, `--native-adapter-arg=${launch.args[0]}`,
    '--native-installed-artifact-root', launch.installedArtifactRoot,
    ...(piProfileBridge ? ['--native-pi-profile-bridge'] : []),
    ...nativeProfileHarnesses.flatMap(id => ['--native-profile-harness', id]),
    ...(bindings.length > 1 ? ['--native-additional-adapters', JSON.stringify(bindings.slice(1).map(
      ({ harnessId, command, args, installedArtifactRoot }) => ({ harnessId, command, args,
        ...(installedArtifactRoot !== launch.installedArtifactRoot ? { installedArtifactRoot } : {}) })))] : []),
  ]) })
}
