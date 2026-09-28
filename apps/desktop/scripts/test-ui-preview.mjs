// Runs the test-only controlled visual preview (docs/ui-preview/*.png) against the real product UI
// with anonymous fixture connectors, then asserts the interaction regression checks.
import assert from 'node:assert/strict'
import { spawn, execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdtemp, mkdir, cp, writeFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { build } from 'esbuild'

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(appRoot, '..', '..')
const outDir = process.env.ORDESSA_PREVIEW_OUT ?? path.join(repoRoot, 'docs', 'ui-preview')

if (process.env.ORDESSA_PREVIEW_SKIP_BUILD !== '1' || !existsSync(path.join(appRoot, 'dist', 'electron-main.cjs')))
  execFileSync('npm', ['run', 'build'], { cwd: appRoot, stdio: 'inherit' })

const home = await mkdtemp(path.join(tmpdir(), 'ordessa-ui-preview-'))
try {
  const fixtureOut = path.join(home, 'extensions', 'example.ui-preview')
  await mkdir(fixtureOut, { recursive: true })
  await build({
    entryPoints: [path.join(repoRoot, 'examples/ui-preview/src/entry.tsx')], outfile: path.join(fixtureOut, 'entry.js'),
    bundle: true, format: 'esm', platform: 'browser', jsx: 'automatic', target: 'chrome132',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@ordessa/extension-api', '@extensions/*'],
  })
  await cp(path.join(repoRoot, 'examples/ui-preview/manifest.json'), path.join(fixtureOut, 'manifest.json'))
  await writeFile(path.join(home, 'extensions.json'), JSON.stringify({ enabled: [
    'ordessa.contracts', 'ordessa.agent-contracts', 'ordessa.commands', 'ordessa.workbench',
    'ordessa.connections', 'ordessa.agent-connections', 'ordessa.agent-sessions', 'ordessa.agent-conversation', 'example.ui-preview',
  ] }))
  // 预览驱动是**测试专用**产物：落在 dist-preview/，绝不进入 dist/（PA-11 代码卫生）。
  await mkdir(path.join(appRoot, 'dist-preview'), { recursive: true })
  await build({
    entryPoints: [path.join(appRoot, 'electron/preview-main.ts')], outfile: path.join(appRoot, 'dist-preview', 'preview-electron.cjs'),
    bundle: true, platform: 'node', format: 'cjs', target: 'node22', external: ['electron'],
  })

  const child = spawn(path.resolve(repoRoot, 'node_modules/electron/dist/electron'),
    ['--no-sandbox', '--disable-gpu', '--ozone-platform=x11', path.join(appRoot, 'dist-preview', 'preview-electron.cjs')], {
      cwd: appRoot, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, MODULAR_USER_DATA: home, ORDESSA_EXTENSION_HOME: home, ORDESSA_EMPTY_HOST: '0',
        ELECTRON_DISABLE_SECURITY_WARNINGS: 'true', ORDESSA_PREVIEW_OUT: outDir,
        ORDESSA_PREVIEW_RENDERER: path.join(appRoot, 'dist/renderer'),
        ORDESSA_PREVIEW_PRELOAD: path.join(appRoot, 'dist/preload.cjs') },
    })
  let output = ''
  for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => { output += chunk })
  const timedOut = await new Promise(resolve => {
    const timer = setTimeout(() => { child.kill('SIGKILL'); resolve(true) }, 120_000)
    child.once('close', () => { clearTimeout(timer); resolve(false) })
  })
  const line = output.split('\n').find(entry => entry.startsWith('PREVIEW_RESULT '))
  if (timedOut || !line) { console.error(output); throw Error('UI preview failed: ' + (output.match(/PREVIEW_FAILED[\s\S]*/)?.[0] ?? 'no result')) }
  const result = JSON.parse(line.slice('PREVIEW_RESULT '.length))
  console.log(JSON.stringify(result, null, 2))
  assert.equal(result.boot.nav, true); assert.equal(result.boot.connectors, 4)
  assert.equal(result.empty.placeholder, true); assert.equal(result.empty.emptyList, true)
  assert.equal(result.empty.rightInert, true); assert.equal(result.empty.bottomInert, true)
  assert.equal(result.history.opened, true); assert.equal(result.history.userRole, true)
  assert.equal(result.history.userRight, true); assert.equal(result.history.composer, true)
  assert.equal(result.history.toolCards, 3); assert.equal(result.history.thinkingCards, 1)
  assert.equal(result.sessionSwitch.switched, true); assert.equal(result.sessionSwitch.restored, true)
  assert.equal(result.send.enabled, true); assert.equal(result.send.replied, true)
  assert.equal(result.send.total, 6); assert.equal(result.send.userBubbles, 3)
  assert.equal(result.toolExpand.expanded, true); assert.equal(result.toolExpand.thinkingOpen, true)
  assert.equal(result.approval.card, true); assert.equal(result.approval.inThread, true)
  assert.deepEqual(result.approval.choices, ['Allow once', 'Always allow', 'Reject'])
  assert.equal(result.approvalRespond.resolved, true)
  assert.equal(result.running.chipRunning, true); assert.equal(result.running.stopVisible, true)
  assert.equal(result.running.stopEnabled, true); assert.equal(result.running.runningTool, true)
  assert.equal(result.stop.requested, true); assert.equal(result.stop.notice, true); assert.equal(result.stop.cancelled, true)
  assert.equal(result.gateRelease.backInHistory, true)
  assert.equal(result.layout.collapsed, true); assert.equal(result.layout.expanded, true)
  assert.equal(result.layout.separator, true)
  assert.ok(result.resize.dragged || result.resize.keyboardResized, `left panel resize ${result.resize.widthBefore} → ${result.resize.widthAfter}; keyboard ${JSON.stringify(result.resize.keyboard)}`)
  assert.equal(result.focus.focused, true)
  assert.equal(result.scroll.scrolled, true)
  assert.ok(result.narrow.overflowX <= 2, 'narrow window horizontal overflow: ' + result.narrow.overflowX)
  assert.equal(result.narrow.composerVisible, true)
  assert.deepEqual(result.consoleErrors, [])
  console.log('UI_PREVIEW_OK screenshots=' + outDir)
} finally { await rm(home, { recursive: true, force: true }) }
