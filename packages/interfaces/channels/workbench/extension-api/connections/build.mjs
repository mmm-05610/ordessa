import { buildExtension } from '../../../../../../tooling/workspace/build-extension.mjs'
await buildExtension(import.meta.dirname, { entries: { entry: 'extension/entry.ts' } })
