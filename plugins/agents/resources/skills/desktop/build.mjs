import { buildExtension } from '../../../../../tooling/workspace/build-extension.mjs'
// The shared contracts are type-only sources imported by relative path, so the
// bundle needs no extra entry; esbuild inlines them.
await buildExtension(import.meta.dirname, { entries: { entry: 'src/entry.tsx' } })
