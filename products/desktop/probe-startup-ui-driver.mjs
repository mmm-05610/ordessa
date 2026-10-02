import assert from 'node:assert/strict'
import { writeFile } from 'node:fs/promises'

export async function runSmoke({win, app}) {
  try {
    for (let n=0;n<100;n++) {
      if (await win.webContents.executeJavaScript('document.documentElement.dataset.settled === "true" && ![...document.querySelectorAll("[role=status]")].some(e=>e.textContent.includes("启动中"))')) break
      await new Promise(resolve=>setTimeout(resolve,100))
    }
    await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    const result=await win.webContents.executeJavaScript(`(() => {
      const sidebar=document.querySelector('.wb-sidebar'), footer=document.querySelector('.wb-sidebar-footer');
      const a=sidebar?.getBoundingClientRect(), b=footer?.getBoundingClientRect();
      return {ready:document.documentElement.dataset.ready==='true',nodeAbsent:typeof window.require==='undefined',
        theme:getComputedStyle(document.documentElement).getPropertyValue('--ordessa-color-surface').trim(),
        overflow:document.documentElement.scrollHeight-window.innerHeight,
        footerGap:a&&b?a.bottom-b.bottom:null,footerHeight:b?.height,
        chat:!!document.querySelector('.chat-page'),connectors:[...document.querySelectorAll('[data-chat-connector]')].map(e=>e.textContent),
        errors:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent)};
    })()`)
    console.log('STARTUP_UI_FACTS '+JSON.stringify(result))
    if(process.env.ORDESSA_STARTUP_SCREENSHOT) {
      await new Promise(resolve=>setTimeout(resolve,250))
      await writeFile(process.env.ORDESSA_STARTUP_SCREENSHOT,(await win.capturePage()).toPNG())
    }
    assert.ok(result.theme, 'theme tokens must be applied by the real product')
    assert.ok(result.overflow<=1,'no document overflow at startup')
    assert.ok(result.footerGap!==null&&Math.abs(result.footerGap)<=1,'footer anchored at sidebar bottom')
    assert.ok(result.footerHeight<150,'footer must not claim half the sidebar')
    assert.ok(result.chat,'Chat is the default main view')
    assert.equal(result.connectors.length,3,'unselected Chat offers the three ACP harnesses')
    assert.deepEqual(result.errors,[])
    await win.webContents.executeJavaScript('document.querySelector(".conn-status-toggle").click()')
    await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    const shellFacts=await win.webContents.executeJavaScript(`(() => {
      const menu=document.querySelector('.conn-popover'),r=menu?.getBoundingClientRect();
      const hit=r&&document.elementFromPoint(r.left+r.width/2,r.top+20);
      return {menuVisible:!!menu&&!!hit&&menu.contains(hit)};
    })()`)
    console.log('SHELL_INTERACTION_FACTS '+JSON.stringify(shellFacts))
    assert.ok(shellFacts.menuVisible,'footer menu must be visible and receive pointer hits above the footer')
    const paint=()=>win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    const click=async (selector,paintAfter=true)=>{
      const point=await win.webContents.executeJavaScript(`(() => {
        const button=document.querySelector(${JSON.stringify(selector)});if(!button)throw Error('missing button');
        const r=button.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2;
        if(!button.contains(document.elementFromPoint(x,y)))throw Error('button is covered: '+${JSON.stringify(selector)});
        return {x:Math.round(x),y:Math.round(y)};
      })()`)
      win.webContents.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,...point})
      win.webContents.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,...point})
      if(paintAfter) await paint()
    }
    await click('[aria-label="布局与视图"]')
    assert.ok(await win.webContents.executeJavaScript(`(() => {
      const m=document.querySelector('.wb-layout-menu-panel'),r=m.getBoundingClientRect();
      return !m.hidden&&r.left>=0&&r.right<=innerWidth&&r.bottom<=innerHeight&&m.contains(document.elementFromPoint(r.left+20,r.top+20));
    })()`),'compact layout menu must stay visible and receive pointer hits')
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'ESC'})
    win.webContents.sendInputEvent({type:'keyUp',keyCode:'ESC'})
    await paint()
    assert.ok(await win.webContents.executeJavaScript('document.querySelector(".wb-layout-menu-panel").hidden && document.activeElement?.getAttribute("aria-label") === "布局与视图"'),'layout Escape closes and restores focus')
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'ESC'})
    win.webContents.sendInputEvent({type:'keyUp',keyCode:'ESC'})
    await paint()
    assert.equal(await win.webContents.executeJavaScript('!!document.querySelector(".conn-popover")'),false,'Escape closes footer menu')
    await click('[aria-label="打开设置"]')
    assert.ok(await win.webContents.executeJavaScript('!!document.querySelector(".wb-settings-nav")'),'settings has section navigation')
    await click('.wb-settings-nav button')
    assert.equal(await win.webContents.executeJavaScript('document.querySelectorAll(".wb-settings-section:not([hidden])").length'),1)
    await click('[aria-label="关闭设置"]')
    assert.equal(await win.webContents.executeJavaScript('!!document.querySelector(".wb-settings")'),false,'real pointer closes settings')
    await click('[aria-label="打开设置"]')
    assert.ok(await win.webContents.executeJavaScript(`(() => {
      const buttons=[...document.querySelectorAll('.window-controls button')];return buttons.length===3&&buttons.every(b=>{
        const r=b.getBoundingClientRect();return b.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))
      });
    })()`),'all window buttons remain hit-testable while settings is open')
    await click('.window-controls button:nth-child(2)')
    await new Promise(resolve=>setTimeout(resolve,250))
    assert.ok(win.isMaximized(),'real pointer maximizes window with settings open')
    await click('.window-controls button:nth-child(2)')
    await new Promise(resolve=>setTimeout(resolve,250))
    assert.equal(win.isMaximized(),false,'real pointer restores window with settings open')
    await click('.window-controls button:first-child',false)
    await new Promise(resolve=>setTimeout(resolve,250))
    assert.ok(win.isMinimized(),'real pointer minimizes window with settings open')
    win.restore();win.show();await paint()
    if(process.env.ORDESSA_STARTUP_SCREENSHOT) await writeFile(process.env.ORDESSA_STARTUP_SCREENSHOT.replace('.png','-settings.png'),(await win.capturePage()).toPNG())
    await click('[data-testid="add-config"]')
    assert.ok(await win.webContents.executeJavaScript(`(() => {
      const inputs=[...document.querySelectorAll('.wb-settings-section:not([hidden]) .mp-settings-form input')];
      return inputs.length>=5 && inputs.every(e=>{const r=e.getBoundingClientRect();return r.width>=120&&r.right<=innerWidth});
    })()`),'provider form fields have usable widths and stay inside the window')
    if(process.env.ORDESSA_STARTUP_SCREENSHOT) await writeFile(process.env.ORDESSA_STARTUP_SCREENSHOT.replace('.png','-provider-form.png'),(await win.capturePage()).toPNG())
    await win.webContents.executeJavaScript(`(() => {
      const field=document.querySelector('.mp-settings-form input[aria-label="名称"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(field,'UI probe draft');
      field.dispatchEvent(new Event('input',{bubbles:true}));
    })()`)
    await paint()
    await click('.wb-settings-nav button:nth-of-type(2)')
    assert.equal(await win.webContents.executeJavaScript('document.querySelectorAll(".wb-settings-section:not([hidden])").length'),1)
    if(process.env.ORDESSA_STARTUP_SCREENSHOT) await writeFile(process.env.ORDESSA_STARTUP_SCREENSHOT.replace('.png','-profile.png'),(await win.capturePage()).toPNG())
    await click('.wb-settings-nav button:first-of-type')
    assert.equal(await win.webContents.executeJavaScript('document.querySelector(".mp-settings-form input[aria-label=名称]").value'),'UI probe draft','actual settings navigation preserves an unsaved form')
    win.setSize(760,640);await paint()
    assert.ok(await win.webContents.executeJavaScript(`(() => {
      const root=document.querySelector('.mp-settings'),form=document.querySelector('.mp-settings-form');
      return getComputedStyle(root).gridTemplateColumns.split(' ').length===1&&getComputedStyle(form).gridTemplateColumns.split(' ').length===1&&document.documentElement.scrollWidth<=innerWidth;
    })()`),'narrow settings stack within their available content width')
    if(process.env.ORDESSA_STARTUP_SCREENSHOT) await writeFile(process.env.ORDESSA_STARTUP_SCREENSHOT.replace('.png','-provider-narrow.png'),(await win.capturePage()).toPNG())
    win.setSize(1220,800);await paint()
    // The narrow layout can have scrolled the form. Make cancel visible before pointer hit-testing.
    await win.webContents.executeJavaScript('document.querySelector("[data-testid=cancel-config]").scrollIntoView({block:"nearest"})')
    await paint()
    await click('[data-testid="cancel-config"]')
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'ESC'})
    win.webContents.sendInputEvent({type:'keyUp',keyCode:'ESC'})
    await paint()
    assert.equal(await win.webContents.executeJavaScript('!!document.querySelector(".wb-settings")'),false,'Escape closes settings')
    for(let n=0;n<3;n++) {
      await click('[aria-label="打开设置"]')
      await click('[aria-label="关闭设置"]')
      assert.equal(await win.webContents.executeJavaScript('!!document.querySelector(".wb-overlays")'),false,'no residual overlay after repeated close')
    }
    win.setSize(760,640);await paint()
    await click('[aria-label="打开设置"]')
    await click('[aria-label="关闭设置"]')
    await click('.wb-sidebar-collapse')
    await click('.conn-status-toggle')
    assert.ok(await win.webContents.executeJavaScript(`(() => {
      const m=document.querySelector('.conn-popover'),r=m.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&m.contains(document.elementFromPoint(r.left+20,r.top+20));
    })()`),'menu remains visible in collapsed sidebar bottom band and resized window')
    await click('.wb-sidebar-restore')
    assert.equal(await win.webContents.executeJavaScript('!!document.querySelector(".conn-popover")'),false,'outside click closes menu')
    win.setSize(1220,800);await paint()
    result.shellInteractions=true
    await win.webContents.executeJavaScript(`(() => {
      const pi=[...document.querySelectorAll('[data-chat-connector]')].find(e=>e.textContent==='ACP · pi');
      if(!pi)throw Error('Pi not offered');pi.click();
    })()`)
    let connected=false
    for(let n=0;n<80;n++) {
      connected=await win.webContents.executeJavaScript('!!document.querySelector("[data-testid=chat-new-session-empty]")')
      if(connected)break
      await new Promise(resolve=>setTimeout(resolve,100))
    }
    assert.ok(connected,'observed Pi connector must connect without creating a native session')
    await win.webContents.executeJavaScript('document.querySelector("[data-testid=chat-new-session-empty]").click()')
    await win.webContents.executeJavaScript('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
    assert.ok(await win.webContents.executeJavaScript('!!document.querySelector("[role=dialog]")'),'new conversation opens a visible project dialog')
    result.piConnected=true
    result.projectDialog=true
    win.webContents.sendInputEvent({type:'keyDown',keyCode:'ESC'})
    win.webContents.sendInputEvent({type:'keyUp',keyCode:'ESC'})
    await paint()
    await click('[aria-label="打开设置"]')
    const closed=new Promise(resolve=>win.once('closed',resolve))
    await click('.window-controls .wc-close',false)
    await Promise.race([closed,new Promise((_,reject)=>setTimeout(()=>reject(Error('window close did not execute')),3000))])
    assert.ok(win.isDestroyed(),'real pointer closes the isolated window with settings open')
    result.nativeWindowControls=true
    console.log('MODULAR_LOADER_READY '+JSON.stringify(result))
    app.quit()
  } catch(error) { console.error('STARTUP_UI_FAILED '+error.message);app.quit();process.exitCode=1 }
}
