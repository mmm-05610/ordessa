import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const app = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export async function launchSmoke(home, extraEnv = {}) {
  const child = spawn(path.resolve(app, '../../node_modules/electron/dist/electron'),
    ['--no-sandbox', '--disable-gpu', '--ozone-platform=x11', '.'], {
      cwd: app, env: { ...process.env, MODULAR_USER_DATA: home, ORDESSA_EXTENSION_HOME: home, ORDESSA_EMPTY_HOST: '1', MODULAR_SMOKE: '1',
        // PA-11：驱动代码按路径从源码树加载，绝不进入 dist/electron-main.cjs。
        ORDESSA_SMOKE_DRIVER: path.join(app, 'scripts/smoke-driver.mjs'),
        ORDESSA_DATA_ROOT: path.join(home, '.ordessa'),
        ELECTRON_DISABLE_SECURITY_WARNINGS: 'true', ...extraEnv },
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
    if (timedOut || code !== 0 || !line) throw Error('Electron smoke failed: ' + output)
    return JSON.parse(line.slice('MODULAR_LOADER_READY '.length))
  } finally { clearTimeout(timer); if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL') }
}
