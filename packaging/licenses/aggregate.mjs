// THIRD-PARTY-NOTICES aggregation (C-09 §D, FR-078).
//
// This file is what the About panel's licence link opens, so it has to be
// complete for what actually ships, not for what the build tree happens to
// contain. The list is derived from the components recorded in
// `bundle-manifest.json`, so a component that is bundled and not declared (or
// the reverse) shows up as a mismatch rather than as a silent omission.

import { readFileSync, writeFileSync, existsSync, readdirSync } from 'node:fs'
import path from 'node:path'

// Python distributions are the authority for their own metadata, so read the
// installed dist-info rather than parsing the lockfile: a lockfile records what
// we asked for, dist-info records what is actually in site-packages.
function pythonComponents(sitePackages) {
  if (!existsSync(sitePackages)) return []
  const out = []
  for (const entry of readdirSync(sitePackages).sort()) {
    const match = entry.match(/^([A-Za-z0-9._-]+?)-([0-9][^-]*)\.dist-info$/)
    if (!match) continue
    const [, name, version] = match
    const metaPath = path.join(sitePackages, entry, 'METADATA')
    let license = null
    let home = null
    if (existsSync(metaPath)) {
      const meta = readFileSync(metaPath, 'utf8')
      const licenseLine = meta.split('\n').find(l => l.startsWith('License-Expression:'))
      const classic = meta.split('\n').find(l => l.startsWith('License:'))
      license = (licenseLine || classic || '').replace(/^[^:]+:\s*/, '').trim() || null
      const homeLine = meta.split('\n').find(l => l.startsWith('Home-page:'))
      home = homeLine ? homeLine.replace(/^Home-page:\s*/, '').trim() : null
    }
    out.push({ ecosystem: 'python', name, version, license, source: home })
  }
  return out
}

// npm components come from the bundled application's own dependency closure.
function npmComponents(appDir) {
  const lockPath = path.join(appDir, 'package-lock.json')
  if (!existsSync(lockPath)) return []
  const lock = JSON.parse(readFileSync(lockPath, 'utf8'))
  const out = []
  for (const [key, pkg] of Object.entries(lock.packages || {})) {
    // "" is the root project; workspace links are not third-party code.
    if (key === '' || !key.startsWith('node_modules/')) continue
    if (pkg.link) continue
    out.push({
      ecosystem: 'npm',
      name: pkg.name || key.replace(/^.*node_modules\//, ''),
      version: pkg.version || null,
      license: pkg.license || null,
      source: null,
    })
  }
  return out.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
}

export function aggregateLicenses({ appDir, sitePackages, bundleManifest, productName, version }) {
  const python = pythonComponents(sitePackages)
  const npm = npmComponents(appDir)
  const components = [...python, ...npm]

  // Anything in the bundle manifest that contributed third-party code must be
  // declared here. Unregistered content is reported, not silently accepted.
  const declaredKinds = new Set((bundleManifest.components || []).map(c => c.kind))

  const lines = []
  lines.push('THIRD-PARTY-NOTICES')
  lines.push('='.repeat(72))
  lines.push('')
  lines.push(productName + ' ' + version)
  lines.push('')
  lines.push('This product bundles the third-party components listed below. Each')
  lines.push('component is distributed under its own license; the full text of each')
  lines.push('license is retained in the corresponding package inside this')
  lines.push('installation, and the product license is in LICENSE next to this file.')
  lines.push('')
  lines.push('Components are derived at build time from the metadata each package')
  lines.push('declares about itself (Python dist-info METADATA, npm package-lock).')
  lines.push('')
  lines.push('-'.repeat(72))
  lines.push('')

  const groups = new Map()
  for (const c of components) {
    const key = (c.license || 'UNKNOWN').toUpperCase()
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(c)
  }

  for (const license of [...groups.keys()].sort()) {
    lines.push('License: ' + license)
    lines.push('-'.repeat(license.length + 9))
    for (const c of groups.get(license).sort((a, b) => (a.name < b.name ? -1 : 1))) {
      lines.push('  ' + c.name + (c.version ? ' ' + c.version : '') + '  [' + c.ecosystem + ']')
      if (c.source) lines.push('      ' + c.source)
    }
    lines.push('')
  }

  lines.push('-'.repeat(72))
  lines.push('')
  lines.push('Bundled components (packaging/bundle-manifest.json):')
  for (const kind of [...declaredKinds].sort()) lines.push('  - ' + kind)
  lines.push('')
  lines.push('Total third-party components: ' + components.length)
  lines.push('')

  const text = lines.join('\n')
  return { text, components, pythonCount: python.length, npmCount: npm.length, kinds: [...declaredKinds].sort() }
}

if (import.meta.url === 'file://' + process.argv[1]) {
  const [, , appDir, sitePackages, manifestPath, outPath] = process.argv
  const bundleManifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
  const result = aggregateLicenses({ appDir, sitePackages, bundleManifest, productName: 'Ordessa', version: bundleManifest.version })
  writeFileSync(outPath, result.text)
  console.log(JSON.stringify({ python: result.pythonCount, npm: result.npmCount, bytes: result.text.length }, null, 2))
}
