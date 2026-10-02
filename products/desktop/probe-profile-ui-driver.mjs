/** Real Electron DOM probe; inference requires the launcher's explicit opt-in. */
export function sameSessionProfileReceipts(confirmations, brand, selected, nextSelected) {
  const first=confirmations.find(c=>brand+'::'+c.profileId===selected)
  const second=confirmations.find(c=>brand+'::'+c.profileId===nextSelected)
  return !!(first && second && first.configDigest && second.configDigest
    && first.configDigest!==second.configDigest && first.sessionRef && second.sessionRef
    && JSON.stringify(first.sessionRef)===JSON.stringify(second.sessionRef))
}
/** Raw text stays in memory. Only an explicit closed vocabulary can enter logs. */
export function safeAlertDiagnostic(alert) {
  const message=typeof alert==='string'?alert:alert?.message??''
  const codes=['CREDENTIAL_UNRESOLVED','CREDENTIAL_NOT_FOUND','SECRET_STORE_LOCKED','SECRET_STORE_TIMEOUT',
    'SECRET_STORE_UNAVAILABLE','UNAUTHENTICATED','ADAPTER_ARTIFACT_UNVERIFIED','ADAPTER_MISSING',
    'PROJECT_NOT_FOUND','PROJECT_INVALID','INVALID_REQUEST','PROFILE_CONFIGURATION_INVALID',
    'PROVIDER_NOT_FOUND','MODEL_NOT_FOUND','PROTOCOL_UNSUPPORTED','CONNECTION_LOST','SESSION_NEEDS_RECOVERY']
  const code=codes.find(code=>new RegExp('(^|[^A-Z_])'+code+'([^A-Z_]|$)').test(message))
    ?? (/连接已断开|ACP connection disposed/.test(message)?'CONNECTION_DISCONNECTED'
      : /Session list failed/.test(message)?'SESSION_CATALOG_FAILED'
      : /项目列表加载失败|Project list failed/.test(message)?'PROJECT_CATALOG_FAILED'
      : /模型列表加载失败/.test(message)?'MODEL_CATALOG_FAILED'
      : /工具栏.*失败/.test(message)?'TOOLBAR_FAILED':'UNCLASSIFIED_UI_ALERT')
  const location=['sidebar','chat','project-dialog','model-picker'].includes(alert?.location)?alert.location:'other'
  return {code,location}
}
export async function runSmoke({ win, app }) {
  const brand=process.env.ORDESSA_UI_PROBE_BRAND ?? 'codex'
  if(!['codex','pi','claude-code'].includes(brand)) throw Error('Unsupported UI probe brand')
  const originalFetch=globalThis.fetch
  const hostTrace=[]
  const confirmations=[]
  globalThis.fetch=async(url,options)=>{
    const start=Date.now()
    const operation=typeof url==='string' && url.includes('/wire/')?url.split('/wire/')[1]:null
    try {
      const response=await originalFetch(url,options)
      if(operation) {
        const body=await response.clone().json().catch(()=>null)
        hostTrace.push({operation,elapsedMs:Date.now()-start,error:body?.error?.code??null})
        if(operation.endsWith('beginTurnApplication')) {
          const receipt=body?.result?.data?.receipt
          if(receipt?.evidenceKind==='harness-api-confirmed') confirmations.push({
            profileId:receipt.profileId,configDigest:receipt.configDigest,sessionRef:receipt.sessionRef,
            runtimeGeneration:receipt.runtimeGeneration})
        }
        if(operation.endsWith('inspectSessionConfig')) {
          const data=body?.result?.data
          const receipt=data?.evidence?.receipt
          if(receipt?.evidenceKind==='harness-api-confirmed') confirmations.push({
            profileId:receipt.profileId, configDigest:receipt.configDigest, sessionRef:receipt.sessionRef,
            runtimeGeneration:receipt.runtimeGeneration})
          console.log('PROFILE_UI_CONFIG_SHAPE '+JSON.stringify({keys:Object.keys(data??{}),
            evidenceKeys:Object.keys(data?.evidence??{}), journalKeys:Object.keys(data?.evidence?.journal??{}),
            receiptKeys:Object.keys(data?.evidence?.receipt??{}), switchState:data?.switchState,
            pending:data?.pending===null, receiptKind:data?.evidence?.receipt?.evidenceKind,
            evidenceKind:data?.evidence?.evidenceKind, journalState:data?.evidence?.journal?.state}))
        }
      }
      return response
    } catch(error) {
      if(operation) hostTrace.push({operation,elapsedMs:Date.now()-start,failure:error.name})
      throw error
    }
  }
  try {
    await new Promise(resolve => setTimeout(resolve, 4000))
    await win.webContents.executeJavaScript(`(async()=>{
      document.querySelector('.conn-status-toggle')?.click();
      await new Promise(r=>setTimeout(r,300));
      const button=[...document.querySelectorAll('button[data-connection-id]')].find(b=>b.textContent.includes(${JSON.stringify('ACP · ')}+${JSON.stringify(brand)}));
      if(!button) throw Error('Actual brand connection unavailable');
      button.click();
      await new Promise(r=>setTimeout(r,3000));
      [...document.querySelectorAll('nav button')].find(b=>b.getAttribute('aria-label')==='Chat')?.click();
      [...document.querySelectorAll('button')].find(b=>b.textContent==='New session')?.click();
      await new Promise(r=>setTimeout(r,200));
      [...document.querySelectorAll('button')].find(b=>b.textContent==='Refresh projects')?.click();
      await new Promise(r=>setTimeout(r,1000));
      const project=[...document.querySelectorAll('.agent-project-picker button')].find(b=>b.textContent.includes('probe-project'));
      project?.click();
      await new Promise(r=>setTimeout(r,1000));
    })()`)
    const result = await win.webContents.executeJavaScript(`({
      ready: document.documentElement.dataset.ready,
      nodeAbsent: typeof require === 'undefined' && typeof process === 'undefined',
      buttons: [...document.querySelectorAll('button')].map(b => ({text:b.textContent, label:b.getAttribute('aria-label'), test:b.dataset.testid})),
      selects: [...document.querySelectorAll('select')].map(s => ({label:s.getAttribute('aria-label'), options:[...s.options].map(o => ({value:o.value,text:o.textContent}))})),
      alerts: [...document.querySelectorAll('[role="alert"]')].map(e=>({message:e.textContent,
        location:e.closest('.agent-sessions')?'sidebar':e.closest('[data-testid="chat-project-dialog"]')?'project-dialog':
          e.closest('[data-testid="model-selector"]')?'model-picker':e.closest('.chat-page')?'chat':'other'})),
      draftVisible:document.querySelector('.chat-page')?.dataset.pane?.startsWith('draft:')??false,
      projectSelected:!!document.querySelector('.agent-project-picker button[aria-pressed="true"]'),
      composerEnabled:!!document.querySelector('textarea.chat-input-text:not(:disabled)'),
      profileEnabled:!!document.querySelector('select[aria-label="配置预设"]:not(:disabled)')
    })`)
    console.log('PROFILE_UI_INVENTORY ' + JSON.stringify({brand,ready:result.ready,nodeAbsent:result.nodeAbsent,
      alertCount:result.alerts.length,profileOptionCount:result.selects.find(s=>s.label==='配置预设')?.options.length??0,
      brandsVisible:['pi','codex','claude-code'].every(id=>result.buttons.some(b=>b.text.includes('ACP · '+id)))}))
    console.log('PROFILE_UI_DIAGNOSTIC '+JSON.stringify({brand,phase:'inventory',
      alerts:result.alerts.map(safeAlertDiagnostic),draftVisible:result.draftVisible,
      projectSelected:result.projectSelected,composerEnabled:result.composerEnabled,profileEnabled:result.profileEnabled}))
    if(!result.nodeAbsent || result.alerts.length
        || !result.selects.some(s=>s.label==='配置预设' && s.options.some(o=>o.text==='UI official probe')
          && s.options.some(o=>o.text==='UI next-turn probe')))
      throw Error('Actual Profile UI inventory incomplete')
    if(process.env.ORDESSA_UI_PROBE_ALLOW_MODEL_CALLS === '1') {
      const selected = await win.webContents.executeJavaScript(`(async()=>{
        const picker=document.querySelector('select[aria-label="配置预设"]');
        if(!picker || picker.disabled) throw Error('Actual Profile picker unavailable');
        picker.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
        await new Promise(r=>setTimeout(r,300));
        const option=[...picker.options].find(o=>o.textContent==='UI official probe');
        if(!option) throw Error('Seed Profile absent');
        picker.value=option.value; picker.dispatchEvent(new Event('change',{bubbles:true}));
        await new Promise(r=>setTimeout(r,300));
        return picker.value;
      })()`)
      if(!selected.startsWith(brand+'::')) throw Error('Profile selection did not stick')
      const firstMessage=process.env.ORDESSA_UI_PROBE_NATIVE_TOOL==='1'
        ? 'Use your native shell tool to run pwd exactly once in the current project. Do not read or modify any files. Then reply OK.'
        : 'Reply exactly OK. Do not use tools or access files.'
      await win.webContents.executeJavaScript(`(()=>{
        const input=document.querySelector('textarea.chat-input-text');
        if(!input || input.disabled) throw Error('Actual composer unavailable');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,${JSON.stringify(firstMessage)});
        input.dispatchEvent(new Event('input',{bubbles:true}));
      })()`)
      await new Promise(resolve=>setTimeout(resolve,300))
      await win.webContents.executeJavaScript(`(()=>{
        const send=document.querySelector('[data-testid="chat-send"]');
        if(!send || send.disabled) throw Error('Actual send disabled after Profile selection');
        send.click();
      })()`)
      let completed=false
      let originalPane
      let selectedDuringRun=null
      for(let i=0;i<180;i++) {
        const state=await win.webContents.executeJavaScript(`({
          alerts:[...document.querySelectorAll('[role="alert"]')].map(e=>e.textContent),
          pane:document.querySelector('.chat-page')?.dataset.pane,
          run:document.querySelector('.chat-run-state')?.dataset.status,
          assistant:document.querySelector('.chat-message-assistant')?.innerText,
          messageStatus:document.querySelector('.chat-message-assistant')?.dataset.status,
          pending:!!document.querySelector('[data-testid="chat-send-pending"]')
        })`)
        if(state.alerts.length) {
          console.log('PROFILE_UI_FAILURE_STATE '+JSON.stringify({brand,alertCount:state.alerts.length,run:state.run,
            alerts:state.alerts.map(safeAlertDiagnostic)}))
          throw Error('Actual send refused')
        }
        if(process.env.ORDESSA_UI_PROBE_DURING_OUTPUT==='1' && !selectedDuringRun
            && state.pane?.startsWith('session:') && state.run==='running' && state.assistant?.trim()) {
          selectedDuringRun=await win.webContents.executeJavaScript(`(()=>{
            const picker=document.querySelector('select[aria-label="配置预设"]');
            if(!picker || picker.disabled) throw Error('Profile picker disabled during active turn');
            const option=[...picker.options].find(o=>o.textContent==='UI next-turn probe');
            if(!option) throw Error('Next Profile missing during active turn');
            picker.value=option.value; picker.dispatchEvent(new Event('change',{bubbles:true}));
            return picker.value;
          })()`)
        }
        if(state.pane?.startsWith('session:') && !state.pending && state.run!=='running' && state.run!=='starting' && state.assistant?.trim() && state.messageStatus==='complete') {
          completed=true; console.log('PROFILE_UI_CHAT_CONFIRMED '+JSON.stringify({brand,profileSelected:true,realText:true,prompt:1,run:state.run})); break
        }
        await new Promise(resolve=>setTimeout(resolve,1000))
      }
      if(!completed) throw Error('Actual UI turn did not complete; no automatic retry')
      if(process.env.ORDESSA_UI_PROBE_NATIVE_TOOL==='1') {
        const tools=await win.webContents.executeJavaScript(`document.querySelectorAll('[data-testid="chat-tool-summary"]').length`)
        if(tools<1) throw Error('Native tool call absent from actual UI')
        console.log('PROFILE_UI_NATIVE_TOOL_CONFIRMED '+JSON.stringify({nativeToolVisible:true,currentTurnCompleted:true,externalPermitRequired:false}))
      }
      if(process.env.ORDESSA_UI_PROBE_DURING_OUTPUT==='1') {
        if(!selectedDuringRun || hostTrace.filter(t=>t.operation.endsWith('beginTurnApplication')).length!==1)
          throw Error('Active-turn selection missing or applied prematurely')
        console.log('PROFILE_UI_ACTIVE_SELECTION_CONFIRMED '+JSON.stringify({currentTurnCompleted:true,applicationsBeforeNextSend:1}))
      }
      originalPane=await win.webContents.executeJavaScript(`document.querySelector('.chat-page')?.dataset.pane`)
      const nextSelected=await win.webContents.executeJavaScript(`(async()=>{
        const picker=document.querySelector('select[aria-label="配置预设"]');
        if(!picker || picker.disabled) throw Error('Session Profile picker unavailable');
        picker.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true}));
        await new Promise(r=>setTimeout(r,300));
        const option=[...picker.options].find(o=>o.textContent==='UI next-turn probe');
        if(!option) throw Error('Next Profile absent');
        picker.value=option.value; picker.dispatchEvent(new Event('change',{bubbles:true}));
        await new Promise(r=>setTimeout(r,300));
        const input=document.querySelector('textarea.chat-input-text');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Reply exactly READY. Do not use tools or access files.');
        input.dispatchEvent(new Event('input',{bubbles:true}));
        return picker.value;
      })()`)
      if(selectedDuringRun && selectedDuringRun!==nextSelected) throw Error('Active-turn selection was not retained')
      if(nextSelected===selected || !nextSelected.startsWith(brand+'::')) throw Error('Next Profile not selected')
      await new Promise(resolve=>setTimeout(resolve,300))
      await win.webContents.executeJavaScript(`(()=>{
        const send=document.querySelector('[data-testid="chat-send"]');
        if(!send || send.disabled) throw Error('Next-turn send unavailable');
        send.click();
      })()`)
      completed=false
      for(let i=0;i<180;i++) {
        const state=await win.webContents.executeJavaScript(`({
          alerts:[...document.querySelectorAll('[role="alert"]')].map(e=>e.textContent),
          pane:document.querySelector('.chat-page')?.dataset.pane,
          run:document.querySelector('.chat-run-state')?.dataset.status,
          messages:[...document.querySelectorAll('.chat-message-assistant')].map(e=>({text:e.innerText,status:e.dataset.status})),
          pending:!!document.querySelector('[data-testid="chat-send-pending"]')
        })`)
        if(state.alerts.length) {
          console.log('PROFILE_UI_FAILURE_STATE '+JSON.stringify({brand,phase:'next-turn',alerts:state.alerts.map(safeAlertDiagnostic)}))
          throw Error('Next turn refused')
        }
        if(state.pane!==originalPane) throw Error('Profile switch replaced the visible session')
        if(state.messages.length>=2 && state.messages.at(-1).text?.trim() && state.messages.at(-1).status==='complete'
            && !state.pending && state.run!=='running' && state.run!=='starting') {
          if(!sameSessionProfileReceipts(confirmations,brand,selected,nextSelected)) throw Error('Same-session changed Profile receipts absent')
          console.log('PROFILE_UI_SWITCH_CONFIRMED '+JSON.stringify({brand,sameSession:true,changedConfig:true,prompts:2,run:state.run,
            distinctUpstreamModelsProved:false})); completed=true; break
        }
        await new Promise(resolve=>setTimeout(resolve,1000))
      }
      if(!completed) throw Error('Next-turn UI switch did not complete; no automatic retry')
    }
  } catch(error) {
    const failures={
      'Actual Profile UI inventory incomplete':'UI_INVENTORY_INCOMPLETE',
      'Actual UI turn did not complete; no automatic retry':'FIRST_TURN_TIMEOUT',
      'Next-turn UI switch did not complete; no automatic retry':'NEXT_TURN_TIMEOUT',
      'Same-session changed Profile receipts absent':'PROFILE_RECEIPT_UNCONFIRMED',
      'Active-turn selection missing or applied prematurely':'ACTIVE_SELECTION_UNCONFIRMED',
      'Actual send refused':'FIRST_SEND_REFUSED',
      'Next turn refused':'NEXT_SEND_REFUSED',
      'Profile switch replaced the visible session':'SESSION_IDENTITY_CHANGED',
    }
    console.log('PROFILE_UI_FAILED '+JSON.stringify({brand,
      code:failures[error?.message]??safeAlertDiagnostic(error?.message).code}))
  } finally { globalThis.fetch=originalFetch; console.log('PROFILE_UI_WIRE_TRACE '+JSON.stringify(hostTrace)); app.quit() }
}
