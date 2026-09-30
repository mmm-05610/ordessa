/** Harness-owned launch reference: callers select a brand, never its bridge internals. */
import path from 'node:path'
import { installedLaunchReference } from '../runtime/access-launch.mjs'

export function nativeServerPlan({ harnessId, harnessIds, pluginRoot, artifactRoot }) {
  if (typeof pluginRoot !== 'string' || !path.isAbsolute(pluginRoot)
      || path.resolve(pluginRoot) !== pluginRoot || pluginRoot.includes('\0')) {
    throw new Error('NATIVE_PLUGIN_ROOT_INVALID')
  }
  const selected = harnessIds ?? [harnessId]
  if (!Array.isArray(selected) || selected.length === 0 || selected.length > 32
      || selected.some(id => typeof id !== 'string' || !id)
      || new Set(selected).size !== selected.length
      || (harnessIds && harnessId !== undefined)) throw new Error('NATIVE_HARNESS_SELECTION_INVALID')
  const bindings = selected.map(id => ({ harnessId: id, ...installedLaunchReference(id, artifactRoot) }))
  const launch = bindings[0]
  return Object.freeze({ args: Object.freeze([
    '--execution-mode', 'native', '--plugin-root', pluginRoot, '--native-harness', launch.harnessId,
    '--native-adapter-command', launch.command, `--native-adapter-arg=${launch.args[0]}`,
    '--native-installed-artifact-root', artifactRoot,
    ...(bindings.length > 1 ? ['--native-additional-adapters', JSON.stringify(bindings.slice(1).map(
      ({ harnessId, command, args }) => ({ harnessId, command, args })))] : []),
  ]) })
}
