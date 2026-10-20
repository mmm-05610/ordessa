import path from 'node:path'

export const SERVER_ORIGIN_ENV = 'ORDESSA_SERVER_ORIGIN'
export const SERVER_TOKEN_FILE_ENV = 'ORDESSA_SERVER_TOKEN_FILE'

export interface ServerTarget {
  /** Normalized loopback HTTP origin, e.g. http://127.0.0.1:41207 — no path, query or credentials. */
  origin: string
  /** Same-origin WebSocket base, used for the authenticated event stream. */
  socket: string
  token: string
}

/** Refusals never carry token bytes, and the locator only ever appears as its basename. */
export class ServerConfigError extends Error {}

const LOOPBACK = /^(\[::1\]|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|localhost)$/
export const MAX_TOKEN_BYTES = 4096

/** Every refusal is `reason; who could fix it`, and neither half may hold a secret or a locator. */
export function refusal(reason: string, source: string): never {
  throw new ServerConfigError(`Ordessa Server ${reason}; ${source}`)
}

/** The two explicit host inputs are the only way this connector learns where the Server is. */
export function parseOrigin(raw: string | undefined): string {
  if (!raw) refusal(`${SERVER_ORIGIN_ENV} is not set`, 'the desktop host must pass the loopback origin of the Server it started')
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return refusal(`${SERVER_ORIGIN_ENV} is not a URL`, 'expected e.g. http://127.0.0.1:<port>')
  }
  if (url.protocol !== 'http:') refusal(`${SERVER_ORIGIN_ENV} must use http`, 'only loopback http is served by the Server')
  if (!LOOPBACK.test(url.hostname)) refusal(`${SERVER_ORIGIN_ENV} host is not loopback`, `got ${url.hostname}`)
  if (!url.port) refusal(`${SERVER_ORIGIN_ENV} omits the port`, 'never assume the default port')
  if (url.pathname !== '/' || url.search || url.hash) refusal(`${SERVER_ORIGIN_ENV} must be an origin only`, 'no path, query or fragment')
  if (url.username || url.password) refusal(`${SERVER_ORIGIN_ENV} must not carry credentials`, 'the bearer token comes from the token file')
  // `url.origin` is the only form used as an identity scope, so two spellings of one Server cannot fork a project selection.
  return url.origin
}

/**
 * A token with an embedded newline would let one file forge extra headers, so only a
 * single trailing end-of-line is stripped and any other control byte is refused.
 */
export function parseToken(bytes: Buffer, source: string): string {
  if (bytes.byteLength > MAX_TOKEN_BYTES) refusal('token file is too large', source)
  const token = bytes.toString('utf8').replace(/\r?\n$/, '')
  if (!token) refusal('token file is empty', source)
  if (/[\u0000-\u001f\u007f]/.test(token)) refusal('token file holds control characters', source)
  return token
}

/** The caller supplies the privileged reader (see token-file.ts), which returns a parsed bearer; this half only trusts the two env inputs. */
export async function resolveServerTarget(
  env: NodeJS.ProcessEnv,
  readToken: (locator: string) => Promise<string>,
): Promise<ServerTarget> {
  const origin = parseOrigin(env[SERVER_ORIGIN_ENV])
  const locator = env[SERVER_TOKEN_FILE_ENV]
  if (!locator) refusal(`${SERVER_TOKEN_FILE_ENV} is not set`, 'the desktop host must pass the token locator for the same data-root')
  if (!path.isAbsolute(locator)) refusal(`${SERVER_TOKEN_FILE_ENV} is not absolute`, 'expected the Server data-root token file path')
  const token = await readToken(locator)
  if (!token) refusal('token file is empty', path.basename(locator))
  return { origin, socket: origin.replace(/^http:/, 'ws:'), token }
}

/** Stable non-secret scope for project selections; the Server id behind it is re-checked on reconnect. */
export function serverInstanceId(origin: string, serverId: string): string {
  return `${origin}|${serverId}`
}
