// Assemble the /opt/ordessa tree and build the .deb (PC-01..PC-07).
//
// Everything here happens at BUILD time. Nothing in this script runs on a user
// machine, and nothing in the produced package builds anything: the Python
// interpreter, the Server dependency closure, the ACP bridge and the Electron
// application are all placed as finished artefacts (FR-071).
//
// Usage:
//   node packaging/build-deb.mjs [--skip-pip] [--stage <dir>] [--out <dir>]
//
// Pinned inputs (changing one changes the release identity):
//   PYTHON_TARBALL_SHA256  python-build-standalone CPython 3.12.14
//   BRIDGE_SHA256_EXPECTED the reproducible ACP bridge from docs/baseline.md

import { execFileSync, spawnSync } from 'node:child_process'
import {
  mkdirSync, writeFileSync, readFileSync, existsSync, rmSync, cpSync,
  chmodSync, symlinkSync, readlinkSync, statSync,
} from 'node:fs'
import { createHash } from 'node:crypto'
import path from 'node:path'
import { repoRoot, identity } from './lib/identity.mjs'
import { layout, ICON_SIZES, iconDest } from './lib/layout.mjs'
import { sha256File, sha256Bytes, treeHash, treeListing } from './lib/hash.mjs'
import { exportIcons } from './icons/export-icons.mjs'
import { aggregateLicenses } from './licenses/aggregate.mjs'

// python-build-standalone release 20260924, CPython 3.12.14, install_only
// (stripped). The hash is the release identity: a build that fetches a
// different tarball must fail here rather than quietly ship a different
// interpreter.
export const PYTHON_URL = 'https://github.com/astral-sh/python-build-standalone/releases/download/20260924/' +
  'cpython-3.12.14%2B20260924-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz'
export const PYTHON_TARBALL_SHA256 = '269b2c99e4db15b242bf01832f4fea1e8f1a664f273cff519393f296e9820b41'
export const PYTHON_VERSION = '3.12.14'
export const PYTHON_RELEASE_TAG = '20260924'

// docs/baseline.md records this as the reproducible bridge hash. It is checked,
// not assumed -- see the note in the report about the observed mismatch.
export const BRIDGE_SHA256_EXPECTED = '5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea'

const args = process.argv.slice(2)
const flag = name => args.includes('--' + name)
const opt = (name, fallback) => {
  const i = args.indexOf('--' + name)
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback
}

const STAGE = path.resolve(opt('stage', path.join(repoRoot, 'packaging/.staging/root')))
const OUT = path.resolve(opt('out', path.join(repoRoot, 'packaging/.out')))
const CACHE = opt('cache', process.env.ORDESSA_PYTHON_CACHE || path.join(repoRoot, 'packaging/.cache'))

const log = (...a) => console.log('[build-deb]', ...a)
const steps = []

function step(name, fn) {
  return async (...args) => {
    const t0 = Date.now()
    const out = await fn(...args)
    steps.push({ name, ms: Date.now() - t0 })
    return out
  }
}

function run(cmd, cmdArgs, opts = {}) {
  const res = spawnSync(cmd, cmdArgs, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024, ...opts })
  if (res.status !== 0) {
    throw new Error(cmd + ' ' + cmdArgs.join(' ') + ' failed (' + res.status + '):\n' +
      (res.stderr || '') + (res.stdout || ''))
  }
  return res
}

// -- 1. python runtime -------------------------------------------------------

async function stagePython() {
  const tarball = path.join(CACHE, 'cpython.tar.gz')
  mkdirSync(CACHE, { recursive: true })

  if (!existsSync(tarball)) {
    log('fetching CPython ' + PYTHON_VERSION + ' (pinned sha256)…')
    const res = spawnSync('curl', ['-sSL', '--max-time', '600', '-o', tarball, PYTHON_URL], { encoding: 'utf8' })
    if (res.status !== 0) throw new Error('python runtime download failed: ' + PYTHON_URL)
  }

  const actual = sha256File(tarball)
  if (actual !== PYTHON_TARBALL_SHA256) {
    // Never "proceed anyway". A different interpreter under the same version
    // number is exactly the kind of drift a release must not carry.
    throw new Error('python runtime hash mismatch:\n  expected ' + PYTHON_TARBALL_SHA256 + '\n  actual   ' + actual)
  }

  const dest = path.join(STAGE, layout.python.replace(/^\//, ''))
  rmSync(dest, { recursive: true, force: true })
  mkdirSync(dest, { recursive: true })
  run('tar', ['xzf', tarball, '-C', dest, '--strip-components=1'])
  return { url: PYTHON_URL, sha256: actual, version: PYTHON_VERSION, release: PYTHON_RELEASE_TAG, dest }
}

// -- 2. server dependencies --------------------------------------------------

function stageServerDeps(python) {
  const pythonBin = path.join(python.dest, 'bin/python3.12')
  const lock = path.join(repoRoot, 'apps/server/lockfiles/server-linux-py312.txt')
  if (!existsSync(lock)) throw new Error('server lockfile missing: ' + lock)
  if (flag('skip-pip')) {
    log('SKIPPING pip install (--skip-pip): the bundle will NOT run on a clean machine')
  } else {
    log('installing the verified Server dependency closure into the bundled interpreter…')
    run(pythonBin, ['-m', 'pip', 'install', '--no-compile', '--no-cache-dir', '-r', lock], {
      env: { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: '1' },
    })
  }
  const sitePackages = path.join(python.dest, 'lib/python3.12/site-packages')
  return { source: 'apps/server/lockfiles/server-linux-py312.txt', dest: sitePackages, lockSha256: sha256File(lock) }
}

// -- 3. the product's own Python packages ------------------------------------

function stageProductPackages(python) {
  // Installed non-editable: an editable install points at the repository, which
  // must not exist on a user machine.
  const pythonBin = path.join(python.dest, 'bin/python3.12')
  const packages = [
    'packages/pacthold',
    'packages/server-plugin-api',
    'apps/server',
  ]
  if (flag('skip-pip')) return { installed: [], skipped: true }
  log('installing the product Python packages (non-editable)…')
  for (const rel of packages) {
    const dir = path.join(repoRoot, rel)
    if (!existsSync(dir)) {
      log('  (skipping absent ' + rel + ')')
      continue
    }
    run(pythonBin, ['-m', 'pip', 'install', '--no-compile', '--no-cache-dir', '--no-deps', dir], {
      env: { ...process.env, PIP_DISABLE_PIP_VERSION_CHECK: '1' },
    })
  }
  return { installed: packages }
}

// -- 4. the Electron application ---------------------------------------------

function stageApp(id) {
  const appDir = path.join(STAGE, layout.app.replace(/^\//, ''))
  rmSync(appDir, { recursive: true, force: true })
  mkdirSync(appDir, { recursive: true })

  // The prebuilt application: apps/desktop/dist plus the assembled product.
  const desktopDist = path.join(repoRoot, 'apps/desktop/dist')
  const productDist = path.join(repoRoot, 'products/desktop/dist')
  for (const src of [desktopDist, productDist]) {
    if (!existsSync(src)) throw new Error('missing build output: ' + src + ' (run `npm run build` first)')
    cpSync(src, path.join(appDir, path.basename(src)), { recursive: true })
  }

  // The Electron runtime itself. Shipped whole; the launcher execs it directly.
  const electronDist = path.join(repoRoot, 'node_modules/electron/dist')
  if (!existsSync(electronDist)) throw new Error('electron runtime missing: ' + electronDist)
  cpSync(electronDist, path.join(appDir, 'electron-dist'), { recursive: true })
  // Flatten so the launcher's fixed path (app/electron) is the real binary.
  for (const entry of ['electron', 'chrome-sandbox', 'chrome_crashpad_handler', 'resources.pak', 'icudtl.dat', 'v8_context_snapshot.bin', 'snapshot_blob.bin', 'vk_swiftshader', 'libEGL.so', 'libGLESv2.so', 'libffmpeg.so', 'locales']) {
    const from = path.join(electronDist, entry)
    if (!existsSync(from)) continue
    const st = statSync(from)
    if (st.isDirectory()) cpSync(from, path.join(appDir, entry), { recursive: true })
    else cpSync(from, path.join(appDir, entry))
  }
  for (const pak of ['chrome_100_percent.pak', 'chrome_200_percent.pak', 'LICENSES.chromium.html']) {
    const from = path.join(electronDist, pak)
    if (existsSync(from)) cpSync(from, path.join(appDir, pak))
  }
  // The Chromium sandbox helper must be setuid-root for the sandbox to work.
  // This is what makes "no --no-sandbox" (FR-072) viable on a real machine.
  try { chmodSync(path.join(appDir, 'chrome-sandbox'), 0o4755) } catch { /* fakeroot build */ }

  // Electron resolves the app from this package.json's `main`.
  writeFileSync(path.join(appDir, 'package.json'), JSON.stringify({
    name: 'ordessa',
    productName: id.productName,
    version: id.version,
    description: id.description,
    author: id.author,
    homepage: id.homepage,
    license: id.license,
    main: path.join('dist', 'electron-main.cjs'),
    private: true,
  }, null, 2) + '\n')

  // The version/build identity the host reads at runtime. PC-05 compares this
  // against package.json, the about panel and the update manifest.
  writeFileSync(path.join(appDir, 'build-info.json'), JSON.stringify({
    version: id.version,
    build: id.build,
    productName: id.productName,
    channel: 'stable',
  }, null, 2) + '\n')

  return { appDir }
}

// -- 5. binaries, launcher, desktop entry, icons ----------------------------

function stageBin(id, bridge) {
  const binDir = path.join(STAGE, layout.bin.replace(/^\//, ''))
  mkdirSync(binDir, { recursive: true })
  cpSync(bridge, path.join(binDir, 'acp'))
  chmodSync(path.join(binDir, 'acp'), 0o755)

  const launcher = readFileSync(path.join(repoRoot, 'packaging/debian/ordessa.in'), 'utf8')
  writeFileSync(path.join(binDir, 'ordessa'), launcher)
  chmodSync(path.join(binDir, 'ordessa'), 0o755)

  // A stable entry on PATH.
  const usrBin = path.join(STAGE, 'usr/bin')
  mkdirSync(usrBin, { recursive: true })
  try { symlinkSync('/opt/ordessa/bin/ordessa', path.join(usrBin, 'ordessa')) } catch { /* exists */ }
  return { binDir }
}

// C-09 A2 puts copyright + changelog.Debian.gz under /usr/share/doc/ordessa as
// well as in DEBIAN/. Both are required: DEBIAN/ is what dpkg reads, the doc
// directory is what a user (and `apt-get changelog`) can actually reach.
function stageDoc() {
  const dir = path.join(STAGE, layout.doc.replace(/^\//, ''))
  mkdirSync(dir, { recursive: true })
  cpSync(path.join(repoRoot, 'packaging/debian/copyright'), path.join(dir, 'copyright'))
  const changelog = path.join(dir, 'changelog.Debian')
  writeFileSync(changelog, readFileSync(path.join(repoRoot, 'packaging/debian/changelog'), 'utf8'))
  run('gzip', ['-9n', '-f', changelog])
  return { dir }
}

function stageDesktopEntry(id) {
  const file = path.join(STAGE, layout.desktop.replace(/^\//, ''))
  mkdirSync(path.dirname(file), { recursive: true })
  writeFileSync(file, [
    '[Desktop Entry]',
    'Type=Application',
    'Version=1.0',
    'Name=' + id.productName,
    'GenericName=Desktop Client',
    'Comment=' + id.description,
    // The launcher, not Electron directly: the release path must never carry
    // --no-sandbox (FR-072), and the launcher is what guarantees that.
    'Exec=/opt/ordessa/bin/ordessa %U',
    'Icon=ordessa',
    'Terminal=false',
    'Categories=Utility;Development;',
    'StartupNotify=true',
    'StartupWMClass=Ordessa',
    'MimeType=x-scheme-handler/ordessa;',
    '',
  ].join('\n'))
  return { file }
}

// -- 6. ACP bridge -----------------------------------------------------------

function buildBridge() {
  const out = path.join(CACHE, 'acp-adapter')
  const script = path.join(repoRoot, 'plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh')
  if (!existsSync(script)) throw new Error('bridge build script missing: ' + script)
  if (!existsSync(out) || flag('rebuild-bridge')) {
    log('building the ACP bridge (reproducible, Go 1.24.13)…')
    run('bash', [script, out], { cwd: repoRoot, env: { ...process.env } })
  }
  const sha = sha256File(out)
  return { path: out, sha256: sha, matchesBaseline: sha === BRIDGE_SHA256_EXPECTED }
}

// -- 7. licenses -------------------------------------------------------------

function stageLicenses(bundleManifest, appDir, sitePackages) {
  const dir = path.join(STAGE, layout.licenses.replace(/^\//, ''))
  mkdirSync(dir, { recursive: true })
  const result = aggregateLicenses({
    appDir,
    sitePackages,
    bundleManifest,
    productName: identity().productName,
    version: bundleManifest.version,
  })
  writeFileSync(path.join(dir, 'THIRD-PARTY-NOTICES'), result.text)
  // The product's own license text, if the repository carries one.
  for (const candidate of ['LICENSE', 'LICENSE.md', 'LICENSE.txt']) {
    const from = path.join(repoRoot, candidate)
    if (existsSync(from)) { cpSync(from, path.join(dir, 'LICENSE')); break }
  }
  return { dir, python: result.pythonCount, npm: result.npmCount }
}

// -- 8. deb assembly ---------------------------------------------------------

function installedSizeKiB(root) {
  let total = 0
  for (const entry of treeListing(root)) {
    try { total += statSync(path.join(root, entry.rel)).size } catch { /* dangling symlink */ }
  }
  return Math.max(1, Math.ceil(total / 1024))
}

function buildDeb(id) {
  const debRoot = path.join(CACHE, 'debroot')
  rmSync(debRoot, { recursive: true, force: true })
  // The staged tree IS the package payload: /opt/ordessa, /usr/share/... .
  // It must be copied in before dpkg-deb runs, or the result is a valid-looking
  // 4 KB package that installs nothing.
  cpSync(STAGE, debRoot, { recursive: true, dereference: false })
  // cpSync drops the setuid bit (it creates files with the source's permission
  // bits minus set-user-ID), so the sandbox helper's mode is re-applied AFTER
  // the copy into the deb root. Without this the package ships chrome-sandbox
  // as 0755 and a release that is forbidden from passing --no-sandbox (FR-072)
  // would have no working sandbox at all.
  const sandboxHelper = path.join(debRoot, 'opt/ordessa/app/chrome-sandbox')
  if (existsSync(sandboxHelper)) chmodSync(sandboxHelper, 0o4755)
  mkdirSync(path.join(debRoot, 'DEBIAN'), { recursive: true })

  writeFileSync(path.join(debRoot, 'DEBIAN/control'), renderControl(id))
  for (const script of ['postinst', 'prerm', 'postrm']) {
    const dest = path.join(debRoot, 'DEBIAN', script)
    writeFileSync(dest, readFileSync(path.join(repoRoot, 'packaging/debian', script), 'utf8'))
    chmodSync(dest, 0o755)
  }
  writeFileSync(path.join(debRoot, 'DEBIAN/copyright'),
    readFileSync(path.join(repoRoot, 'packaging/debian/copyright'), 'utf8'))

  // changelog.Debian.gz is required by the layout.
  const changelog = readFileSync(path.join(repoRoot, 'packaging/debian/changelog'), 'utf8')
  writeFileSync(path.join(debRoot, 'DEBIAN/changelog'), changelog)
  run('gzip', ['-9n', '-f', path.join(debRoot, 'DEBIAN/changelog')])

  mkdirSync(OUT, { recursive: true })
  const debPath = path.join(OUT, id.pkgName + '_' + id.version + '_amd64.deb')
  rmSync(debPath, { force: true })
  log('building ' + path.basename(debPath) + '…')
  // fakeroot gives dpkg-deb the ownership it wants without root.
  run('fakeroot', ['--', 'dpkg-deb', '--root-owner-group', '-Zxz', '--build', debRoot, debPath])
  return debPath
}

function renderControl(id) {
  // The template carries `#` documentation lines for the maintainer. Debian
  // control files are strict and reject a leading comment block, so the
  // commentary lives in the source and is dropped here rather than being
  // duplicated (and drifting) in a separate cleaned-up copy.
  const template = readFileSync(path.join(repoRoot, 'packaging/debian/control.in'), 'utf8')
  return template
    .split('\n')
    .filter(line => !line.startsWith('#'))
    .join('\n')
    .replace(/@PKG@/g, id.pkgName)
    .replace(/@VERSION@/g, id.version)
    .replace(/@AUTHOR@/g, id.author)
    .replace(/@HOMEPAGE@/g, id.homepage)
    .replace(/@DESCRIPTION@/g, id.description)
    .replace(/@INSTALLED_SIZE@/g, String(installedSizeKiB(STAGE)))
    // dpkg-deb on some toolchains (observed on dpkg 1.23.7) rejects a
    // Depends/Recommends value that starts on a continuation line, even though
    // it is standard Debian format. Folding those lists onto one logical line
    // is equally valid and keeps the package buildable everywhere. The
    // template stays one-entry-per-line so it remains readable and diffable.
    .replace(/^(Depends|Recommends):\n((?: [^\n]*\n?)+)/gm, (_, field, body) => {
      // Template entries already carry a trailing comma; strip it before
      // rejoining so the folded list does not come out as "a,, b".
      const items = body.split('\n')
        .map(s => s.trim().replace(/,$/, ''))
        .filter(Boolean)
        .join(', ')
      return field + ': ' + items + '\n'
    })
}
// -- 9. hashes ---------------------------------------------------------------

function writeHashes(debPath, id) {
  const entries = []
  entries.push({ rel: path.basename(debPath), sha256: sha256File(debPath) })

  const manifestPath = path.join(repoRoot, 'packaging/bundle-manifest.json')
  if (existsSync(manifestPath)) {
    entries.push({ rel: 'bundle-manifest.json', sha256: sha256File(manifestPath) })
  }

  const appDir = path.join(STAGE, layout.app.replace(/^\//, ''))
  const appHash = treeHash(appDir)
  if (appHash) entries.push({ rel: 'app-tree', sha256: appHash })
  if (appHash) writeFileSync(path.join(OUT, 'app-tree.sha256'), appHash + '  app/\n')

  const sums = entries.map(e => e.sha256 + '  ' + e.rel + '\n').join('')
  writeFileSync(path.join(OUT, 'SHA256SUMS'), sums)
  return { entries, appHash }
}

// -- main --------------------------------------------------------------------

async function main() {
  const id = identity()
  log('identity:', id.version, id.build)
  if (id.metaStubs.length) {
    log('CONTROLLED STUB — product metadata not yet delivered by P-A, using: ' + id.metaStubs.join(', '))
  }

  rmSync(STAGE, { recursive: true, force: true })
  mkdirSync(STAGE, { recursive: true })

  // Every step returns a promise, so every step must be awaited: a
  // non-awaited one yields a Promise, and `bridge.path` on a Promise is
  // silently `undefined` rather than an error.
  const python = await step('python-runtime', stagePython)()
  const serverDeps = await step('server-deps', () => stageServerDeps(python))()
  const productPkgs = await step('product-packages', () => stageProductPackages(python))()
  const app = await step('app', () => stageApp(id))()
  const bridge = await step('acp-bridge', buildBridge)()
  await step('bin', () => stageBin(id, bridge.path))()
  await step('desktop-entry', () => stageDesktopEntry(id))()
  await step('doc', () => stageDoc())()
  const iconReport = await step('icons', () => exportIcons({ outRoot: STAGE }))()
  if (iconReport.placeholder) log('CONTROLLED STUB — icon design not yet delivered, using the built-in placeholder')

  // The update public key ships with the package so an installed copy can
  // verify the next manifest. A build without a key cannot be updated later,
  // so the absence is a hard error rather than a warning.
  const pubkey = process.env.ORDESSA_UPDATE_PUBKEY
  if (!pubkey || !existsSync(pubkey)) {
    throw new Error('ORDESSA_UPDATE_PUBKEY must point at the Ed25519 public key PEM to embed. ' +
      'Generate a test pair with: node packaging/update/keygen.mjs <dir>')
  }
  cpSync(pubkey, path.join(STAGE, layout.pubkey.replace(/^\//, '')))

  const components = [
    { kind: 'desktop', source: 'apps/desktop/dist + products/desktop/dist', version: id.version, sha256: treeHash(app.appDir), dest: layout.app },
    { kind: 'python-runtime', source: PYTHON_URL, version: PYTHON_VERSION, sha256: sha256Bytes(python.sha256), dest: layout.python },
    { kind: 'server-deps', source: 'apps/server/lockfiles/server-linux-py312.txt', version: 'pinned', sha256: serverDeps.lockSha256, dest: layout.sitePackages },
    { kind: 'acp-bridge', source: 'plugins/harness/packaging/acp-adapter (built)', version: 'round-h', sha256: bridge.sha256, dest: layout.acp },
    { kind: 'licenses', source: 'build-time aggregation', version: id.version, sha256: null, dest: layout.licenses },
  ]

  const bundleManifest = {
    schemaVersion: 1,
    version: id.version,
    build: id.build,
    productName: id.productName,
    createdAt: new Date().toISOString(),
    components,
  }
  // Licenses are hashed after they are written, so the manifest is completed
  // in two passes rather than leaving a null that could hide a real omission.
  const lic = stageLicenses(bundleManifest, app.appDir, serverDeps.dest)
  components.find(c => c.kind === 'licenses').sha256 = sha256File(path.join(lic.dir, 'THIRD-PARTY-NOTICES'))
  components.find(c => c.kind === 'licenses').counts = { python: lic.python, npm: lic.npm }
  writeFileSync(path.join(repoRoot, 'packaging/bundle-manifest.json'), JSON.stringify(bundleManifest, null, 2) + '\n')
  cpSync(path.join(repoRoot, 'packaging/bundle-manifest.json'), path.join(app.appDir, 'bundle-manifest.json'))

  const debPath = buildDeb(id)
  const hashes = writeHashes(debPath, id)

  const result = {
    version: id.version,
    build: id.build,
    deb: debPath,
    debSha256: sha256File(debPath),
    debSize: statSync(debPath).size,
    appTreeSha256: hashes.appHash,
    sha256sums: path.join(OUT, 'SHA256SUMS'),
    bridgeSha256: bridge.sha256,
    bridgeMatchesBaseline: bridge.matchesBaseline,
    iconPlaceholder: iconReport.placeholder,
    metadataStubs: id.metaStubs,
    pythonSha256: python.sha256,
    pipSkipped: Boolean(flag('skip-pip')),
    steps,
  }
  writeFileSync(path.join(OUT, 'build-result.json'), JSON.stringify(result, null, 2) + '\n')
  log('done:', debPath)
  if (!bridge.matchesBaseline) {
    log('NOTE: bridge sha256 ' + bridge.sha256 + ' != baseline ' + BRIDGE_SHA256_EXPECTED)
  }
  return result
}

if (import.meta.url === 'file://' + process.argv[1]) {
  main().catch(err => {
    console.error('[build-deb] FAILED:', err.message)
    process.exit(1)
  })
}

export { main, STAGE, OUT }
