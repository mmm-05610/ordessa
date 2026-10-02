/** Actual default product startup geometry. No connector selection or prompts. */
import {mkdtemp,copyFile,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import path from 'node:path'
import {fileURLToPath} from 'node:url'
import {launchSmoke} from '../../apps/desktop/scripts/launch-smoke.mjs'
import {nativeProductPlan} from './native-product-plan.mjs'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..')
const home=await mkdtemp(path.join(tmpdir(),'ordessa-startup-ui-'))
try {
  await copyFile(path.join(root,'products/desktop/extensions.json'),path.join(home,'extensions.json'))
  console.log(JSON.stringify(await launchSmoke(home,{ORDESSA_EMPTY_HOST:'0',
    ORDESSA_SERVER_ARGS_JSON:JSON.stringify(nativeProductPlan().args),
    ORDESSA_SMOKE_DRIVER:path.join(root,'products/desktop/probe-startup-ui-driver.mjs')})))
} finally {await rm(home,{recursive:true,force:true})}
