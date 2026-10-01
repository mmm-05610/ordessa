/** Full enabled desktop + installed adapters, zero prompts and isolated probe data. */
import assert from 'node:assert/strict'
import { mkdtemp, copyFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchSmoke } from '../../apps/desktop/scripts/launch-smoke.mjs'
import { nativeServerPlan } from '../../plugins/harness/packaging/native-server-plan.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const home = await mkdtemp(path.join(tmpdir(), 'ordessa-product-installed-probe-'))
try {
  await copyFile(path.join(root, 'products/desktop/extensions.json'), path.join(home, 'extensions.json'))
  const nativeProfileRoot = process.env.ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT
    ?? '/opt/ordessa/harnesses/profile-native/artifacts'
  if (nativeProfileRoot !== undefined && !nativeProfileRoot) throw new Error('Native Profile asset root must not be empty')
  const nativeProfileHarnesses = nativeProfileRoot ? ['codex', 'claude-code'] : []
  const plan = nativeServerPlan({ harnessIds: ['pi', 'codex', 'claude-code'],
    pluginRoot: path.join(root, 'plugins/harness'),
    artifactRoot: process.env.ORDESSA_INSTALLED_ARTIFACT_ROOT ?? '/opt/ordessa/harnesses/artifacts',
    artifactRoots: { pi: process.env.ORDESSA_PI_PROFILE_ARTIFACT_ROOT
      ?? '/opt/ordessa/harnesses/profile-pi-provider/artifacts',
      ...Object.fromEntries(nativeProfileHarnesses.map(id => [id, nativeProfileRoot])) },
    nativeProfileHarnesses, piProfileBridge: true })
  const result = await launchSmoke(home, { ORDESSA_EMPTY_HOST: '0', HOME: home,
    XDG_CONFIG_HOME: path.join(home, 'config'), XDG_DATA_HOME: path.join(home, 'data'),
    ORDESSA_SERVER_ARGS_JSON: JSON.stringify(plan.args) })
  assert.equal(result.ready, true)
  assert.equal(result.rootMounted, true)
  assert.deepEqual(result.errors, [])
  // Legacy smoke names every role=status node "starting", including the
  // expected no-project hint and async business loads. Report those facts;
  // this mount-only gate does not claim all business loads have settled.
  console.log(JSON.stringify({ ready: result.ready, rootMounted: result.rootMounted,
    errors: result.errors, statuses: result.starting, pages: result.pages, nodeAbsent: result.nodeAbsent,
    prompt: 0, scope: 'installed-product-mount-only' }))
} finally {
  await rm(home, { recursive: true, force: true })
}
