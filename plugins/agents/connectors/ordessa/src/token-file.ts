import { constants, closeSync, fstatSync, openSync, readSync } from 'node:fs'
import path from 'node:path'
import { MAX_TOKEN_BYTES, parseToken, refusal } from './target'

export const TOKEN_FILE_NAME = 'http-token'
export const TOKEN_FILE_PARENT = 'secrets'

const openRefusal = (code: string | undefined): string =>
  code === 'ELOOP' ? 'token file is a symlink'
    : code === 'ENOENT' ? 'token file is unreadable'
    : code === 'EACCES' || code === 'EPERM' ? 'token file is not readable by this user'
    : code === 'ENOTDIR' ? 'token file path is not a file'
    : 'token file is unreadable'

/**
 * The Server writes its bearer into `<data-root>/secrets/http-token` at 0600, so a locator is only
 * evidence of the same data-root when that shape and those ownership facts hold. Everything is
 * checked on one descriptor: a path verified and then re-opened could be swapped in between, and a
 * directory or symlink that survives to `readFile` would hand the token to the wrong file.
 */
export async function readRestrictedTokenFile(locator: string): Promise<string> {
  const source = path.basename(locator)
  if (source !== TOKEN_FILE_NAME) refusal('token file is not named http-token', source)
  if (path.basename(path.dirname(locator)) !== TOKEN_FILE_PARENT) refusal('token file is not inside the data-root secrets directory', source)
  // Ownership and mode mean nothing without a comparable owner, so an unsupported platform is refused rather than trusted.
  const getuid = typeof process.getuid === 'function' ? process.getuid : undefined
  if (!getuid) refusal('token file ownership cannot be checked on this platform', source)
  let descriptor: number
  try {
    descriptor = openSync(locator, constants.O_RDONLY | constants.O_NOFOLLOW)
  } catch (error) {
    // The OS message embeds the absolute locator, so only its code is ever reported.
    return refusal(openRefusal((error as NodeJS.ErrnoException).code), source)
  }
  try {
    const stats = fstatSync(descriptor)
    if (!stats.isFile()) refusal('token file is not a regular file', source)
    if ((stats.mode & 0o077) !== 0) refusal('token file is readable by group or other', source)
    if ((stats.mode & 0o400) === 0) refusal('token file is not readable by its owner', source)
    if (stats.uid !== getuid()) refusal('token file is owned by another user', source)
    if (stats.size === 0) refusal('token file is empty', source)
    if (stats.size > MAX_TOKEN_BYTES) refusal('token file is too large', source)
    const buffer = Buffer.allocUnsafe(MAX_TOKEN_BYTES + 1)
    let length = 0
    for (;;) {
      const read = readSync(descriptor, buffer, length, buffer.byteLength - length, length)
      if (read === 0) break
      length += read
      // The size check came from an earlier fstat, so growth while reading still refuses.
      if (length >= buffer.byteLength) refusal('token file is too large', source)
    }
    return parseToken(buffer.subarray(0, length), source)
  } finally {
    closeSync(descriptor)
  }
}
