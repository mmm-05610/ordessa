import { layout, tokenFileOf } from './data-root.js'
import { HttpWirePort as SharedHttpWirePort, type HttpWirePortOptions as SharedOptions } from '@ordessa/system-access-client/wire-port'
export { interpret, AbsentWirePort, PendingWirePort } from '@ordessa/system-access-client/wire-port'
export type HttpWirePortOptions = Omit<SharedOptions, 'wirePathPrefix'>
export class HttpWirePort extends SharedHttpWirePort {
  constructor(options: HttpWirePortOptions) { super({ ...options, wirePathPrefix: layout().launch.wirePathPrefix }) }
}
/**
 * Read the bearer from the data root's token file — main process only.
 *
 * The locator is built from the shared layout, the file is read with the
 * caller's own privileges, and the returned string is used inside the
 * `Authorization` header and nowhere else. A read failure answers `null`,
 * which the port turns into `transport-unreachable`; the error text is
 * dropped on the floor so no path can ride along in a result.
 */
export function tokenReaderFor(
  dataRoot: string,
  readFile: (file: string) => Promise<string>,
): () => Promise<string | null> {
  const locator = tokenFileOf(dataRoot)
  return async () => {
    try {
      const bytes = await readFile(locator)
      // A single trailing end-of-line is stripped; anything else is refused
      // rather than cleaned, because a token with a control byte in it is
      // not the token the Server issued.
      const token = bytes.replace(/\r?\n$/, '')
      if (token.length === 0 || /[\u0000-\u001f\u007f]/.test(token)) return null
      return token
    } catch {
      return null
    }
  }
}
