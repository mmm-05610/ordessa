/**
 * `@ordessa/server-bridge` — the host's seam onto the Server it starts.
 *
 * P-A consumes this package; it is the one coupling point between the two
 * implementation packages. Nothing here imports a plugin, a host internal or
 * a brand: the bridge knows about a data root, a child process, a loopback
 * origin and a wire method name, and about nothing else.
 */
export {
  BACKUPS_DIR,
  DATA_ROOT_ENV,
  DEFAULT_DATA_ROOT_DIRNAME,
  DIR_MODE,
  DESKTOP_LOG_FILE,
  INSTANCE_LOCK,
  LOGS_DIR,
  SECRETS_DIR,
  SECRET_FILE_MODE,
  SERVER_LOG_FILE,
  TOKEN_FILE,
  DataRootError,
  assertNoSymlink,
  backupsDirOf,
  desktopLogFileOf,
  launchEnv,
  layout,
  logsDirOf,
  resolveDataRoot,
  serverLogFileOf,
  tokenFileOf,
  type DataRootLayout,
  type DataRootSource,
  type ResolvedDataRoot,
} from './data-root.js'

export {
  BundledRuntimeMissing,
  LaunchError,
  PortAllocationFailed,
  ServerCrashed,
  ServerExitedEarly,
  ServerHandshakeMalformed,
  ServerStartTimeout,
  type LaunchErrorCode,
} from './errors.js'

export {
  bundledRootExists,
  resolveBundledRuntime,
  serverCommand,
  type BundledRuntime,
} from './runtime.js'

export {
  ServerBridge,
  parseHandshake,
  serverInstanceId,
  type HandshakeLine,
  type ServerBridgeOptions,
  type ServerInstance,
  type ServerState,
} from './lifecycle.js'

export {
  AbsentWirePort,
  HttpWirePort,
  PendingWirePort,
  interpret,
  tokenReaderFor,
  type HttpWirePortOptions,
  type WirePort,
  type WireReason,
  type WireResult,
} from './wire-port.js'
