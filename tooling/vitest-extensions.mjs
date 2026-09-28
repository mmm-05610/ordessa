// Single source of truth for the `@extensions/<id>/contract.js` → source-file
// mapping. The product resolves these specifiers at runtime through the
// `ordessa:/extensions/...` module channel (packages/desktop-platform/extension-host);
// every dev-time loader — vitest configs and the ACP rig's Node customization
// hooks — has to answer the same question, and four hand-written copies of the
// answer drifted the moment a carrier moved. Contract ids are persistent
// identities, so they are keyed here and nowhere else.
import path from 'node:path'

const repoRoot = path.resolve(import.meta.dirname, '..')

/** Extension id → its contract source file, relative to the repository root. */
export const CONTRACT_SOURCES = {
  'ordessa.contracts': 'packages/desktop-platform/contracts/foundation/src/contract.ts',
  'ordessa.agent-contracts': 'plugins/agent/contracts/src/contract.ts',
}

/** Vite `resolve.alias` entries for every contract carrier. */
export function contractAliases() {
  return Object.fromEntries(Object.entries(CONTRACT_SOURCES)
    .map(([id, rel]) => [`@extensions/${id}/contract.js`, path.join(repoRoot, rel)]))
}
