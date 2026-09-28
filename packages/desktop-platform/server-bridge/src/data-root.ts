/**
 * C-01 — the data root, resolved by the host exactly the way the Server CLI
 * resolves it.
 *
 * The literals live in ONE file, `data_root_layout.json`, which is the same
 * file `apps/server/src/ordessa_server/bootstrap/data_root.py` loads. This
 * module only reads it and applies the two-step order; it never restates a
 * path, a variable name or a permission. A cross-language test compares both
 * sides' answers for the same environment, so a divergence fails a test
 * rather than producing two data roots.
 *
 * The symlink rule is enforced with `lstatSync`, never `realpathSync`:
 * resolving first would answer the question by following the link, which is
 * the thing being refused. The order is also load-bearing — the symlink
 * check runs before the writability probe, because the probe would
 * otherwise create a file inside the link's target.
 */
import { readFileSync, lstatSync } from 'node:fs'
import path from 'node:path'

export interface DataRootLayout {
  readonly schemaVersion: number
  readonly dataRoot: { readonly envVar: string; readonly defaultDirname: string }
  readonly layout: {
    readonly secretsDir: string
    readonly tokenFile: string
    readonly logsDir: string
    readonly backupsDir: string
    readonly instanceLock: string
  }
  readonly permissions: { readonly dirMode: string; readonly secretFileMode: string }
  readonly logs: {
    readonly desktopFile: string
    readonly serverFile: string
    readonly rotateBytes: number
    readonly keep: number
  }
  readonly launch: {
    readonly originEnv: string
    readonly tokenFileEnv: string
    readonly dataRootEnv: string
    readonly bundledRootEnv: string
    readonly bundledRootDefault: string
    readonly bundledDirs: readonly string[]
    readonly acpBridgeRelative: string
    readonly livePath: string
    readonly wirePathPrefix: string
    readonly systemAssignedPort: number
    readonly defaultPort: number
    readonly readyTimeoutMs: number
    readonly handshakeEvent: string
    readonly instanceFile: string
  }
  readonly dataRootErrors: readonly string[]
  readonly launchErrors: readonly string[]
}

/** Where the shared constants file lives, relative to this module. */
const LAYOUT_SOURCE = '../../../../apps/server/src/ordessa_server/bootstrap/data_root_layout.json'

let cached: DataRootLayout | undefined

/**
 * The shared layout, read once. A missing or malformed file is a build
 * error, not a fallback: a host that invented its own defaults would be
 * the exact "two entry points, two spellings" failure C-01 §5 forbids.
 */
export function layout(): DataRootLayout {
  if (!cached) {
    const raw = readFileSync(new URL(LAYOUT_SOURCE, import.meta.url), 'utf8')
    const parsed = JSON.parse(raw) as DataRootLayout
    if (parsed.schemaVersion !== 1) {
      throw new Error(`unsupported data-root layout schema ${String(parsed.schemaVersion)}`)
    }
    cached = parsed
  }
  return cached
}

export const DATA_ROOT_ENV: string = layout().dataRoot.envVar
export const DEFAULT_DATA_ROOT_DIRNAME: string = layout().dataRoot.defaultDirname
export const SECRETS_DIR: string = layout().layout.secretsDir
export const TOKEN_FILE: string = layout().layout.tokenFile
export const LOGS_DIR: string = layout().layout.logsDir
export const BACKUPS_DIR: string = layout().layout.backupsDir
export const INSTANCE_LOCK: string = layout().layout.instanceLock
export const DIR_MODE: number = parseInt(layout().permissions.dirMode, 8)
export const SECRET_FILE_MODE: number = parseInt(layout().permissions.secretFileMode, 8)
export const SERVER_LOG_FILE: string = `${LOGS_DIR}/${layout().logs.serverFile}`
export const DESKTOP_LOG_FILE: string = `${LOGS_DIR}/${layout().logs.desktopFile}`

export type DataRootSource = 'env' | 'default'

export interface ResolvedDataRoot {
  /** Absolute, `..`-free, not yet created. */
  readonly path: string
  readonly source: DataRootSource
}

/** A data-root refusal, carrying the same five codes as the Python side. */
export class DataRootError extends Error {
  readonly code: string
  readonly reason: string
  readonly remedy: string

  constructor(code: string, reason: string, remedy: string) {
    super(`${code}: ${reason}; ${remedy}`)
    this.name = 'DataRootError'
    this.code = code
    this.reason = reason
    this.remedy = remedy
  }
}

/**
 * C-01 §1, and only that: the environment override, else the default under
 * the home directory. A relative value or one carrying `..` is refused
 * BEFORE any normalisation — collapsing `..` first would hand the caller a
 * plausible path it never asked for.
 */
export function resolveDataRoot(
  env: Readonly<Record<string, string | undefined>> = process.env,
  home?: string,
): ResolvedDataRoot {
  const override = env[DATA_ROOT_ENV]
  if (override) {
    assertUsable(override)
    return { path: override, source: 'env' }
  }
  const base = home ?? env.HOME ?? env.USERPROFILE
  if (!base) {
    throw new DataRootError(
      'DATA_ROOT_INVALID',
      'no home directory is available for the default data root',
      `set ${DATA_ROOT_ENV} to an absolute directory`,
    )
  }
  return { path: path.join(base, DEFAULT_DATA_ROOT_DIRNAME), source: 'default' }
}

function assertUsable(raw: string): void {
  if (!raw) {
    throw new DataRootError(
      'DATA_ROOT_INVALID',
      'the data root is empty',
      `set ${DATA_ROOT_ENV} to an absolute directory, or unset it to use the default`,
    )
  }
  if (!path.isAbsolute(raw)) {
    throw new DataRootError(
      'DATA_ROOT_INVALID',
      `the data root ${path.basename(raw)} is not absolute`,
      'pass an absolute path; relative data roots are never resolved against the cwd',
    )
  }
  if (raw.split(/[\\/]/).includes('..')) {
    throw new DataRootError(
      'DATA_ROOT_INVALID',
      "the data root contains a '..' segment",
      "pass a normalised absolute path; '..' is never resolved",
    )
  }
}

/**
 * C-01 §3's symlink rule, asked with no-follow semantics and asked first.
 *
 * `lstatSync` describes the directory entry itself. A `statSync` or an
 * `existsSync` would have followed the link and answered "yes, it is a
 * directory" about the TARGET — which is precisely the leak this refuses.
 */
export function assertNoSymlink(root: string): void {
  const owned: ReadonlyArray<readonly [string, string]> = [
    ['data root', root],
    [SECRETS_DIR, path.join(root, SECRETS_DIR)],
    [LOGS_DIR, path.join(root, LOGS_DIR)],
    [BACKUPS_DIR, path.join(root, BACKUPS_DIR)],
    [INSTANCE_LOCK, path.join(root, INSTANCE_LOCK)],
    [TOKEN_FILE, path.join(root, TOKEN_FILE)],
  ]
  for (const [label, candidate] of owned) {
    let entry
    try {
      entry = lstatSync(candidate)
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue
      throw new DataRootError(
        'DATA_ROOT_INVALID',
        `the ${label} path cannot be inspected`,
        'check the permissions on the data root and its parents',
      )
    }
    if (entry.isSymbolicLink()) {
      throw new DataRootError(
        'DATA_ROOT_SYMLINK',
        `the ${label} path is a symbolic link`,
        `point ${DATA_ROOT_ENV} at a real directory; links are refused before their target is read`,
      )
    }
  }
}

/** The token LOCATOR. The bytes behind it never cross this boundary (C-02 §2). */
export function tokenFileOf(root: string): string {
  return path.join(root, TOKEN_FILE)
}

export function logsDirOf(root: string): string {
  return path.join(root, LOGS_DIR)
}

export function serverLogFileOf(root: string): string {
  return path.join(root, SERVER_LOG_FILE)
}

export function desktopLogFileOf(root: string): string {
  return path.join(root, DESKTOP_LOG_FILE)
}

export function backupsDirOf(root: string): string {
  return path.join(root, BACKUPS_DIR)
}

/**
 * C-02 §2's three variables, spelled exactly as the connectors read them.
 *
 * `plugins/connectors/ordessa/src/target.ts` refuses a missing
 * `ORDESSA_SERVER_ORIGIN` or `ORDESSA_SERVER_TOKEN_FILE`, naming the host
 * as the party that must supply them. This is the host's side of that
 * refusal: the origin is an origin and nothing else, and only a locator
 * crosses into the extension host — never the token.
 */
export function launchEnv(dataRoot: string, origin: string): Readonly<Record<string, string>> {
  const launch = layout().launch
  return {
    [launch.dataRootEnv]: dataRoot,
    [launch.originEnv]: origin,
    [launch.tokenFileEnv]: tokenFileOf(dataRoot),
  }
}
