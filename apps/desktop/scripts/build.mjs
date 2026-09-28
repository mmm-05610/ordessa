import { build } from 'esbuild'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { exportIcons } from './build-icons.mjs'
import { writeBuildInfo } from './build-info.mjs'
import { assertNoTestDrivers } from './release-hygiene.mjs'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repoRoot = path.resolve(root, '../..')
await import('../../../tooling/build-all.mjs')
await mkdir(path.join(root, 'dist/renderer/shared'), { recursive: true })
// All shared entrypoints are one splitting build, so React and API have one identity.
await build({
  entryPoints: Object.fromEntries(['react', 'jsx-runtime', 'react-dom', 'react-dom-client', 'api', 'ui-components-api'].map(name => [name, path.join(root, 'renderer/shared/' + name + '.ts')])),
  outdir: path.join(root, 'dist/renderer/shared'), bundle: true, splitting: true,
  platform: 'browser', format: 'esm', target: 'chrome132',
  define: { 'process.env.NODE_ENV': '"production"' },
})
await build({
  entryPoints: [path.join(root, 'renderer/main.tsx')], outfile: path.join(root, 'dist/renderer/main.js'),
  bundle: true, platform: 'browser', format: 'esm', target: 'chrome132', jsx: 'automatic',
  external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@ordessa/extension-api'],
  loader: { '.css': 'css' },
})
for (const name of ['main', 'preload']) await build({
  entryPoints: [path.join(root, 'electron/' + name + '.ts')],
  outfile: path.join(root, 'dist', name === 'main' ? 'electron-main.cjs' : 'preload.cjs'),
  bundle: true, platform: 'node', format: 'cjs', target: 'node22', external: ['electron'],
  // PA-11：smoke 驱动是**运行时按路径**加载的，esbuild 不得尝试打包它。
  logOverride: { 'unsupported-dynamic-import': 'silent' },
})
// PA-02/PC-05：产品元数据 + 版本/构建号注入（关于面板、诊断 meta、发行清单同源）。
const product = await writeBuildInfo({ repoRoot, outDir: path.join(root, 'dist') })
// PA-03：图标从 `assets/brand/icon.svg` 导出；缺设计稿时用占位图，构建不阻塞。
const icons = await exportIcons({ repoRoot, outDir: path.join(root, 'dist/icons') })
// PA-11：发行物里不得有测试驱动代码——真实构建即真实门。
await assertNoTestDrivers(path.join(root, 'dist'))
console.log(`product: ${product.info.productName} ${product.info.version} (${product.info.build}); icons: source=${icons.haveSource} rasterized=${icons.rasterized}`)
