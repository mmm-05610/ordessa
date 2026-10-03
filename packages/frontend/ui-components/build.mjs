import { buildExtension } from '../../../tooling/build-extension.mjs'

// The runtime carrier supplies the Token, so the extension bundle carries only
// the assembly entry plus the service implementation (see extension/entry.ts).
await buildExtension(import.meta.dirname, { entries: { entry: 'extension/entry.ts' } })
