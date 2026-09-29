import type * as acp from '@agentclientprotocol/sdk'
import type { AgentWorkspaceInfo } from '@extensions/ordessa.agent-contracts/contract.js'
import type { AcpControlledSubmission, AcpPermissionDecision, AcpSubmissionAdmission } from './submission'
import type { AcpAttachmentPreparePort } from './attachments'

/**
 * The reviewed injection seam (docs/acp-connector-test-review.md): the backend orchestration owns
 * picking a Server/Harness, listing and binding projects, and standing project-bound ACP channels
 * up and down. The connector only consumes the managed handle — identity, authoritative binding,
 * stream, explicit release — and never opens a project-less channel, guesses a path, or infers a
 * backend release from a transport event. These types mirror the frozen fixture seam
 * (tests/integration/acp-connector/fixtures/target-seam.ts); they are a proposed injection surface pending
 * backend alignment, NOT a second public protocol.
 */

/** One project-bound ACP channel as the orchestration hands it over. Dropping the transport,
 * switching the UI view and releasing the backend channel are three distinct events; only
 * release() stands the backend channel down. */
export interface AcpChannelHandle {
  /** Orchestration-issued identity for this channel instance. */
  readonly connectionId: string
  /** The authoritative project binding this channel serves; `binding.normalizedPath` is the
   * `session/new` cwd. */
  readonly binding: AgentWorkspaceInfo
  readonly stream: acp.Stream
  /** Optional transport-owned terminal fact. Command catalogs stay unknown without this fact. */
  subscribeDown?: (listener: (reason: string) => void) => () => void
  /** Optional until the Server publishes the authenticated C5 admission method. A controlled
   * submit refuses when absent; no frontend-created permit is accepted. */
  authorizeSubmission?: (submission: AcpControlledSubmission) => Promise<AcpSubmissionAdmission>
  /** Owner-supplied content preparation. Absent in the current production host. */
  attachmentPrepare?: AcpAttachmentPreparePort
  /** Backend Q5 authority must verify execution-time permission before the ACP answer is sent. */
  authorizePermission?: (decision: AcpPermissionDecision) => Promise<AcpSubmissionAdmission>
  /** Explicit backend release. */
  release(): Promise<void>
}

export interface AcpChannelSpec {
  /** Real Server instance identity behind the connection (never a plugin id). */
  serverInstanceId: string
  /** The one Harness selected through orchestration; the connector never picks or spawns one. */
  harness: { id: string; title: string }
  /** Server-authoritative project records; readable on selection, without any ACP channel. */
  listProjects: () => Promise<readonly AgentWorkspaceInfo[]>
  /** The authoritative binding for one project; its `normalizedPath` is the `session/new` cwd. */
  openProject: (id: string) => Promise<AgentWorkspaceInfo>
  /** Register a user-picked local directory with this Server over the SAME existing
   * `workspaces.open` upsert the project surface already rides (no new backend method), and answer
   * its authoritative record. Optional on purpose: where orchestration does not supply it, the
   * client exposes no `addWorkspace` and the UI must disable that entry, never fake it. */
  addProject?: (path: string) => Promise<AgentWorkspaceInfo>
  /** Acquire the managed channel for the selected project. No channel exists until a project is
   * bound; `initialize` runs on the handle's stream. */
  acquireChannel: (projectId: string) => Promise<AcpChannelHandle>
}
