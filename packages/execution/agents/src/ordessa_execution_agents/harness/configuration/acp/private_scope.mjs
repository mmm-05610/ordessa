import { lstatSync, realpathSync } from 'node:fs'
import path from 'node:path'
export function establishPrivateScope(scope) {
try {
  const directory = process.env.ORDESSA_NATIVE_INSTANCE_DIR
  if (!directory || !path.isAbsolute(directory) || path.normalize(directory) !== directory)
    throw new Error('invalid instance scope')
  const stat = lstatSync(directory)
  if (!stat.isDirectory() || stat.isSymbolicLink() || realpathSync(directory) !== directory
      || stat.uid !== process.getuid() || (stat.mode & 0o077) !== 0)
    throw new Error('invalid instance ownership')
  // The backend owner allocates a unique private directory. Never implicitly
  // copy login/configuration from the user's HOME or create through symlinks.
  for (const key of scope.environmentKeys) process.env[key] = directory
  const account = process.env[scope.managedAccountKey]
  if (account !== undefined) {
    if (!scope.supportsManagedAccount || !account || !path.isAbsolute(account)
        || path.normalize(account) !== account || account.endsWith(path.sep))
      throw new Error('invalid account scope')
    const info = lstatSync(account)
    if (!info.isDirectory() || info.isSymbolicLink() || realpathSync(account) !== account
        || info.uid !== process.getuid() || (info.mode & 0o077) !== 0
        || account === directory || account.startsWith(directory + path.sep)
        || directory.startsWith(account + path.sep))
      throw new Error('invalid account ownership')
    process.env[scope.managedHomeKey] = account
  }
  for (const key of scope.clearedCredentialKeys) delete process.env[key]

} catch {
  // Closed diagnostic: no user paths, credentials or upstream errors.
  console.error('Native Profile startup refused: private instance directory required')
  process.exit(1)
}
}
