import path from 'node:path'
/** Trusted launcher opt-in. Credentials remain in the main process. No server lifecycle ownership. */
export function statusBoardConnection(env: NodeJS.ProcessEnv, desktopDataRoot: string): { origin: string; serverDataRoot: string; tokenLocator?: string } | undefined {
  const origin = env.ORDESSA_STATUS_BOARD_SERVER_ORIGIN
  const serverDataRoot = env.ORDESSA_STATUS_BOARD_SERVER_DATA_ROOT
  const tokenLocator = env.ORDESSA_STATUS_BOARD_TOKEN_LOCATOR
  if (!origin && !serverDataRoot && !tokenLocator) return undefined
  if (!origin || !serverDataRoot) throw Error('Status-board connection requires explicit origin and server data root')
  let parsed: URL
  try { parsed = new URL(origin) } catch { throw Error('Status-board connection origin is invalid') }
  if (parsed.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(parsed.hostname)
    || parsed.username || parsed.password || parsed.pathname !== '/' || parsed.search || parsed.hash) throw Error('Status-board connection must be a plain loopback HTTP origin')
  if (!path.isAbsolute(serverDataRoot)) throw Error('Status-board server data root must be absolute')
  if (path.resolve(serverDataRoot) === path.resolve(desktopDataRoot)) throw Error('Status-board must use its own desktop data root')
  if (tokenLocator && (!path.isAbsolute(tokenLocator) || !path.resolve(tokenLocator).startsWith(path.resolve(serverDataRoot) + path.sep))) throw Error('Status-board token locator must be inside the selected server data root')
  return { origin: parsed.origin, serverDataRoot, ...(tokenLocator ? { tokenLocator: path.resolve(tokenLocator) } : {}) }
}

const readMethods = new Set(['server.hello', 'engineering.capabilities', 'engineering.artifacts.get', 'engineering.references.resolve', 'engineering.proposals.get', 'engineering.proposals.get_control', 'engineering.changes.get', 'engineering.commands.get', 'engineering.reviews.get_request', 'engineering.notices.get', 'engineering.approvals.get', 'engineering.approvals.get_control', 'engineering.approvals.get_intent', 'engineering.approvals.get_challenge', 'engineering.approvals.list_pending', 'engineering.work.get', 'engineering.work.current_condition', 'engineering.runs.get_wait'])
export function isStatusBoardRead(method: unknown): boolean { return typeof method === 'string' && readMethods.has(method) }
