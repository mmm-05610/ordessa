// PA-11：主进程内联的 smoke 驱动（约 200 行 executeJavaScript）已迁到这里。
// 主进程**只在** `ORDESSA_SMOKE_DRIVER` 指向本文件时按路径动态加载它，
// 因此这些测试驱动代码永远不会进 `dist/electron-main.cjs`（构建期的 release-hygiene 闸门会验）。
import { writeFile } from 'node:fs/promises'
import path from 'node:path'
import { verifyAgentUI } from './smoke-agent.mjs'
import { probeUiFoundations, tabForwardFrom } from './smoke-ui.mjs'

/** 驱动一次 smoke 会话：探测渲染进程、跑各个门，最后按结果退出。 */
export async function runSmoke({ win, app }) {
  const result = await win.webContents.executeJavaScript(`(async () => {
    for (let i = 0; i < 100 && !document.documentElement.dataset.ready; i++) await new Promise(r => setTimeout(r, 50));
    for (let i = 0; i < 20 && !document.documentElement.dataset.settled; i++) await new Promise(r => setTimeout(r, 50));
    const pages = [...document.querySelectorAll('[data-region] header [role="group"] button')].map(b => b.textContent);
    const views = [];
    for (const button of document.querySelectorAll('[data-region] header [role="group"] button')) {
      button.click(); await new Promise(r => setTimeout(r, 30));
      const increment = document.querySelector('[data-testid="increment"]');
      if (increment) { increment.click(); await new Promise(r => setTimeout(r, 30)); }
      views.push(document.querySelector('[data-region="main"]').textContent);
    }
    // A single-view region renders without a tab strip; the shell exposes it via data-active-view.
    for (const region of document.querySelectorAll('[data-region][data-active-view]')) {
      pages.push(region.getAttribute('data-active-view'));
      if (region.getAttribute('data-region') === 'main') {
        await new Promise(r => setTimeout(r, 30));
        const increment = document.querySelector('[data-testid="increment"]');
        if (increment) { increment.click(); await new Promise(r => setTimeout(r, 30)); }
        views.push(region.textContent);
      }
    }
    return {
      ready: document.documentElement.dataset.ready === 'true', pages, views,
      // A root view mounted without any Workbench region is otherwise invisible to this probe.
      rootText: document.querySelector('#root')?.textContent ?? '',
      activeElement: document.activeElement ? document.activeElement.tagName + ':' + (document.activeElement.getAttribute('data-testid') ?? '') : 'none',
      rootMounted: !!document.querySelector('[data-testid="workspace"]'),
      emptyHost: !!document.querySelector('[data-testid="empty"]'),
      errors: [...document.querySelectorAll('[role="alert"]')].map(p => p.textContent),
      starting: [...document.querySelectorAll('[role="status"]')].map(p => p.textContent),
      nodeAbsent: typeof require === 'undefined' && typeof process === 'undefined',
      bridgeKeys: Object.keys(window.extensionCatalog ?? {}),
    };
  })()`)
  // Real keyboard focus: a Tab keystroke through the browser input stack must move
  // focus onto an actual focusable control (U15/V04 keyboard acceptance).
  win.webContents.sendInputEvent({ type: 'keyDown', keyCode: 'Tab' })
  await new Promise(resolve => setTimeout(resolve, 120))
  Object.assign(result, { activeElementAfterTab: await win.webContents.executeJavaScript(
    `document.activeElement ? document.activeElement.tagName + ':' + (document.activeElement.getAttribute('data-testid') ?? '') : 'none'`) })
  // C8 V03/V04: real layout and computed style at two widths, plus keyboard order.
  if (process.env.MODULAR_UI_FOUNDATIONS === '1') {
    const shots = process.env.MODULAR_UI_SHOTS
    const probe360 = await probeUiFoundations(win, 360)
    const probe768 = await probeUiFoundations(win, 768)
    Object.assign(result, { probe360, probe768, tabFromInput: await tabForwardFrom(win, 'ui-input') })
    if (shots) {
      // A hidden smoke window captures blank; show it only for the evidence images.
      win.showInactive()
      await new Promise(resolve => setTimeout(resolve, 150))
      await probeUiFoundations(win, 360)
      await writeFile(path.join(shots, 'viewport-360.png'), (await win.webContents.capturePage()).toPNG())
      await probeUiFoundations(win, 768)
      await writeFile(path.join(shots, 'viewport-768.png'), (await win.webContents.capturePage()).toPNG())
    }
  }
  if (process.env.MODULAR_AGENT_SMOKE === '1') {
    Object.assign(result, { agent: await verifyAgentUI(win) })
    if (process.env.MODULAR_SCREENSHOT) {
      win.showInactive()
      await new Promise(resolve => setTimeout(resolve, 150))
      await writeFile(process.env.MODULAR_SCREENSHOT, (await win.webContents.capturePage()).toPNG())
    }
  }
  if (process.env.MODULAR_AGENT_SHELL_SMOKE === '1') {
    Object.assign(result, { agentShell: await win.webContents.executeJavaScript(`(async () => {
      const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
      const entry = [...document.querySelectorAll('nav button')].find(button => button.getAttribute('aria-label') === 'Agents');
      entry?.click(); await wait(100);
      const emptyConversation = !!document.querySelector('.agent-placeholder')?.textContent.includes('Choose a connection');
      const toggle = document.querySelector('.conn-status-toggle');
      toggle?.click(); await wait(100);
      const popover = document.querySelector('[role="group"][aria-label="Agent connections"]');
      const connectorButtons = popover ? [...popover.querySelectorAll('button')] : [];
      const tab = label => [...document.querySelectorAll('[data-region] header [role="group"] button')].find(button => button.textContent === label);
      tab('Sessions')?.click(); await wait(100);
      const panel = document.querySelector('.agent-sessions');
      const panelButtons = panel ? [...panel.querySelectorAll('button')] : [];
      return {
        navigation: !!entry, statusbarToggle: !!toggle, popover: !!popover,
        codexVisible: connectorButtons.some(button => button.textContent.includes('Codex')),
        piVisible: connectorButtons.some(button => button.textContent.includes('Pi')),
        serverVisible: connectorButtons.some(button => button.textContent.includes('Ordessa Server')),
        emptyConversation,
        newSessionEntry: panelButtons.some(button => button.textContent === 'New session'),
        panelOwnConnectionUi: !!panel?.querySelector('.conn-status') || panelButtons.some(button => ['Reconnect', 'Connect'].includes(button.textContent)),
        projectPicker: !!document.querySelector('.agent-project-picker'),
        rightRequests: [...document.querySelectorAll('[data-region="right"] button')].some(button => button.textContent === 'Requests'),
        rightTab: !!tab('Requests'),
      };
    })()`) })
  }
  if (process.env.MODULAR_NATIVE_PAIR_SMOKE === '1') {
    // C-0048: UI-only paired gate. The script may refresh/open a project but has no Send action.
    const expectedConnection = `ordessa:${process.env.ORDESSA_SERVER_ORIGIN}|${process.env.ORDESSA_PAIR_SERVER_ID}`
    const projectPath = process.env.ORDESSA_PAIR_PROJECT_PATH ?? ''
    Object.assign(result, { nativePair: await win.webContents.executeJavaScript(`(async () => {
      const waitFor = async predicate => {
        for (let i = 0; i < 80; i++) {
          if (predicate()) return true;
          await new Promise(resolve => setTimeout(resolve, 50));
        }
        return false;
      };
      const tab = label => [...document.querySelectorAll('[data-region] header [role="group"] button')].find(button => button.textContent === label);
      const agents = [...document.querySelectorAll('nav button')].find(button => button.getAttribute('aria-label') === 'Agents');
      agents?.click();
      await waitFor(() => !!document.querySelector('.conn-status-toggle'));
      document.querySelector('.conn-status-toggle')?.click();
      await waitFor(() => !!document.querySelector('[role="group"][aria-label="Agent connections"]'));
      const buttons = [...document.querySelectorAll('[role="group"][aria-label="Agent connections"] button[data-connection-id]')];
      const server = buttons.find(button => button.textContent.includes('Ordessa Server'));
      const oneServer = buttons.length === 1 && !!server;
      const connectionIdMatches = server?.getAttribute('data-connection-id') === ${JSON.stringify(expectedConnection)};
      server?.click();
      const connected = await waitFor(() => !!document.querySelector('.conn-dot-connected'));
      tab('Sessions')?.click();
      await waitFor(() => !!document.querySelector('.agent-sessions'));
      const newSession = [...document.querySelectorAll('.agent-sessions button')].find(button => button.textContent === 'New session');
      newSession?.click();
      await waitFor(() => !!document.querySelector('.agent-project-picker'));
      const refresh = [...document.querySelectorAll('.agent-sessions button')].find(button => button.textContent === 'Refresh projects');
      refresh?.click();
      const listed = await waitFor(() => [...document.querySelectorAll('.agent-project-picker button')]
        .some(button => button.textContent.trim() === ${JSON.stringify(projectPath)}));
      const project = [...document.querySelectorAll('.agent-project-picker button')]
        .find(button => button.textContent.trim() === ${JSON.stringify(projectPath)});
      project?.click();
      const selected = await waitFor(() => [...document.querySelectorAll('.agent-project-picker button')]
        .some(button => button.textContent.trim() === ${JSON.stringify(projectPath)} && button.getAttribute('aria-pressed') === 'true'));
      tab('Conversation')?.click();
      await waitFor(() => !!document.querySelector('.agent-compose'));
      const start = [...document.querySelectorAll('.agent-compose button')].find(button => button.textContent === 'Start session');
      return {
        oneServer, connectionIdMatches, connected, listed, selected,
        draftVisible: !!document.querySelector('.agent-conversation-head')?.textContent.includes('NEW SESSION'),
        projectGateOpen: !document.querySelector('.agent-compose-block'),
        emptyComposerCannotSend: !!start && start.disabled && !document.querySelector('.agent-compose textarea')?.value,
        directConnectorsAbsent: !buttons.some(button => /Codex|Pi/.test(button.textContent)),
        errorsAbsent: [...document.querySelectorAll('[role="alert"]')].length === 0,
      };
    })()`) })
  }
  if (process.env.MODULAR_FE_TWO_TURN_SMOKE === '1') {
    Object.assign(result, { twoTurn: await win.webContents.executeJavaScript(`(async () => {
      const waitFor = async (predicate, limit = 900) => {
        for (let i = 0; i < limit; i++) {
          if (predicate()) return true;
          await new Promise(resolve => setTimeout(resolve, 100));
        }
        return false;
      };
      const compose = async (value, label) => {
        const field = document.querySelector('.agent-compose textarea');
        if (!field) return false;
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, value);
        field.dispatchEvent(new Event('input', { bubbles: true }));
        const button = () => [...document.querySelectorAll('.agent-compose button')].find(item => item.textContent === label);
        if (!await waitFor(() => !!button() && !button().disabled, 50)) return false;
        button().click();
        return true;
      };
      const messages = () => [...document.querySelectorAll('.agent-message')];
      const firstStarted = await compose('Reply exactly HD002_FE_OK_1.', 'Start session');
      if (firstStarted) console.log('HD002_FE_ATTEMPT_1');
      const firstOpened = firstStarted && await waitFor(() =>
        document.querySelector('.agent-conversation-head small')?.textContent === 'SESSION');
      const firstReply = firstOpened && await waitFor(() =>
        messages().length >= 2 && messages().at(-1)?.textContent?.includes('HD002_FE_OK_1'));
      const secondStarted = firstReply && await compose('Reply exactly HD002_FE_OK_2.', 'Send');
      if (secondStarted) console.log('HD002_FE_ATTEMPT_2');
      const secondReply = secondStarted && await waitFor(() =>
        messages().length >= 4 && messages().at(-1)?.textContent?.includes('HD002_FE_OK_2'));
      return { firstStarted, firstOpened, firstReply, secondStarted, secondReply,
        stillSession: document.querySelector('.agent-conversation-head small')?.textContent === 'SESSION',
        errorsAbsent: [...document.querySelectorAll('[role="alert"]')].length === 0,
        attemptedSends: Number(!!firstStarted) + Number(!!secondStarted) };
    })()`) })
  }
  if (process.env.MODULAR_STORAGE_RESTART_SMOKE === '1') {
    // Test-only fixture: non-secret placeholder selection values, namespaced by origin+serverId (FC-0034/0035).
    Object.assign(result, { storage: await win.webContents.executeJavaScript(`(async () => {
      const key = serverId => 'ordessa.cp-project|http://127.0.0.1:4471|' + serverId
      const payload = JSON.stringify({ workspaceId: 'ws-fixture-A', normalizedPath: '/fixture/project-A' })
      if (${JSON.stringify(process.env.ORDESSA_SMOKE_STORAGE_MODE ?? 'read')} === 'write') {
        localStorage.setItem(key('srv-A'), payload)
        return { wrote: key('srv-A'), echo: localStorage.getItem(key('srv-A')) }
      }
      return { valueA: localStorage.getItem(key('srv-A')), valueB: localStorage.getItem(key('srv-B')) }
    })()`) })
  }
  console.log('MODULAR_LOADER_READY', JSON.stringify(result))
  // C-0074 paired diagnostic needs the command-line default NetLog to flush on normal quit.
  if ((process.env.MODULAR_PAIR_NETWORK_DIAG === '1' && process.env.MODULAR_NATIVE_PAIR_SMOKE === '1') ||
      process.env.MODULAR_FE_TWO_TURN_SMOKE === '1') app.quit()
  else app.exit(result.ready && result.nodeAbsent ? 0 : 1)
}

