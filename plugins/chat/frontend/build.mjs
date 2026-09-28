import { buildExtension } from '../../../tooling/build-extension.mjs'
await buildExtension(import.meta.dirname, {
  entries: { entry: 'src/entry.tsx' },
  licenses: [
    ['streamdown/LICENSE', 'streamdown-LICENSE'],
    ['shiki/LICENSE', 'shiki-LICENSE'],
    ['use-stick-to-bottom/LICENSE.txt', 'use-stick-to-bottom-LICENSE'],
  ],
})
