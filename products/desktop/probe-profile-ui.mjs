/** Own isolated product root, actual installed adapters and actual native account. */
import { spawn, execFileSync } from 'node:child_process'
import { mkdtemp, copyFile, rm } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nativeServerPlan } from '../../plugins/harness/packaging/native-server-plan.mjs'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const home = await mkdtemp(path.join(root,'.cleanup-evidence/ordessa-profile-ui-'))
let failed=false
try {
  await copyFile(path.join(root, 'products/desktop/extensions.json'), path.join(home, 'extensions.json'))
  execFileSync(path.join(root,'.cleanup-evidence/product-integration-venv/bin/python'),
    [path.join(root,'products/server/scripts/seed-profile-ui-probe.py'),home],{stdio:['ignore','pipe','pipe']})
  const plan = nativeServerPlan({harnessIds:['pi','codex','claude-code'], pluginRoot:path.join(root,'plugins/harness'),
    artifactRoot:'/opt/ordessa/harnesses/artifacts', nativeProfileHarnesses:['codex','claude-code'], piProfileBridge:true,
    artifactRoots:{codex:'/opt/ordessa/harnesses/profile-codex-managed/artifacts',
      pi:'/opt/ordessa/harnesses/profile-chat-fixes/artifacts', 'claude-code':'/opt/ordessa/harnesses/profile-chat-fixes/artifacts'}})
  const child = spawn(path.join(root,'node_modules/electron/dist/electron'),
    ['--no-sandbox','--disable-gpu','--ozone-platform=x11','.'], {cwd:path.join(root,'apps/desktop'),
    env:{...process.env, MODULAR_USER_DATA:home, ORDESSA_EXTENSION_HOME:home, ORDESSA_DATA_ROOT:path.join(home,'data'),
      ORDESSA_EMPTY_HOST:'0', MODULAR_SMOKE:'1', ORDESSA_SERVER_ARGS_JSON:JSON.stringify(plan.args),
      ORDESSA_UI_PROBE_ALLOW_MODEL_CALLS:process.argv.includes('--allow-model-calls')?'1':'0',
      ORDESSA_UI_PROBE_DURING_OUTPUT:process.argv.includes('--during-output')?'1':'0',
      ORDESSA_UI_PROBE_NATIVE_TOOL:process.argv.includes('--native-tool')?'1':'0',
      ORDESSA_SMOKE_DRIVER:path.join(root,'products/desktop/probe-profile-ui-driver.mjs')},
    stdio:['ignore','pipe','pipe']})
  let output = ''
  for (const stream of [child.stdout,child.stderr]) stream.on('data', chunk => {output += chunk})
  const timer = setTimeout(()=>child.kill('SIGTERM'),240000)
  try {
    const code = await new Promise((resolve,reject)=>{child.once('error',reject);child.once('close',resolve)})
    console.log(output)
    if(code !== 0 || !output.includes('PROFILE_UI_INVENTORY ') || output.includes('PROFILE_UI_FAILED ')) throw Error('Actual Desktop UI probe failed')
    if(process.argv.includes('--allow-model-calls') && (!output.includes('PROFILE_UI_CHAT_CONFIRMED ')
        || !output.includes('PROFILE_UI_SWITCH_CONFIRMED '))) throw Error('Actual two-turn UI evidence missing')
    if(process.argv.includes('--during-output') && !output.includes('PROFILE_UI_ACTIVE_SELECTION_CONFIRMED '))
      throw Error('Active-turn selection evidence missing')
    if(process.argv.includes('--native-tool') && !output.includes('PROFILE_UI_NATIVE_TOOL_CONFIRMED '))
      throw Error('Native tool evidence missing')
  } finally { clearTimeout(timer) }
} catch(error) { failed=true; throw error }
finally {
  if(failed) {
    console.log('Own failed probe data retained for diagnosis: '+home)
  } else await rm(home,{recursive:true,force:true})
}
