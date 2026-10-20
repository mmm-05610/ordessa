import { BoardStore } from '@ordessa/status-board'
import { QueryClient, type WireResult } from '@ordessa/system-access-client'
import { engineeringQueries } from './engineering-queries'
import { refreshIntervalMs } from './config'
import type { BoardHost, HostFault } from '@ordessa/status-board'
declare global { interface Window { desktopHost?: { wireCall(method: string, params: Record<string, unknown>): Promise<WireResult>; faults(): Promise<readonly HostFault[]> }; statusBoardHost?: BoardHost } }
export function composeBoard() {
  const port = { call: (method: string, params: Readonly<Record<string, unknown>>) => window.desktopHost?.wireCall(method, params) ?? Promise.resolve({ kind: 'Unknown', requestId: 'browser', reason: 'port-absent' }) }
  const discovery = new QueryClient(port, 'server.hello', { clientVersions: ['wire/1'], clientPresentationSupports: [] })
  // Work projection and trusted confirmation remain absent. Exact Engineering queries do not create Work.
  return { store: new BoardStore(), discovery, exactQueries: engineeringQueries(port), host: window.statusBoardHost, readHostFaults: window.desktopHost ? () => window.desktopHost!.faults() : undefined, refreshIntervalMs }
}
