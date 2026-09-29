/**
 * Shared-module entry, mirroring packages/desktop-platform/contracts/agent-ui.
 * The contract is delivered as an independently loaded module; importing it
 * enables nothing (no auto-enable, contracts.md preamble).
 */
export default function createPlugin() {
  return { id: 'ordessa.profile-api', activate() {} }
}
