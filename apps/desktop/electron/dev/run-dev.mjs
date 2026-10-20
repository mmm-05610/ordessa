import { spawn } from 'node:child_process'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const userData = await mkdtemp(path.join(tmpdir(), 'modular-dev-'))
const electron = path.resolve(root, '../../node_modules/electron/dist/electron')
// Normal development keeps Chromium sandboxing enabled; --no-sandbox is test-smoke-only.
const child = spawn(electron, ['.'], {
  cwd: root,
  env: { ...process.env, MODULAR_USER_DATA: userData,
    ORDESSA_EXTENSION_HOME: process.env.ORDESSA_EXTENSION_HOME ?? path.resolve(root, '../../.local-desktop') },
  stdio: 'inherit',
})
process.on('SIGINT', () => child.kill('SIGINT'))
process.on('SIGTERM', () => child.kill('SIGTERM'))
try {
  const code = await new Promise((resolve, reject) => {
    child.once('error', reject)
    child.once('exit', (code, signal) => resolve(code ?? (signal ? 1 : 0)))
  })
  process.exitCode = code
} finally {
  await rm(userData, { recursive: true, force: true })
}
