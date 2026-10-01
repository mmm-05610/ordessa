/** Development product launcher. This does not install assets or disable Electron sandboxing. */
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeServerPlan } from '../../plugins/harness/packaging/native-server-plan.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const selected = process.env.ORDESSA_NATIVE_HARNESS ? [process.env.ORDESSA_NATIVE_HARNESS] : ['pi', 'codex', 'claude-code']
const profileBridge = process.env.ORDESSA_PI_PROFILE_BRIDGE ?? (selected.includes('pi') ? '1' : '0')
if (profileBridge !== undefined && profileBridge !== '0' && profileBridge !== '1')
  throw new Error('ORDESSA_PI_PROFILE_BRIDGE must be 0 or 1')
// Delivered and independently verified additive assets. Ordinary assets are
// unchanged; exact enhanced variants still pass Harness provenance checks.
const nativeProfileRoot = process.env.ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT
  ?? '/opt/ordessa/harnesses/profile-native/artifacts'
if (nativeProfileRoot !== undefined && !nativeProfileRoot)
  throw new Error('ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT must not be empty')
const nativeProfileHarnesses = nativeProfileRoot ? selected.filter(id => ['codex', 'claude-code'].includes(id)) : []
const profileRoots = { ...(profileBridge === '1' ? { pi: process.env.ORDESSA_PI_PROFILE_ARTIFACT_ROOT
    ?? '/opt/ordessa/harnesses/profile-pi-provider/artifacts' } : {}),
  ...Object.fromEntries(nativeProfileHarnesses.map(id => [id, nativeProfileRoot])) }
const plan = nativeServerPlan({ ...(process.env.ORDESSA_NATIVE_HARNESS
    ? { harnessId: process.env.ORDESSA_NATIVE_HARNESS }
    : { harnessIds: ['pi', 'codex', 'claude-code'] }),
  pluginRoot: process.env.ORDESSA_HARNESS_PLUGIN_ROOT ?? path.join(root, 'plugins/harness'),
  artifactRoot: process.env.ORDESSA_INSTALLED_ARTIFACT_ROOT ?? '/opt/ordessa/harnesses/artifacts',
  artifactRoots: profileRoots, nativeProfileHarnesses,
  piProfileBridge: profileBridge === '1' })
const child = spawn(path.join(root, 'node_modules/electron/dist/electron'), ['.'], {
  cwd: path.join(root, 'apps/desktop'), stdio: 'inherit',
  env: { ...process.env, ORDESSA_SERVER_ARGS_JSON: JSON.stringify(plan.args) },
})
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal))
child.once('error', error => { console.error(error.message); process.exitCode = 1 })
child.once('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0) })
