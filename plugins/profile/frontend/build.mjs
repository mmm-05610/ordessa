import { buildExtension } from '../../../tooling/build-extension.mjs'
await buildExtension(import.meta.dirname, {"entries":{"entry":"src/entry.ts"}})
