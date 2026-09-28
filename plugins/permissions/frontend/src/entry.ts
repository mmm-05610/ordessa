// Extension entry point. Real activation — resolving ChatContributionsToken,
// creating the host transport and registering `createApprovalContributions()`
// under the plugin's ResourceScope — is product composition work that is
// registered as UNPROVEN in this batch (README); this entry only makes the
// package buildable and is deliberately side-effect free.
export default function createPlugin() {
  return { id: 'ordessa.permissions-chat', activate() {} }
}
