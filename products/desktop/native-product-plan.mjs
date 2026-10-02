/** Product selection only: Harness owns adapter references and asset verification. */
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeServerPlan } from '../../plugins/harness/packaging/native-server-plan.mjs'

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const profileAssets = Object.freeze({
  codex: 'profile-codex-catalog-fast-off-v6',
  pi: 'profile-pi-startup-admission-v2',
  'claude-code': 'profile-claude-provider-restoration',
})

export function nativeProductPlan({ env = process.env,
  pluginRoot = path.join(repositoryRoot, 'plugins/harness'),
  assetBase = '/opt/ordessa/harnesses', planImpl = nativeServerPlan } = {}) {
  if (typeof assetBase !== 'string' || !path.isAbsolute(assetBase)
      || path.resolve(assetBase) !== assetBase || assetBase.includes('\0')) {
    throw new Error('NATIVE_PRODUCT_ASSET_BASE_INVALID')
  }
  const selected = env.ORDESSA_NATIVE_HARNESS ? [env.ORDESSA_NATIVE_HARNESS] : ['pi', 'codex', 'claude-code']
  const profileBridge = env.ORDESSA_PI_PROFILE_BRIDGE ?? (selected.includes('pi') ? '1' : '0')
  if (profileBridge !== '0' && profileBridge !== '1')
    throw new Error('ORDESSA_PI_PROFILE_BRIDGE must be 0 or 1')
  const defaultRoot = id => path.join(assetBase, profileAssets[id], 'artifacts')
  const nativeProfileRoot = env.ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT ?? defaultRoot('codex')
  if (!nativeProfileRoot) throw new Error('ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT must not be empty')
  const nativeProfileHarnesses = selected.filter(id => ['codex', 'claude-code'].includes(id))
  const claudeProfileRoot = env.ORDESSA_CLAUDE_PROFILE_ARTIFACT_ROOT
    ?? env.ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT ?? defaultRoot('claude-code')
  if (!claudeProfileRoot) throw new Error('Claude Profile asset root must not be empty')
  const artifactRoots = {
    ...(profileBridge === '1' ? { pi: env.ORDESSA_PI_PROFILE_ARTIFACT_ROOT ?? defaultRoot('pi') } : {}),
    ...Object.fromEntries(nativeProfileHarnesses.map(id =>
      [id, id === 'claude-code' ? claudeProfileRoot : nativeProfileRoot])),
  }
  const plan = planImpl({ ...(env.ORDESSA_NATIVE_HARNESS
      ? { harnessId: env.ORDESSA_NATIVE_HARNESS } : { harnessIds: selected }),
    pluginRoot: env.ORDESSA_HARNESS_PLUGIN_ROOT ?? pluginRoot,
    artifactRoot: env.ORDESSA_INSTALLED_ARTIFACT_ROOT ?? path.join(assetBase, 'artifacts'),
    artifactRoots, nativeProfileHarnesses, piProfileBridge: profileBridge === '1' })
  if (!Array.isArray(plan?.args) || plan.args.length === 0
      || plan.args.some(arg => typeof arg !== 'string' || arg.includes('\0'))) {
    throw new Error('NATIVE_PRODUCT_PLAN_INVALID')
  }
  return plan
}
