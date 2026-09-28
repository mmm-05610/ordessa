// Extension entry point. Real activation — resolving ProfileServiceToken and
// the workbench, registering the settings/management views under the plugin's
// ResourceScope — is product composition work owned by the core integration
// (seams S-01); the tokens the views consume are absent until that wiring
// lands, and registering a fake picker now would be exactly the dishonest
// activation the contracts forbid. This entry only makes the package
// buildable and loadable in the extensions channel; it is deliberately
// side-effect free.
export default function createPlugin() {
  return { id: 'ordessa.profile-frontend', activate() {} }
}
