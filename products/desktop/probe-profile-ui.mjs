/** Own isolated product root, actual installed adapters and actual native account. */
import { spawn, execFileSync } from 'node:child_process'
import { mkdtemp, copyFile, rm } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeServerPlan } from '../../plugins/harness/packaging/native-server-plan.mjs'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
export function probeOptions(argv) {
  const brand = argv.find(arg => arg.startsWith('--brand='))?.slice(8) ?? 'codex'
  if (!['codex','pi','claude-code'].includes(brand)) throw Error('Unsupported UI probe brand')
  const allowModelCalls = argv.includes('--allow-model-calls')
  const inventoryOnly = argv.includes('--inventory-only')
  const keyFile = argv.find(arg => arg.startsWith('--key-file='))?.slice(11)
  if (allowModelCalls && brand !== 'codex' && (!keyFile || !path.isAbsolute(keyFile)))
    throw Error('API UI inference requires an explicit absolute --key-file path')
  if (!allowModelCalls && (argv.includes('--during-output') || argv.includes('--native-tool')))
    throw Error('Inference evidence flags require --allow-model-calls')
  if(inventoryOnly && (argv.includes('--during-output') || argv.includes('--native-tool')))
    throw Error('Inventory-only probe cannot request inference evidence')
  return { brand, allowModelCalls, inventoryOnly, keyFile }
}
export async function main(argv=process.argv.slice(2)) {
const options = probeOptions(argv)
const home = await mkdtemp(path.join(root,'.cleanup-evidence/ordessa-profile-ui-'))
const python = path.join(root,'.cleanup-evidence/product-integration-venv/bin/python')
const seed = path.join(root,'products/server/scripts/seed-profile-ui-probe.py')
let failed=false
try {
  await copyFile(path.join(root, 'products/desktop/extensions.json'), path.join(home, 'extensions.json'))
  try {
    execFileSync(python, [seed,home,'--brand='+options.brand,
      ...(options.allowModelCalls ? ['--allow-model-calls'] : []),
      ...(options.keyFile ? ['--key-file='+options.keyFile] : [])],{stdio:['ignore','pipe','pipe']})
  } catch { throw Error('UI seed failed; no model calls made; verify installed assets and unlocked keyring') }
  const plan = nativeServerPlan({harnessIds:['pi','codex','claude-code'], pluginRoot:path.join(root,'plugins/harness'),
    artifactRoot:process.env.ORDESSA_INSTALLED_ARTIFACT_ROOT ?? '/opt/ordessa/harnesses/artifacts',
    nativeProfileHarnesses:['codex','claude-code'], piProfileBridge:true,
    artifactRoots:{codex:process.env.ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT ?? '/opt/ordessa/harnesses/profile-codex-catalog-fast-off-v6/artifacts',
      pi:process.env.ORDESSA_PI_PROFILE_ARTIFACT_ROOT ?? '/opt/ordessa/harnesses/profile-pi-registration-owner-bound/artifacts',
      'claude-code':process.env.ORDESSA_CLAUDE_PROFILE_ARTIFACT_ROOT ?? '/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts'}})
  const child = spawn(path.join(root,'node_modules/electron/dist/electron'),
    ['--no-sandbox','--disable-gpu','--ozone-platform=x11','.'], {cwd:path.join(root,'apps/desktop'),
    env:{...process.env, MODULAR_USER_DATA:home, ORDESSA_EXTENSION_HOME:home, ORDESSA_DATA_ROOT:path.join(home,'data'),
      ORDESSA_EMPTY_HOST:'0', MODULAR_SMOKE:'1', ORDESSA_SERVER_ARGS_JSON:JSON.stringify(plan.args),
      ORDESSA_UI_PROBE_BRAND:options.brand,
      ORDESSA_UI_PROBE_ALLOW_MODEL_CALLS:options.allowModelCalls && !options.inventoryOnly?'1':'0',
      ORDESSA_UI_PROBE_DURING_OUTPUT:argv.includes('--during-output')?'1':'0',
      ORDESSA_UI_PROBE_NATIVE_TOOL:argv.includes('--native-tool')?'1':'0',
      ORDESSA_SMOKE_DRIVER:path.join(root,'products/desktop/probe-profile-ui-driver.mjs')},
    stdio:['ignore','pipe','pipe']})
  let output = ''
  for (const stream of [child.stdout,child.stderr]) stream.on('data', chunk => {output += chunk})
  const timer = setTimeout(()=>child.kill('SIGTERM'),240000)
  try {
    const code = await new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve)})
    console.log(output.split('\n').filter(line=>line.startsWith('PROFILE_UI_')).join('\n'))
    if(code !== 0 || !output.includes('PROFILE_UI_INVENTORY ') || output.includes('PROFILE_UI_FAILED ')) throw Error('Actual Desktop UI probe failed')
    if(options.allowModelCalls && !options.inventoryOnly && (!output.includes('PROFILE_UI_CHAT_CONFIRMED ')
        || !output.includes('PROFILE_UI_SWITCH_CONFIRMED '))) throw Error('Actual two-turn UI evidence missing')
    if(argv.includes('--during-output') && !output.includes('PROFILE_UI_ACTIVE_SELECTION_CONFIRMED '))
      throw Error('Active-turn selection evidence missing')
    if(argv.includes('--native-tool') && !output.includes('PROFILE_UI_NATIVE_TOOL_CONFIRMED '))
      throw Error('Native tool evidence missing')
  } finally { clearTimeout(timer) }
} catch(error) { failed=true; throw error }
finally {
  try {
    if(existsSync(path.join(home,'data')))
      execFileSync(python,[seed,home,'--brand='+options.brand,'--cleanup'],{stdio:['ignore','pipe','pipe']})
    console.log('PROFILE_UI_CLEANUP '+JSON.stringify({ownCredentialsDeleted:true,brand:options.brand}))
  } catch { failed=true; console.log('PROFILE_UI_CLEANUP_FAILED Exact own credential cleanup requires diagnosis'); process.exitCode=1 }
  if(failed) {
    console.log('Own failed probe data retained for diagnosis: '+home)
  } else await rm(home,{recursive:true,force:true})
}
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main()
