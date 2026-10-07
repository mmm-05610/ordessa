// Cross-language guard: the TypeScript mirror of the sandbox refusal vocabulary
// must equal the Python authority in `ordessa_sandbox_api/errors.py`, and the
// describe wire parameter names must equal `ordessa_sandbox_backend/plugin.py`.
// A drift here means the Settings region would report a code the backend never
// emits (or swallow one it does), so this compares the real source text.
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import {
  SANDBOX_DESCRIBE_METHOD,
  SANDBOX_DESCRIBE_OPTIONAL_PARAMS,
  SANDBOX_DESCRIBE_REQUIRED_PARAMS,
  SANDBOX_STABLE_ERROR_CODES,
} from '../src/contract'

const errorsPy = readFileSync(
  fileURLToPath(new URL('../../api/src/ordessa_sandbox_api/errors.py', import.meta.url)), 'utf8')
const pluginPy = readFileSync(
  fileURLToPath(new URL('../../backend/src/ordessa_sandbox_backend/plugin.py', import.meta.url)), 'utf8')

/** Every `NAME = "VALUE"` member of a Python enum/class body in the source text. */
function pythonEnumMembers(source: string, className: string): string[] {
  const body = new RegExp(`class ${className}\\(.*?\\n(?=\\S)`, 's').exec(source)?.[0]
  if (body === undefined) throw new Error(`Python enum ${className} not found — the source moved`)
  return [...body.matchAll(/^\s{4}([A-Z0-9_]+)\s*=\s*"([^"]+)"/gm)].map(m => m[2])
}

function pythonFrozensetLiterals(source: string, constant: string): string[] {
  const decl = new RegExp(`${constant}\\s*=\\s*frozenset\\(\\{(.*?)\\}\\)`, 's').exec(source)
  if (decl === null) throw new Error(`Python constant ${constant} not found — the wire shape moved`)
  return [...decl[1].matchAll(/"([^"]+)"/g)].map(m => m[1])
}

describe('sandbox describe contract mirrors the Python authority (FR-09)', () => {
  it('the TS stable-code list equals the Python SandboxErrorCode members exactly', () => {
    const python = pythonEnumMembers(errorsPy, 'SandboxErrorCode')
    // errors.py documents six stable codes plus SANDBOX_INTENT_INVALID, which
    // the API keeps deliberately outside the stable set ("a typo never reads as
    // a platform or coverage verdict"). The region mirrors the stable six.
    const stable = python.filter(code => code !== 'SANDBOX_INTENT_INVALID')
    expect(SANDBOX_STABLE_ERROR_CODES).toHaveLength(6)
    expect([...SANDBOX_STABLE_ERROR_CODES].sort()).toEqual(stable.sort())
    expect(python).toContain('SANDBOX_INTENT_INVALID')
    // and the TS list carries no member the Python enum lacks (exact, both ways)
    expect(SANDBOX_STABLE_ERROR_CODES.filter(c => !python.includes(c))).toEqual([])
  })

  it('the describe method and parameter names equal the backend handler shape', () => {
    expect(SANDBOX_DESCRIBE_METHOD).toBe('sandbox.describe')
    expect([...SANDBOX_DESCRIBE_REQUIRED_PARAMS].sort())
      .toEqual(pythonFrozensetLiterals(pluginPy, '_DESCRIBE_REQUIRED').sort())
    expect([...SANDBOX_DESCRIBE_OPTIONAL_PARAMS].sort())
      .toEqual(pythonFrozensetLiterals(pluginPy, '_DESCRIBE_OPTIONAL').sort())
  })
})
