import { createHash } from 'node:crypto'
import { readFile, realpath, stat } from 'node:fs/promises'
import path from 'node:path'

type SourceFile = { relative: string; sha256: string }
type Admission = { entry: string; files: readonly SourceFile[] }

// This is the closed, Root-reviewed test-source set. A new driver or any changed
// byte requires an explicit review of this admission record and its tests.
export const SMOKE_DRIVER_ADMISSIONS: Readonly<Record<string, Admission>> = Object.freeze({
  smoke: Object.freeze({
    entry: 'tests/fixtures/smoke-driver.mjs',
    files: Object.freeze([
      Object.freeze({ relative: 'tests/fixtures/smoke-driver.mjs', sha256: '2ec60fa716c2af183a353d4e8549639f4141542f22e99750b07fc7124daa85c2' }),
      Object.freeze({ relative: 'tests/fixtures/smoke-agent.mjs', sha256: '0d57a8b0973af77d1df89906654a4bf3729230b28d4a0e830429725e61ec570b' }),
      Object.freeze({ relative: 'tests/fixtures/smoke-ui.mjs', sha256: 'e1aedd7cc63f77e73266927cb6b89129f587e3186c7ea25c234d8d1ff4e3503a' }),
    ]),
  }),
  'probe-startup-ui': Object.freeze({
    entry: 'tests/fixtures/probe-startup-ui-driver.mjs',
    files: Object.freeze([
      Object.freeze({ relative: 'tests/fixtures/probe-startup-ui-driver.mjs', sha256: '55b4072b59df1705d3bea6a79b63597b804d97480ff6d92ac83477d190246629' }),
    ]),
  }),
})

function refused(code: string): Error { return Object.assign(new Error(code), { code }) }

/** Resolve only a named, digest-pinned fixture rooted in the Electron app tree. */
export async function resolveSmokeDriver(id: unknown, appRoot: string): Promise<string> {
  if (typeof id !== 'string' || !Object.hasOwn(SMOKE_DRIVER_ADMISSIONS, id)) throw refused('SMOKE_DRIVER_NOT_ADMITTED')
  const admission = SMOKE_DRIVER_ADMISSIONS[id]
  const root = await realpath(appRoot)
  for (const source of admission.files) {
    const expected = path.resolve(root, source.relative)
    const actual = await realpath(expected).catch(() => { throw refused('SMOKE_DRIVER_SOURCE_MISSING') })
    const relative = path.relative(root, actual)
    if (actual !== expected || !relative || relative === '..' || relative.startsWith('..' + path.sep) || path.isAbsolute(relative)) {
      throw refused('SMOKE_DRIVER_PATH_ESCAPE')
    }
    if (!(await stat(actual)).isFile()) throw refused('SMOKE_DRIVER_SOURCE_NOT_FILE')
    const digest = createHash('sha256').update(await readFile(actual)).digest('hex')
    if (digest !== source.sha256) throw refused('SMOKE_DRIVER_SOURCE_MISMATCH')
  }
  return path.resolve(root, admission.entry)
}
