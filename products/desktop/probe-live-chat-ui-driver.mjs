/** User-authorized live UI probe. One NEW prompt; never retry unknown sends. */
import assert from 'node:assert/strict'
import {writeFile} from 'node:fs/promises'

export async function runSmoke({win}) {
  const js = code => win.webContents.executeJavaScript(code)
  const wait = async (code, timeout=20000) => {
    const end=Date.now()+timeout
    while(Date.now()<end) { if(await js(code))return; await new Promise(r=>setTimeout(r,150)) }
    throw Error('UI condition timed out: '+code)
  }
  const click = async selector => {
    const point=await js(`(() => {const e=document.querySelector(${JSON.stringify(selector)});if(!e)throw Error('missing control');const r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;if(!e.contains(document.elementFromPoint(x,y)))throw Error('covered control');return {x:Math.round(x),y:Math.round(y)}})()`)
    win.webContents.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,...point})
    win.webContents.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,...point})
  }
  const capture=async name=>{
    if(process.env.ORDESSA_LIVE_UI_EVIDENCE)await writeFile(`${process.env.ORDESSA_LIVE_UI_EVIDENCE}/${name}.png`,(await win.capturePage()).toPNG())
  }
  try {
    await wait('!!document.querySelector(".chat-page")')
    await wait('!!document.querySelector("[data-chat-connector]") || !!document.querySelector(".agent-project-new")')
    await js(`(() => {const pi=[...document.querySelectorAll('[data-chat-connector]')].find(e=>e.textContent==='ACP · pi');if(pi)pi.click()})()`)
    await wait('!!document.querySelector(".agent-project-new")')
    await click('.agent-project-new')
    await wait("document.querySelector('[data-profile-picker] select')?.options.length > 1")
    const chosen=await js(`(() => {const e=document.querySelector('[data-profile-picker] select');const option=[...e.options].find(o=>/pi/i.test(o.textContent)&&/deepseek-flash/i.test(o.textContent));if(!option)throw Error('Pi flash Profile unavailable');Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(e,option.value);e.dispatchEvent(new Event('change',{bubbles:true}));return option.textContent})()`)
    await new Promise(r=>setTimeout(r,500))
    if (process.env.ORDESSA_LIVE_UI_SEND !== '1') {
      await capture('live-draft-navigation')
      console.log('LIVE_CHAT_NAVIGATION '+JSON.stringify({profile:chosen,promptsIssued:0}))
      return
    }
    await js(`(() => {const e=document.querySelector('[data-testid=chat-input]');Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(e,'Ordessa UI 自动验收：请只回复 UI_OK，不调用工具。');e.dispatchEvent(new Event('input',{bubbles:true}))})()`)
    await wait('!document.querySelector("[data-testid=chat-send]").disabled')
    await capture('live-before-send')
    await click('[data-testid=chat-send]')
    await wait('!!document.querySelector("[role=alert]") || (!!document.querySelector("[data-testid=chat-input]") && document.querySelector("[data-testid=chat-input]").value === "")',90000)
    await new Promise(r=>setTimeout(r,1000))
    const facts=await js(`(() => {const s=document.querySelector('[data-profile-picker] select'),i=document.querySelector('[data-testid=chat-input]');return {profile:s?.selectedOptions[0]?.textContent,draftRetained:!!i?.value,alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent),documentOverflow:document.documentElement.scrollWidth-innerWidth}})()`)
    await capture('live-after-send')
    assert.equal(facts.profile,chosen,'applied Profile label is retained across first send')
    assert.ok(facts.documentOverflow<=1,'no horizontal overflow')
    console.log('LIVE_CHAT_UI_FACTS '+JSON.stringify(facts))
    if (!facts.draftRetained && !facts.alerts.length) {
      await wait("[...document.querySelectorAll('.chat-page')].some(e=>e.textContent.includes('UI_OK') && e.textContent.includes('completed'))",90000)
      await capture('live-completed')
      console.log('LIVE_CHAT_COMPLETED '+JSON.stringify({reply:'UI_OK',profile:chosen}))
      await click('[data-testid="model-selector-trigger"]')
      await wait('!!document.querySelector("[role=listbox]")')
      await capture('live-model-menu')
      win.webContents.sendInputEvent({type:'keyDown',keyCode:'ESC'})
      win.webContents.sendInputEvent({type:'keyUp',keyCode:'ESC'})
      await click('.agent-project-new')
      await wait('!!document.querySelector("[data-profile-picker] select")')
      assert.equal(await js('document.querySelector("[data-profile-picker] select").value'),'','new draft must not claim the previous native session Profile')
      await capture('live-new-draft')
      console.log('LIVE_NEW_DRAFT_FACTS '+JSON.stringify({previousProfileNotInherited:true}))
    }
  } catch(error) { console.error('LIVE_CHAT_UI_FAILED '+error.message);await capture('live-failed') }
  // Keep the authorized real product open for the user. No retry, app.quit or data cleanup.
}
