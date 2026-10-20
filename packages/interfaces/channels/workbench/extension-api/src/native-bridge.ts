export interface NativeConnection {
  send(frame: unknown): Promise<unknown>
  close(): Promise<void>
}
export interface NativeTransport {
  open(onFrame: (frame: unknown) => void): Promise<NativeConnection>
}


/**
 * Renderer-side handle to the agent-native IPC bridge (T008-06): the type
 * lives here in the public bridge contract; consumers import this contract
 * directly and never reach into `apps/desktop/**` (migration-map:
 * "ACP host导入apps/desktop/renderer/agent-native → frontend公开bridge
 * contract"). Shape frozen with the original declaration.
 */
export interface AgentNativeBridge {
  open(adapterId: string): Promise<string>
  send(instanceId: string, frame: unknown): Promise<unknown>
  close(instanceId: string): Promise<void>
  subscribe(listener: (event: { instanceId: string; frame?: unknown; error?: string }) => void): () => void
}
