/** Release argv generation: no service launch, installation, or empty-host fallback. */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeProductPlan } from './native-product-plan.mjs'

export function runReleaseServerArgs({ argv = process.argv.slice(2), env = process.env,
  planImpl, writeStdout = value => process.stdout.write(value),
  writeStderr = value => process.stderr.write(value) } = {}) {
  try {
    const options = {}
    const names = { '--plugin-root': 'pluginRoot', '--asset-base': 'assetBase' }
    for (let index = 0; index < argv.length; index += 2) {
      const name = Object.hasOwn(names, argv[index]) ? names[argv[index]] : undefined
      const value = argv[index + 1]
      if (!name || Object.hasOwn(options, name) || typeof value !== 'string'
          || !value || value.startsWith('--')) throw new Error('NATIVE_RELEASE_LAYOUT_INVALID')
      options[name] = value
    }
    if (!options.pluginRoot && !env.ORDESSA_HARNESS_PLUGIN_ROOT)
      throw new Error('NATIVE_RELEASE_PLUGIN_ROOT_REQUIRED: pass --plugin-root for the installed Harness')
    const plan = nativeProductPlan({ ...options, env, planImpl })
    writeStdout(JSON.stringify(plan.args) + '\n')
    return 0
  } catch (error) {
    writeStderr(`ordessa: ${error.message}\n`)
    return 1
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  process.exitCode = runReleaseServerArgs()
}
