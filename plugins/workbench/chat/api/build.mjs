import { buildExtension } from '../../../../tooling/workspace/build-extension.mjs'
await buildExtension(import.meta.dirname, {"entries":{"entry":"src/entry.ts","contract":"src/contract.ts"}})
