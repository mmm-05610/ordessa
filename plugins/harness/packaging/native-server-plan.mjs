/** Harness-owned launch reference: callers select a brand, never its bridge internals. */
import path from 'node:path'
import { installedLaunchReference } from '../runtime/access-launch.mjs'

export function nativeServerPlan({ harnessId, pluginRoot, artifactRoot }) {
  if (typeof pluginRoot !== 'string' || !path.isAbsolute(pluginRoot)
      || path.resolve(pluginRoot) !== pluginRoot || pluginRoot.includes('\0')) {
    throw new Error('NATIVE_PLUGIN_ROOT_INVALID')
  }
  const launch = installedLaunchReference(harnessId, artifactRoot)
  return Object.freeze({ args: Object.freeze([
    '--execution-mode', 'native', '--plugin-root', pluginRoot, '--native-harness', harnessId,
    '--native-adapter-command', launch.command, `--native-adapter-arg=${launch.args[0]}`,
    '--native-installed-artifact-root', artifactRoot,
  ]) })
}
