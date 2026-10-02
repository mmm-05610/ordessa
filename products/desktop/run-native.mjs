/** Development product launcher. This does not install assets or disable Electron sandboxing. */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeProductPlan } from './native-product-plan.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')

export function launchNativeProduct({ env = process.env, planImpl, spawnImpl = spawn } = {}) {
  const plan = nativeProductPlan({ env, planImpl })
  return spawnImpl(path.join(root, 'node_modules/electron/dist/electron'), ['.'], {
    cwd: path.join(root, 'apps/desktop'), stdio: 'inherit',
    env: { ...env, ORDESSA_SERVER_ARGS_JSON: JSON.stringify(plan.args) },
  })
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  try {
    const child = launchNativeProduct()
    for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
    child.once('error', error => { console.error(error.message); process.exitCode = 1 })
    child.once('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0) })
  } catch (error) {
    console.error(error.message)
    process.exitCode = 1
  }
}
