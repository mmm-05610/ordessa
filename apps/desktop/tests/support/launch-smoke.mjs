import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const DRIVER_IDS = new Set(['smoke', 'probe-startup-ui'])
const RESERVED_SMOKE_ENV = new Set(['MODULAR_SMOKE', 'ORDESSA_SMOKE_DRIVER', 'ORDESSA_SMOKE_DRIVER_ID'])

export function buildSmokeEnvironment(home, extraEnv = {}, driverId = 'smoke') {
  if (!DRIVER_IDS.has(driverId)) throw Error('SMOKE_DRIVER_NOT_ADMITTED')
  for (const key of RESERVED_SMOKE_ENV) {
    if (Object.hasOwn(extraEnv, key)) throw Error('SMOKE_DRIVER_ENV_OVERRIDE_REFUSED')
  }
  const env = { ...process.env, MODULAR_USER_DATA: home, ORDESSA_EXTENSION_HOME: home, ORDESSA_EMPTY_HOST: '1',
    MODULAR_SMOKE: '1', ORDESSA_DATA_ROOT: path.join(home, '.ordessa'),
    ELECTRON_DISABLE_SECURITY_WARNINGS: 'true', ...extraEnv }
  // A stale inherited path is never an alternate input. Main accepts only the ID below.
  delete env.ORDESSA_SMOKE_DRIVER
  env.ORDESSA_SMOKE_DRIVER_ID = driverId
  return env
}

export async function launchSmoke(home, extraEnv = {}, { driverId = 'smoke' } = {}) {
  const child = spawn(path.resolve(app, '../../node_modules/electron/dist/electron'),
    ['--no-sandbox', '--disable-gpu', '--ozone-platform=x11', '.'], {
      cwd: app, env: buildSmokeEnvironment(home, extraEnv, driverId),
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  let output = '', timedOut = false
  const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL') }, 25000)
  for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => { output += chunk })
  try {
    const code = await new Promise((resolve, reject) => {
      child.once('error', reject)
      child.once('close', resolve)
    })
    const line = output.split('\n').find(line => line.startsWith('MODULAR_LOADER_READY '))
    if (timedOut || code !== 0 || !line) throw Error(`Electron smoke failed (code=${String(code)}, signal=${String(child.signalCode)}, timeout=${timedOut}): ` + output)
    const result = JSON.parse(line.slice('MODULAR_LOADER_READY '.length))
    if (!result.ready || !result.nodeAbsent) throw Error('Electron smoke failed its readiness/isolation checks: ' + output)
    return result
  } finally { clearTimeout(timer); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL') }
}
