// The public contract owns this type (T008-06); the app only re-exports it
// so the window typing and consumers share ONE declaration.
import type { AgentNativeBridge } from '@ordessa/native-bridge'
export type { AgentNativeBridge }
declare global { interface Window {
  agentNative: AgentNativeBridge
  projectDirectory?: { choose(): Promise<string | undefined> }
} }
export function agentNative(): AgentNativeBridge { return window.agentNative }
