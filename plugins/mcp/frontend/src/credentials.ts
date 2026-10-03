// CredentialProvider: the frontend abstraction over the unified credential
// service (ux.md —「秘密输入委托统一凭据提供者，页面不回显明文」).
//
// The interface deliberately has NO method that returns a secret value: the
// page can only list credential REFERENCES (ids + labels) so a secretRef input
// is a picker over ids. Whatever resolves an id into a value stays server-side
// behind the host CredentialRecords/SecretStore layers (T07). When no provider
// is installed the secretRef fields render read-only and the revision cannot
// be applied (批准并用于选择 is blocked) — the UI never grows a local vault.

export interface CredentialReference {
  readonly credentialId: string
  /** Display label chosen by the provider; ids stay distinguishable by it. */
  readonly label: string
}

export interface CredentialProvider {
  listCredentials(signal?: AbortSignal): Promise<readonly CredentialReference[]>
}
