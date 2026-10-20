import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { QueryClient } from '@ordessa/system-access-client'
import { ExactRecords } from '../details/exact-record'
;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
it('keeps precise-query inputs and scroll through raw detail navigation; no inferred Work or confirmation', async () => {
  const el=document.createElement('main');document.body.append(el);const root=createRoot(el)
  let calls=0
  const access={queries:[{method:'test.fixture',label:'TEST FIXTURE 原记录'}],createQuery:()=>new QueryClient({call:async()=>{calls++;return {kind:'Accepted',requestId:'test',result:{contract_version:'TEST FIXTURE',scope:{realm_id:'r',project_id:'p'},record_type:'Artifact',data:{artifact_id:'a',version:2}}}}},'test.fixture')}
  await act(async()=>root.render(<ExactRecords access={access}/>))
  const fill=async(index:number,value:string)=>{await act(async()=>{const input=el.querySelectorAll('input')[index];Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')!.set!.call(input,value);input.dispatchEvent(new Event('input',{bubbles:true}))})}
  await fill(0,'r');await fill(1,'p')
  const click=async(name:string)=>{const button=[...el.querySelectorAll('button')].find(b=>b.textContent?.includes(name));expect(button).toBeDefined();await act(async()=>button!.click())}
  await click('读取精确记录');expect(calls).toBe(1);expect(el.textContent).toContain('已读取原记录')
  el.scrollTop=125;await click('查看原记录详情');expect(el.scrollTop).toBe(0);expect(el.textContent).toContain('查询成功不等于执行完成');expect(el.querySelector('[data-testid=exact-record]')!.textContent).toContain('"version": 2');expect(el.textContent).not.toContain('确认版本')
  await click('返回精确查询');expect(el.scrollTop).toBe(125);expect(el.querySelectorAll('input')[0].value).toBe('r');expect(el.querySelectorAll('input')[1].value).toBe('p')
  await act(async()=>root.unmount());el.remove()
})
