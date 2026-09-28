// Cross-language consistency: the TS code list and wire vocabulary must equal
// what the Python side actually registers (parsed from source, not re-typed).
// @vitest-environment node
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
// The T015 mirrors (describe method vocabulary) are read off the module
// namespace so an unbuilt export is a named failing test, not an import crash.
import * as mirror from '../src/contract'
import {
  CEILING_ENTRY_ACTIONS, CEILING_RECORD_FIELDS, DECIDE_PARAM_NAMES, INTENT_RECORD_FIELDS,
  INTENT_RULE_ACTIONS,
  PERMISSIONS_EXPOSURE_LEVELS, PERMISSIONS_REFUSAL_CODES, PERMISSIONS_SCOPE_ORDER,
  PERMISSIONS_WIRE_METHOD_IDS, QUERY_PARAM_NAMES, TRUSTED_CEILING_SOURCES,
  renderRefusalSentence,
} from '../src/contract'

const codesPy = readFileSync(
  fileURLToPath(new URL('../../api/src/ordessa_permissions_api/codes.py', import.meta.url)), 'utf8')
const pluginPy = readFileSync(
  fileURLToPath(new URL('../../backend/src/ordessa_permissions_backend/plugin.py', import.meta.url)), 'utf8')
const ceilingsPy = readFileSync(
  fileURLToPath(new URL('../../api/src/ordessa_permissions_api/ceilings.py', import.meta.url)), 'utf8')
const intentsPy = readFileSync(
  fileURLToPath(new URL('../../api/src/ordessa_permissions_api/intents.py', import.meta.url)), 'utf8')
const rulesPy = readFileSync(
  fileURLToPath(new URL('../../api/src/ordessa_permissions_api/rules.py', import.meta.url)), 'utf8')

/** The describe handler's source, lazily: until the backend lands
 * `permissions.policy.describe`, reading it MUST throw — these equality
 * tests are red-first evidence, never stubs. */
function describePy(): string {
  const path = fileURLToPath(new URL('../../backend/src/ordessa_permissions_backend/describe.py', import.meta.url))
  if (!existsSync(path)) throw new Error('backend describe.py is absent — the mirror cannot be proven yet (red-first)')
  return readFileSync(path, 'utf8')
}

/** The members of `class RefusalCode(str, Enum)` in codes.py: NAME = "NAME". */
function pythonRefusalCodes(source: string): string[] {
  const block = /class RefusalCode\(str, Enum\):[\s\S]*?(?=\nclass |\Z)/.exec(source)
  if (!block) throw new Error('RefusalCode enum not found in codes.py — the parse must not pass vacuously')
  return [...block[0].matchAll(/^\s{4}([A-Z][A-Z0-9_]+) = "\1"$/gm)].map(m => m[1])
}

function pythonParamSet(source: string, constant: string): string[] {
  const block = new RegExp(`${constant} = frozenset\\(\\s*\\{([\\s\\S]*?)\\}\\s*\\)`).exec(source)
  if (!block) throw new Error(`${constant} not found in plugin.py`)
  return [...block[1].matchAll(/"([A-Za-z]+)"/g)].map(m => m[1]).sort()
}

function pythonStringConstant(source: string, constant: string): string {
  const hit = new RegExp(`${constant} = "([^"]+)"`).exec(source)
  if (!hit) throw new Error(`${constant} not found in plugin.py`)
  return hit[1]
}

/** The `"value"` side of every `NAME = "value"` member of a `class X(str, Enum)`. */
function pythonEnumValues(source: string, className: string): string[] {
  const block = new RegExp(`class ${className}\\(str, Enum\\):[\\s\\S]*?(?=\\nclass |\\Z)`).exec(source)
  if (!block) throw new Error(`${className} enum not found — the parse must not pass vacuously`)
  const values = [...block[0].matchAll(/^\s{4}([A-Z_]+) = "([^"]+)"$/gm)].map(m => m[2])
  if (values.length === 0) throw new Error(`${className} parsed vacuously`)
  return values
}

/** The string members of a `constant: Final[frozenset[str]] = frozenset({...})`. */
function pythonFinalFrozensetStrings(source: string, constant: string): string[] {
  const block = new RegExp(
    `${constant}: Final\\[frozenset\\[str\\]\\] = frozenset\\(\\s*\\{([\\s\\S]*?)\\}\\s*\\)`).exec(source)
  if (!block) throw new Error(`${constant} not found — the parse must not pass vacuously`)
  return [...block[1].matchAll(/"([^"]+)"/g)].map(m => m[1])
}

describe('refusal code list mirrors the Python source (FR-09)', () => {
  it('the TS stable-code list equals the parsed RefusalCode members of codes.py', () => {
    const parsed = pythonRefusalCodes(codesPy)
    expect(parsed.length).toBeGreaterThan(0) // non-vacuous parse
    expect([...PERMISSIONS_REFUSAL_CODES].sort()).toEqual(parsed.sort())
  })

  it('every stable code renders a sentence naming the target/action and the limiting layer', () => {
    for (const code of PERMISSIONS_REFUSAL_CODES) {
      const sentence = renderRefusalSentence(code, {
        operationCategory: '写入文件', targetSummary: '<目标已脱敏>', policySource: '组织上限',
      })
      expect(sentence, code).toContain(code)
      expect(sentence).toContain('写入文件')
      expect(sentence).toContain('组织上限')
    }
  })

  it('an unknown code yields a bounded generic sentence and echoes no raw payload', () => {
    const sentence = renderRefusalSentence('NOT_A_CODE\nsecret-token', {
      operationCategory: 'x', targetSummary: 'y', policySource: 'z',
    })
    expect(sentence).not.toContain('secret-token')
    expect(sentence).not.toContain('\n')
  })
})

describe('wire vocabulary mirrors the permissions backend plugin (FR-04)', () => {
  it('method ids equal the Python plugin registrations', () => {
    expect(PERMISSIONS_WIRE_METHOD_IDS.decide).toBe(pythonStringConstant(pluginPy, 'DECIDE_METHOD'))
    expect(PERMISSIONS_WIRE_METHOD_IDS.query).toBe(pythonStringConstant(pluginPy, 'QUERY_METHOD'))
  })

  it('decide/query parameter names equal the Python required-param sets', () => {
    expect([...DECIDE_PARAM_NAMES].sort()).toEqual(pythonParamSet(pluginPy, '_DECIDE_REQUIRED'))
    expect([...QUERY_PARAM_NAMES].sort()).toEqual(pythonParamSet(pluginPy, '_QUERY_REQUIRED'))
  })
})

// The Settings region (T011) renders ceiling and intent records; every field
// name, exposure level, scope and action it can display must equal what the
// Python API actually declares — parsed from source, never re-typed.
describe('ceiling/intent record mirrors equal the Python API sources (T011)', () => {
  it('exposure levels equal the ExposureLevel members of ceilings.py, in order', () => {
    expect([...PERMISSIONS_EXPOSURE_LEVELS]).toEqual(pythonEnumValues(ceilingsPy, 'ExposureLevel'))
  })

  it('the ceiling record field set equals _RECORD_FIELDS of ceilings.py', () => {
    expect([...CEILING_RECORD_FIELDS].sort()).toEqual(pythonFinalFrozensetStrings(ceilingsPy, '_RECORD_FIELDS').sort())
  })

  it('the intent record field set equals _RECORD_FIELDS of intents.py', () => {
    expect([...INTENT_RECORD_FIELDS].sort()).toEqual(pythonFinalFrozensetStrings(intentsPy, '_RECORD_FIELDS').sort())
  })

  it('scope order mirrors rules.py Scope, and rule actions mirror RuleAction', () => {
    expect([...PERMISSIONS_SCOPE_ORDER]).toEqual(pythonEnumValues(rulesPy, 'Scope'))
    expect([...INTENT_RULE_ACTIONS]).toEqual(pythonEnumValues(rulesPy, 'RuleAction'))
  })

  it('the trusted ceiling sources equal exactly the members of _TRUSTED_SOURCES in ceilings.py', () => {
    const namesBlock = /_TRUSTED_SOURCES: Final\[frozenset\[str\]\] = frozenset\(\s*\{([\s\S]*?)\}\s*\)/.exec(ceilingsPy)
    if (!namesBlock) throw new Error('_TRUSTED_SOURCES not found in ceilings.py')
    const names = [...namesBlock[1].matchAll(/CeilingSource\.([A-Z_]+)\.value/g)].map(m => m[1])
    const enumBlock = /class CeilingSource\(str, Enum\):[\s\S]*?(?=\n[^\s]|\Z)/.exec(ceilingsPy)
    if (!enumBlock) throw new Error('CeilingSource enum not found')
    const valueOf = new Map([...enumBlock[0].matchAll(/^\s{4}([A-Z_]+) = "([^"]+)"$/gm)].map(m => [m[1], m[2]]))
    const expected = names.map(name => {
      if (!valueOf.has(name)) throw new Error(`CeilingSource.${name} missing`)
      return valueOf.get(name) as string
    })
    expect([...TRUSTED_CEILING_SOURCES].sort()).toEqual(expected.sort())
  })

  it('ceiling entry actions are exactly the two restriction spellings of ceilings.py', () => {
    expect(ceilingsPy).toContain('("deny", "require-approval")')
    expect([...CEILING_ENTRY_ACTIONS]).toEqual(['deny', 'require-approval'])
  })
})

// ---------------------------------------------------------------------------
// T015: `permissions.policy.describe` — the client mirror must equal the
// backend's own declaration, parsed from its SOURCE TEXT (plugin.py method
// registration + describe.py constants and response dict literals). While the
// backend has not landed the method these tests are red by construction; they
// must never be satisfied by stubbing the backend package.
// ---------------------------------------------------------------------------

/** `NAME = frozenset()` / `NAME = frozenset({...})` — sorted string members. */
function pythonFrozenset(source: string, constant: string): string[] {
  const block = new RegExp(`${constant}[^=\\n]*=\\s*frozenset\\(\\s*(\\{[\\s\\S]*?\\})?\\s*\\)`).exec(source)
  if (!block) throw new Error(`${constant} not found in the backend source — the parse must not pass vacuously`)
  if (!block[1]) return []
  return [...block[1].matchAll(/"([^"]+)"/g)].map(m => m[1]).sort()
}

/** Every double-quoted dict-literal key set in the source, top level of each
 * `{...}` literal (string-aware, `#`-comment aware). */
function pythonDictKeySets(source: string): string[][] {
  const sets: string[][] = []
  const clean = source.replace(/#[^\n]*/g, '')
  for (let i = 0; i < clean.length; i += 1) {
    if (clean[i] !== '{') continue
    let depth = 0, end = -1
    for (let j = i; j < clean.length; j += 1) {
      const c = clean[j]
      if (c === '"' || c === "'") { j = skipString(clean, j); continue }
      if (c === '{') depth += 1
      else if (c === '}') { depth -= 1; if (depth === 0) { end = j; break } }
    }
    if (end < 0) continue
    const keys = topLevelDictKeys(clean.slice(i + 1, end))
    if (keys) sets.push(keys.sort())
    i = end
  }
  return sets
}

function skipString(s: string, start: number): number {
  const quote = s[start]
  let j = start + 1
  while (j < s.length) {
    if (s[j] === '\\') { j += 2; continue }
    if (s[j] === quote) return j
    j += 1
  }
  return j
}

function topLevelDictKeys(body: string): string[] | null {
  const keys: string[] = []
  let depth = 0, i = 0, sawColonAtZero = false
  while (i < body.length) {
    const c = body[i]
    if (c === '"' || c === "'") {
      const end = skipString(body, i)
      const text = body.slice(i + 1, end)
      let k = end + 1
      while (k < body.length && /\s/.test(body[k])) k += 1
      if (depth === 0 && body[k] === ':' && /^[A-Za-z][A-Za-z0-9]*$/.test(text)) {
        keys.push(text); sawColonAtZero = true
      }
      i = end
    } else if (c === '{' || c === '[' || c === '(') depth += 1
    else if (c === '}' || c === ']' || c === ')') depth -= 1
    i += 1
  }
  return keys.length > 0 && sawColonAtZero ? keys : null
}

const sorted = (values: readonly string[]) => [...values].sort()

describe('permissions.policy.describe mirrors equal the backend source (T015)', () => {
  it('the TS method id equals the POLICY_DESCRIBE_METHOD the plugin registers', () => {
    const pyId = pythonStringConstant(describePy(), 'POLICY_DESCRIBE_METHOD')
    expect((mirror.PERMISSIONS_WIRE_METHOD_IDS as Record<string, string>).describe).toBe(pyId)
    // the plugin really registers it (not just a stray constant): the method id
    // flows into a ServerMethodDescriptor in plugin.py.
    const pluginSrc = pluginPy
    expect(pluginSrc).toMatch(/ServerMethodDescriptor\([\s\S]*?method_id\s*=\s*POLICY_DESCRIBE_METHOD/)
  })

  it('the required/optional param sets equal the Python frozensets exactly', () => {
    const source = describePy()
    const required = pythonFrozenset(source, 'DESCRIBE_REQUIRED_PARAMS')
    const optional = pythonFrozenset(source, 'DESCRIBE_OPTIONAL_PARAMS')
    expect(sorted(mirror.DESCRIBE_REQUIRED_PARAM_NAMES as readonly string[])).toEqual(required)
    expect(sorted(mirror.DESCRIBE_OPTIONAL_PARAM_NAMES as readonly string[])).toEqual(optional)
    // and the registration wires those same constants into the descriptor
    expect(pluginPy).toMatch(/required_params\s*=\s*DESCRIBE_REQUIRED_PARAMS/)
    expect(pluginPy).toMatch(/optional_params\s*=\s*DESCRIBE_OPTIONAL_PARAMS/)
  })

  it('every closed response key set of the TS decoder equals a dict literal of describe.py', () => {
    const literals = pythonDictKeySets(describePy())
    expect(literals.length).toBeGreaterThan(0) // non-vacuous parse
    for (const [name, mirrorKeys] of [
      ['response', mirror.DESCRIBE_RESPONSE_KEYS as readonly string[]],
      ['ceiling row', mirror.DESCRIBE_CEILING_ROW_KEYS as readonly string[]],
      ['ceiling entry', mirror.DESCRIBE_CEILING_ENTRY_KEYS as readonly string[]],
      ['intent row', mirror.DESCRIBE_INTENT_ROW_KEYS as readonly string[]],
      ['intent rule', mirror.DESCRIBE_RULE_ROW_KEYS as readonly string[]],
      ['brand mode', mirror.DESCRIBE_BRAND_MODE_KEYS as readonly string[]],
      ['needs-review row', mirror.DESCRIBE_REVIEW_ROW_KEYS as readonly string[]],
    ] as const) {
      const expected = sorted(mirrorKeys)
      expect(literals.some(set => set.join('|') === expected.join('|')),
        `describe.py must build a dict literal with exactly the ${name} keys ${expected.join(', ')}`).toBe(true)
    }
  })
})
