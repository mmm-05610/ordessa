/**
 * C-01 on the host side: the resolution order, the symlink refusal, and the
 * guarantee that the two entry points read ONE set of literals.
 *
 * The cross-language half of this file runs the Python resolver as a
 * subprocess and compares its answer to this module's, for the same
 * environment. That is the only honest way to test "the Server CLI and the
 * Desktop host agree" — a test that re-implements the Python rule in
 * TypeScript would agree with a bug in the test.
 */
import { execFileSync } from 'node:child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  DATA_ROOT_ENV,
  DataRootError,
  INSTANCE_LOCK,
  LOGS_DIR,
  SECRETS_DIR,
  TOKEN_FILE,
  assertNoSymlink,
  layout,
  launchEnv,
  resolveDataRoot,
  tokenFileOf,
} from '../src/data-root.js'

const REPO_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..')
const PYTHON = path.join(REPO_ROOT, '.venv/bin/python')

let scratch: string

beforeEach(() => {
  scratch = mkdtempSync(path.join(tmpdir(), 'sb-dataroot-'))
})

afterEach(() => {
  rmSync(scratch, { recursive: true, force: true })
})

describe('C-01 §1 — the resolution order', () => {
  it('uses the home directory when the override is absent', () => {
    const resolved = resolveDataRoot({}, scratch)
    expect(resolved).toEqual({ path: path.join(scratch, '.ordessa'), source: 'default' })
  })

  it('prefers the override over the default, for both entry points', () => {
    const override = path.join(scratch, 'chosen')
    expect(resolveDataRoot({ [DATA_ROOT_ENV]: override }, '/somewhere/else')).toEqual({
      path: override,
      source: 'env',
    })
  })

  it('refuses a relative override rather than resolving it against the cwd', () => {
    expect(() => resolveDataRoot({ [DATA_ROOT_ENV]: 'relative/root' })).toThrow(DataRootError)
  })

  it('refuses a ".." segment before normalising it away', () => {
    let thrown: DataRootError | null = null
    try {
      // String concatenation, NOT path.join: join would collapse the '..'
      // before the resolver ever saw it, and the test would prove nothing.
      resolveDataRoot({ [DATA_ROOT_ENV]: `${scratch}/../escape` })
    } catch (error) {
      thrown = error as DataRootError
    }
    expect(thrown?.code).toBe('DATA_ROOT_INVALID')
    // The refusal must not have quietly produced the collapsed path.
    expect(thrown?.message).not.toContain('escape')
  })
})

describe('C-01 §3 — the symlink question is asked before anything is read', () => {
  it('refuses a data root that is a symbolic link', () => {
    const target = path.join(scratch, 'real-root')
    const link = path.join(scratch, 'linked-root')
    mkdirSync(target)
    symlinkSync(target, link)
    let thrown: DataRootError | null = null
    try {
      assertNoSymlink(link)
    } catch (error) {
      thrown = error as DataRootError
    }
    expect(thrown?.code).toBe('DATA_ROOT_SYMLINK')
  })

  it('refuses a symlinked secrets/ even when the root itself is real', () => {
    const root = path.join(scratch, 'root')
    const elsewhere = path.join(scratch, 'elsewhere')
    mkdirSync(root)
    mkdirSync(elsewhere)
    symlinkSync(elsewhere, path.join(root, SECRETS_DIR))
    expect(() => assertNoSymlink(root)).toThrow(/DATA_ROOT_SYMLINK/)
  })

  it('accepts a real root, including one that does not exist yet', () => {
    const root = path.join(scratch, 'not-created-yet')
    expect(() => assertNoSymlink(root)).not.toThrow()
  })
})

describe('C-01 §5 — one set of literals, read by both entry points', () => {
  it('reads the layout the Server package ships, and never restates it', () => {
    const source = readFileSync(
      path.join(REPO_ROOT, 'apps/server/src/ordessa_server/bootstrap/data_root_layout.json'),
      'utf8',
    )
    const shared = JSON.parse(source) as { layout: Record<string, string> }
    expect(layout().layout.tokenFile).toBe(shared['layout']?.['tokenFile'])
    expect(layout().layout.logsDir).toBe(shared['layout']?.['logsDir'])
    expect(layout().layout.backupsDir).toBe(shared['layout']?.['backupsDir'])
    expect(layout().layout.instanceLock).toBe(shared['layout']?.['instanceLock'])
    expect(layout().layout.secretsDir).toBe(SECRETS_DIR)
    expect(layout().layout.instanceLock).toBe(INSTANCE_LOCK)
  })

  it('resolves the SAME default root as the Python resolver, given the same env', () => {
    const home = path.join(scratch, 'home')
    mkdirSync(home, { recursive: true })
    const python = execFileSync(
      PYTHON,
      [
        '-c',
        'import json,sys;from ordessa_server.bootstrap.data_root import resolve_data_root;' +
          'print(json.dumps({"path": str(resolve_data_root(env={}, home=sys.argv[1]).path),' +
          '"source": resolve_data_root(env={}, home=sys.argv[1]).source}))',
        home,
      ],
      { cwd: REPO_ROOT, encoding: 'utf8' },
    )
    const fromPython = JSON.parse(python.trim()) as { path: string; source: string }
    const fromTypeScript = resolveDataRoot({}, home)
    expect(fromTypeScript.path).toBe(fromPython.path)
    expect(fromTypeScript.source).toBe(fromPython.source)
  })

  it('honours the same override on both sides', () => {
    const override = path.join(scratch, 'shared-root')
    const python = execFileSync(
      PYTHON,
      [
        '-c',
        'import json,sys;from ordessa_server.bootstrap.data_root import resolve_data_root;' +
          'print(json.dumps({"path": str(resolve_data_root(env={sys.argv[1]: sys.argv[2]}).path),' +
          '"source": resolve_data_root(env={sys.argv[1]: sys.argv[2]}).source}))',
        DATA_ROOT_ENV,
        override,
      ],
      { cwd: REPO_ROOT, encoding: 'utf8' },
    )
    expect(JSON.parse(python.trim())).toEqual({ path: override, source: 'env' })
    expect(resolveDataRoot({ [DATA_ROOT_ENV]: override })).toEqual({
      path: override,
      source: 'env',
    })
  })

  it('agrees on the token locator, built from the shared layout', () => {
    const root = path.join(scratch, 'root')
    mkdirSync(path.join(root, SECRETS_DIR), { recursive: true })
    const locator = tokenFileOf(root)
    const python = execFileSync(
      PYTHON,
      [
        '-c',
        'import sys;from pathlib import Path;from ordessa_server.bootstrap.data_root import token_file;' +
          'print(token_file(Path(sys.argv[1])))',
        root,
      ],
      { cwd: REPO_ROOT, encoding: 'utf8' },
    )
    expect(locator).toBe(python.trim())
    expect(locator.endsWith(TOKEN_FILE)).toBe(true)
  })
})

describe('C-02 §2 — the launch environment', () => {
  it('passes an absolute data root, an origin and a token LOCATOR', () => {
    const root = path.join(scratch, 'root')
    mkdirSync(path.join(root, SECRETS_DIR), { recursive: true })
    const env = launchEnv(root, 'http://127.0.0.1:41207')
    expect(env[DATA_ROOT_ENV]).toBe(root)
    expect(env['ORDESSA_SERVER_ORIGIN']).toBe('http://127.0.0.1:41207')
    expect(env['ORDESSA_SERVER_TOKEN_FILE']).toBe(path.join(root, SECRETS_DIR, 'http-token'))
    // The locator is a path, not a token: nothing here reads the file.
    expect(Object.values(env).some((value) => value.includes('\n'))).toBe(false)
  })

  it('keeps the logs directory inside the same root the Server will use', () => {
    const root = path.join(scratch, 'root')
    mkdirSync(path.join(root, LOGS_DIR), { recursive: true })
    writeFileSync(path.join(root, LOGS_DIR, 'server.log'), '')
    expect(path.join(root, LOGS_DIR, 'server.log')).toBe(
      path.join(root, layout().logs.serverFile.replace(/^/, `${LOGS_DIR}/`)),
    )
  })
})
