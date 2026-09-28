// The deb contract, asserted against the built artefact (PC-01, PC-02, PC-05,
// PC-07, PC-12, FR-070/071/072/073/078/079/080).
//
// These read the produced .deb, not the build script's intentions. A build that
// forgets to copy its staged tree still "passes" a test that inspects the
// script; only reading the artefact catches that, which is exactly the class of
// bug this suite exists for.
// Extraction happens under the repository's own filesystem, not os.tmpdir():
// the package expands to ~700 MB and /tmp is typically a small tmpfs, so
// unpacking there fails with a quota error on ordinary build machines.
const EXTRACT_ROOT = path.join(repoRoot, 'packaging/.test-extract')
// Run: node tests/integration/packaging/deb-contract.test.mjs
// Requires: packaging/.out/ordessa_<version>_amd64.deb (see `npm run build:deb`)

import { test, describe, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'

import { readFileSync, existsSync, mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'
import { repoRoot, identity } from '../../../packaging/lib/identity.mjs'
import { layout } from '../../../packaging/lib/layout.mjs'

const id = identity()
const OUT = path.join(repoRoot, 'packaging/.out')
const DEB = path.join(OUT, id.pkgName + '_' + id.version + '_amd64.deb')

let control = null
let listing = null
let workDir = null

function sh(cmd, args) {
  return execFileSync(cmd, args, { encoding: 'utf8', maxBuffer: 256 * 1024 * 1024 })
}

before(() => {
  if (!existsSync(DEB)) {
    throw new Error('deb not built: ' + DEB + '\nRun `npm run build:deb` first. ' +
      'These tests read the real artefact on purpose, so there is no stub fallback.')
  }
  control = sh('dpkg-deb', ['-I', DEB, 'control'])
  listing = sh('dpkg-deb', ['-c', DEB])
  rmSync(EXTRACT_ROOT, { recursive: true, force: true })
  mkdirSync(EXTRACT_ROOT, { recursive: true })
  workDir = EXTRACT_ROOT
  sh('dpkg-deb', ['-x', DEB, workDir])
})

after(() => {
  if (workDir) rmSync(workDir, { recursive: true, force: true })
})

const shipped = rel => path.join(workDir, rel.replace(/^\.\//, ''))
const hasEntry = needle => listing.split('\n').some(line => line.includes(needle))

describe('PC-01 deb control', () => {
  test('package identity matches the single source of version', () => {
    assert.match(control, new RegExp('^Package: ' + id.pkgName + '$', 'm'))
    assert.match(control, new RegExp('^Version: ' + id.version.replace(/\./g, '\\.') + '$', 'm'))
    assert.match(control, /^Architecture: amd64$/m)
    assert.match(control, /^Section: utils$/m)
    assert.match(control, /^Priority: optional$/m)
  })

  test('Maintainer/Homepage/License come from the product metadata', () => {
    assert.match(control, new RegExp('^Maintainer: ' + id.author.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$', 'm'))
    assert.match(control, new RegExp('^Homepage: ' + id.homepage.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '$', 'm'))
  })

  // The headline "clean machine" rule.
  test('Depends contains no toolchain package (nodejs / golang / python3)', () => {
    const depends = (control.match(/^Depends:(.*)$/m) || [, ''])[1]
    for (const forbidden of ['nodejs', 'golang', 'python3', 'npm', 'gcc', 'build-essential']) {
      assert.ok(!new RegExp('(^|[\\s,])' + forbidden + '([\\s,]|$)').test(depends),
        'Depends must not require ' + forbidden + ' (a clean machine must not need a toolchain)')
    }
  })

  test('Depends names only shared libraries, not whole toolchains', () => {
    const depends = (control.match(/^Depends:(.*)$/m) || [, ''])[1]
    for (const entry of depends.split(',')) {
      const name = entry.trim().split('|')[0].trim()
      if (!name) continue
      assert.ok(/^(lib|policykit|polkitd|xdg-utils|fonts)/.test(name),
        'unexpected non-library dependency: ' + name)
    }
  })

  test('maintainer scripts and copyright are present', () => {
    // The scripts live in control.tar, not in the payload listing, so they
    // must be read from the control tarball rather than from `dpkg-deb -c`.
    const ctrl = sh('bash', ['-c',
      'dpkg-deb --ctrl-tarfile ' + JSON.stringify(DEB) + ' | tar t'])
    for (const entry of ['postinst', 'prerm', 'postrm', 'copyright', 'changelog.gz']) {
      assert.ok(ctrl.includes(entry), 'missing DEBIAN/' + entry)
    }
  })
})

describe('PC-02 install layout', () => {
  test('the payload is actually in the package (not an empty shell)', () => {
    // Regression guard: a build that skips copying the staged tree still emits a
    // valid 4 KB .deb. Asserting real content is what catches that.
    const fileCount = listing.trim().split('\n').filter(Boolean).length
    assert.ok(fileCount > 1000, 'package contains only ' + fileCount + ' entries; the staged tree was not packaged')
  })

  test('/opt/ordessa has the full C-09 A2 layout', () => {
    for (const rel of ['python/bin/python3.12', 'bin/ordessa', 'bin/acp', 'app/electron',
      'app/build-info.json', 'app/update-pubkey', 'licenses/THIRD-PARTY-NOTICES']) {
      assert.ok(existsSync(shipped('opt/ordessa/' + rel)), 'missing /opt/ordessa/' + rel)
    }
  })

  test('desktop entry and hicolor icons are installed', () => {
    assert.ok(existsSync(shipped('usr/share/applications/ordessa.desktop')))
    for (const size of [16, 32, 48, 64, 128, 256]) {
      const p = shipped('usr/share/icons/hicolor/' + size + 'x' + size + '/apps/ordessa.png')
      assert.ok(existsSync(p), 'missing hicolor icon at ' + size)
      const head = readFileSync(p).subarray(0, 8)
      assert.deepEqual([...head], [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a], 'not a PNG: ' + size)
    }
  })

  test('/usr/share/doc/ordessa carries copyright and changelog', () => {
    assert.ok(existsSync(shipped('usr/share/doc/ordessa/copyright')))
    assert.ok(existsSync(shipped('usr/share/doc/ordessa/changelog.Debian.gz')))
  })

  test('the desktop entry launches the launcher, not electron directly', () => {
    const desktop = readFileSync(shipped('usr/share/applications/ordessa.desktop'), 'utf8')
    assert.match(desktop, /^Exec=\/opt\/ordessa\/bin\/ordessa/m)
  })
})

describe('PC-03/PC-04 release command', () => {
  test('the launcher command does not disable the sandbox (FR-072)', () => {
    const launcher = readFileSync(shipped('opt/ordessa/bin/ordessa'), 'utf8')
    // Strip comments first: the file *documents* that --no-sandbox is banned,
    // so a naive substring search would flag its own warning.
    const code = launcher.split('\n').filter(l => !l.trimStart().startsWith('#')).join('\n')
    assert.ok(!code.includes('--no-sandbox'),
      'the release launch path must never pass --no-sandbox (FR-072)')
    assert.match(code, /exec "\$ORDESSA_APP\/electron"/)
  })

  test('the launcher exports the runtime root P-B resolves (C-02 §6)', () => {
    const launcher = readFileSync(shipped('opt/ordessa/bin/ordessa'), 'utf8')
    assert.match(launcher, /ORDESSA_BUNDLED_ROOT="\$ORDESSA_PREFIX"/)
    assert.match(launcher, /ORDESSA_DATA_ROOT/)
  })

  test('the bundled Python is the pinned 3.12 runtime and imports the Server', () => {
    const res = sh(path.join(workDir, 'opt/ordessa/python/bin/python3.12'), ['-c',
      'import sys; print(sys.version_info[:2])'])
    assert.match(res.trim(), /\(3, 12\)/)
    const dep = sh(path.join(workDir, 'opt/ordessa/python/bin/python3.12'), ['-c', 'import fastapi'])
    assert.equal(dep, '')
  })

  test('the ACP bridge is present and executable', () => {
    const st = readFileSync(shipped('opt/ordessa/bin/acp')).subarray(0, 4)
    assert.equal(st.toString('hex'), '7f454c46', 'acp is not an ELF binary')
  })
})

describe('PC-05 version consistency', () => {
  test('package.json, build-info.json and the bundle manifest agree', () => {
    const pkg = JSON.parse(readFileSync(shipped('opt/ordessa/app/package.json'), 'utf8'))
    const build = JSON.parse(readFileSync(shipped('opt/ordessa/app/build-info.json'), 'utf8'))
    const bundle = JSON.parse(readFileSync(shipped('opt/ordessa/app/bundle-manifest.json'), 'utf8'))
    const source = JSON.parse(readFileSync(path.join(repoRoot, 'apps/desktop/package.json'), 'utf8'))

    assert.equal(pkg.version, id.version)
    assert.equal(build.version, id.version)
    assert.equal(bundle.version, id.version)
    assert.equal(source.version, id.version, 'the single source of version is apps/desktop/package.json')
    assert.equal(build.build, bundle.build, 'build number must match between build-info and the bundle manifest')
  })
})

describe('PC-06/PC-07 licences and hashes', () => {
  test('THIRD-PARTY-NOTICES lists real components', () => {
    const notices = readFileSync(shipped('opt/ordessa/licenses/THIRD-PARTY-NOTICES'), 'utf8')
    assert.match(notices, /THIRD-PARTY-NOTICES/)
    // Real content, not an empty template: the Server closure must show up.
    assert.match(notices, /fastapi/i)
    assert.ok(!/Total third-party components: 0\b/.test(notices), 'no third-party components were recorded')
  })

  test('SHA256SUMS covers the deb, the bundle manifest and the app tree', () => {
    const sums = readFileSync(path.join(OUT, 'SHA256SUMS'), 'utf8')
    assert.match(sums, new RegExp('ordessa_' + id.version.replace(/\./g, '\\.') + '_amd64\\.deb'))
    assert.match(sums, /bundle-manifest\.json/)
    assert.match(sums, /app-tree/)
  })
})

describe('PC-12 uninstall semantics (FR-080)', () => {
  test('postrm preserves the data root on remove and on purge', () => {
    const postrm = readFileSync(path.join(repoRoot, 'packaging/debian/postrm'), 'utf8')
    // Assert the actual rule, not just the word "purge": no branch may remove a
    // data root. A future edit that adds `rm -rf .../.ordessa` must fail here.
    const destructive = /rm\s+(-[a-zA-Z]*\s+)*[^#\n]*\.ordessa/.exec(postrm.replace(/#[^\n]*/g, ''))
    assert.equal(destructive, null, 'postrm must never delete a data root: ' + (destructive && destructive[0]))
    assert.match(postrm.replace(/#[^\n]*/g, ''), /PRESERVE_DATA_ROOT=1/)
    assert.match(postrm, /remove\|purge/)
  })

  test('postinst does not create a data root on the user\'s behalf', () => {
    const postinst = readFileSync(path.join(repoRoot, 'packaging/debian/postinst'), 'utf8')
    const creates = /mkdir[^#\n]*\.ordessa/.exec(postinst.replace(/#[^\n]*/g, ''))
    assert.equal(creates, null, 'postinst must not create ~/.ordessa: ' + (creates && creates[0]))
  })
})
