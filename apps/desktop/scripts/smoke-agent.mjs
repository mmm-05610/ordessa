export async function verifyAgentUI(win) {
  return win.webContents.executeJavaScript(`(async () => {
    const wait = () => new Promise(r => setTimeout(r, 100));
    const content = () => document.querySelector('.probe-viewport').textContent;
    const check = (condition, message) => { if (!condition) throw Error(message); };
    const click = async text => {
      const b = [...document.querySelectorAll('.agent-probe button')].find(b => b.textContent === text);
      check(b && !b.disabled, 'Missing/disabled button: '+text); b.click(); await wait();
    };
    const send = async text => {
      const input = document.querySelector('.agent-probe textarea');
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,text);
      input.dispatchEvent(new Event('input',{bubbles:true})); await wait(); await click('发送');
    };
    check(content().includes('恢复的历史回答'), 'history missing');
    await send('测试发送'); check(content().includes('测试发送'),'composer not wired');
    await click('流式①'); check(content().includes('第一段流式输出'),'first delta missing');
    await click('流式②'); check(content().includes('第二段已到达'),'second delta missing');
    await click('工具开始'); check(document.querySelector('[data-testid="agent-tool"]').textContent.includes('执行中'),'tool pending missing');
    await click('工具结果'); check(content().includes('文件内容（模拟）'),'tool result missing');
    await click('停止'); check(document.querySelector('[data-testid="agent-state"]').textContent.includes('cancelled'),'cancel not wired');
    await click('迟到事件'); check(!content().includes('STALE_EVENT'),'stale event leaked');
    await click('会话 B'); check(!content().includes('测试发送'),'A leaked into B');
    await send('B独立消息'); await click('失败');
    check(document.querySelector('[data-testid="agent-state"]').textContent.includes('error'),'error not distinct');
    await click('会话 A'); check(content().includes('测试发送') && !content().includes('B独立消息'),'restore crossed sessions');
    await send('结束验证'); await click('完成');
    check(document.querySelector('[data-testid="agent-state"]').textContent.includes('done'),'completion missing');
    return { history: true, composer: true, streaming: true, tools: true, cancel: true, staleRejected: true, sessionRestore: true, failure: true, completion: true };
  })()`)
}
