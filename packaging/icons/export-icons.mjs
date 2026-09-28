// Export the application icon to every size the Linux hicolor theme needs
// (C-09 A2, PC-02).
//
// `assets/brand/icon.svg` is the single source of truth. The design is supplied
// later, so until it exists a built-in placeholder is used and the build says
// so out loud -- a placeholder must never be allowed to pass as the real
// design (see the `placeholder` field in the returned report).
//
// Swapping in the real design is a file drop, not a code change: this exporter
// reads the SVG at build time and nothing downstream knows or cares which of
// the two it rasterised.
//
// Rasterisation runs through the Electron binary we already ship, drawing into
// a canvas in a headless window. That is deliberate: the icon is rendered by
// the exact engine that will display it, and the release machine needs no
// native image tooling (no librsvg, no Inkscape).

import { readFileSync, writeFileSync, mkdirSync, existsSync, rmSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { ICON_SIZES, iconDest } from '../lib/layout.mjs'
import { repoRoot } from '../lib/identity.mjs'

export const SOURCE_SVG = path.join(repoRoot, 'assets/brand/icon.svg')

// Stand-in until the brand design lands. Same viewBox contract as a real
// design, so a later swap is purely a file replacement.
export const PLACEHOLDER_SVG = [
  '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">',
  '  <rect width="256" height="256" rx="56" fill="#12161f"/>',
  '  <path d="M64 176V80h26l38 56 38-56h26v96h-24v-52l-40 58-40-58v52z" fill="#5b8cff"/>',
  '</svg>',
].join('\n')

// Runs inside the generated Electron app. The config path arrives via the
// environment: inside Electron's main process process.argv does not line up
// with the CLI we spawned (Chromium inserts its own entries), and guessing the
// offset silently reads the wrong file.
function rendererSource() {
  return [
    "const fs = require('fs')",
    "const { app, BrowserWindow } = require('electron')",
    "",
    "app.disableHardwareAcceleration()",
    "",
    "app.whenReady().then(async () => {",
    "  const cfg = JSON.parse(fs.readFileSync(process.env.ORDESSA_ICON_CONFIG, 'utf8'))",
    "  const win = new BrowserWindow({ width: 8, height: 8, show: false })",
    "  await win.loadURL('data:text/html;charset=utf-8,<body></body>')",
    "  for (const entry of cfg.entries) {",
    "    // The SVG is bound to a window global first: executeJavaScript evaluates",
    "    // in page scope, so it cannot see this process's locals.",
    "    const script =",
    "      'window.__svgB64 = ' + JSON.stringify(entry.svgB64) + ';' +",
    "      'new Promise(function (res, rej) {' +",
    "      '  var img = new Image();' +",
    "      '  img.onload = function () {' +",
    '      \'    var c = document.createElement("canvas");\' +',
    "      '    c.width = ' + entry.size + '; c.height = ' + entry.size + ';' +",
    '      \'    var g = c.getContext("2d");\' +',
    "      '    g.clearRect(0, 0, ' + entry.size + ', ' + entry.size + ');' +",
    "      '    g.drawImage(img, 0, 0, ' + entry.size + ', ' + entry.size + ');' +",
    '      \'    res(c.toDataURL("image/png"));\' +',
    "      '  };' +",
    '      \'  img.onerror = function () { rej(new Error("svg decode failed")); };\' +',
    "      '  img.src = \"data:image/svg+xml;base64,\" + window.__svgB64;' +",
    "      '})'",
    "    const dataUrl = await win.webContents.executeJavaScript(script, true)",
    "    if (typeof dataUrl !== 'string' || dataUrl.indexOf('data:image/png;base64,') !== 0) {",
    "      throw new Error('icon render produced no PNG for size ' + entry.size)",
    "    }",
    "    fs.writeFileSync(entry.out, Buffer.from(dataUrl.split(',')[1], 'base64'))",
    "  }",
    "  app.exit(0)",
    "}).catch(function (err) {",
    "  console.error(String((err && err.stack) || err))",
    "  app.exit(1)",
    "})",
    "",
  ].join('\n')
}

function electronBinary() {
  const candidate = path.join(repoRoot, 'node_modules/electron/dist/electron')
  if (!existsSync(candidate)) {
    throw new Error('electron binary not found at ' + candidate + ' (run `npm ci` first)')
  }
  return candidate
}

// Chromium needs a display. On a headless build machine Xvfb supplies one; with
// no display the app cannot open at all, so we fail loudly here rather than
// quietly shipping a blank icon.
export function exportIcons({ workDir, outRoot, sizes = ICON_SIZES } = {}) {
  const placeholder = !existsSync(SOURCE_SVG)
  const svg = placeholder ? PLACEHOLDER_SVG : readFileSync(SOURCE_SVG, 'utf8')
  const stage = workDir || path.join(repoRoot, 'packaging/.icon-stage')
  const appDir = path.join(stage, 'app')

  // A stale stage from an earlier run would keep an old main.cjs alive.
  rmSync(stage, { recursive: true, force: true })
  mkdirSync(appDir, { recursive: true })

  // The SVG travels base64-encoded: a data URL built by concatenation breaks on
  // the '#' and '%' characters that appear in ordinary SVG source.
  const svgB64 = Buffer.from(svg, 'utf8').toString('base64')
  const entries = sizes.map(size => ({
    size,
    svgB64,
    out: path.join(outRoot, iconDest(size).replace(/^\//, '')),
  }))
  for (const entry of entries) mkdirSync(path.dirname(entry.out), { recursive: true })

  const cfgPath = path.join(stage, 'icons.json')
  writeFileSync(cfgPath, JSON.stringify({ entries }))
  writeFileSync(path.join(appDir, 'package.json'),
    JSON.stringify({ name: 'ordessa-icon-export', version: '0.0.0', main: 'main.cjs' }))
  writeFileSync(path.join(appDir, 'main.cjs'), rendererSource())

  const res = spawnSync(electronBinary(), ['--no-sandbox', '--disable-gpu', appDir], {
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: 120000,
    env: { ...process.env, ORDESSA_ICON_CONFIG: cfgPath },
  })
  if (res.status !== 0) {
    const noise = (res.stderr ? res.stderr.toString() : '')
      .split('\n')
      .filter(line => line && !/ERROR:|dbus|vaapi|zygote|GetTerminationStatus/.test(line))
      .join('\n')
    throw new Error('icon export failed (electron exit ' + res.status + '):\n' + noise)
  }
  for (const entry of entries) {
    if (!existsSync(entry.out)) throw new Error('icon export produced no file for size ' + entry.size)
  }
  return {
    placeholder,
    sizes,
    svg_source: placeholder ? 'packaging/icons/placeholder.svg' : 'assets/brand/icon.svg',
  }
}

if (import.meta.url === 'file://' + process.argv[1]) {
  const outRoot = process.argv[2] || path.join(repoRoot, 'packaging/.staging/root')
  console.log(JSON.stringify(exportIcons({ outRoot }), null, 2))
}
