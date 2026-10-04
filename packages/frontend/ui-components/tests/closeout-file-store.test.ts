import {it,expect} from 'vitest'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createFileUiAdapter} from '../../native-bridge/src/ui-storage.mjs'
import {fileBackedUiStore,readUiRevision} from '../src/state/uiStorage'
it('two independent stores use real file atomic revision and reopen without singleton', async()=>{
 const root=await mkdtemp(join(tmpdir(),'ordessa-013-stores-'))
 const ns={pluginNamespace:'fixture',workspace:'w',windowOrSharedPurpose:'shared',schemaVersion:1}
 try {
  const adapterA=createFileUiAdapter(root), adapterB=createFileUiAdapter(root)
  const a=fileBackedUiStore(adapterA), b=fileBackedUiStore(adapterB)
  await a.write(ns,'layout',{width:100},{})
  const rev=await readUiRevision(adapterA,ns,'layout')
  const result=await Promise.all([a.write(ns,'layout',{width:200},{ifRevision:rev}),b.write(ns,'layout',{width:300},{ifRevision:rev})])
  expect(result.sort()).toEqual(['conflict','written'])
  const reopened=fileBackedUiStore(createFileUiAdapter(root))
  expect([200,300]).toContain((await reopened.read<{width:number}>(ns,'layout'))!.width)
  expect(await readUiRevision(adapterB,ns,'layout')).not.toBe(rev)
  let value:any={accessToken:'fixture'};for(let i=0;i<12;i++)value={nested:value}
  await expect(a.write(ns,'unsafe',value,{})).rejects.toThrow()
  expect(await a.read(ns,'unsafe')).toBeUndefined()
 } finally {await rm(root,{recursive:true,force:true})}
})
