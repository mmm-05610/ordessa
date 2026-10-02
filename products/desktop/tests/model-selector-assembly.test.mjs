import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import test from 'node:test'
import { build } from 'esbuild'

const repoRoot = path.resolve(import.meta.dirname, '../../..')
const selectorId = 'ordessa.model-provider-chat'

test('product admits the model selector and binds its published component key', async () => {
  const product = JSON.parse(await readFile(path.join(repoRoot, 'products/desktop/extensions.json'), 'utf8'))
  assert.ok(product.enabled.includes(selectorId), 'the model selector is absent from the product')
  assert.ok(product.config['ordessa.ui-components'].some(binding =>
    binding.componentId === 'ordessa.chat.model-selector' && binding.major === 1 && binding.providerId === selectorId),
  'Chat cannot render an unbound model-selector key')
})

test('built provider and Chat consumer share one token and register through scoped public services', async () => {
  const outputRoot = await mkdtemp(path.join(os.tmpdir(), 'ordessa-model-selector-'))
  try {
    for (const dir of ['packages/desktop-platform/contracts/foundation', 'plugins/agent/contracts', 'plugins/chat/api', 'plugins/profile/api',
      'plugins/assets/model-provider/desktop', 'plugins/assets/model-provider/chat-contribution']) {
      execFileSync(process.execPath, [path.join(repoRoot, dir, 'build.mjs')], {
        cwd: repoRoot, env: { ...process.env, ORDESSA_PRODUCT_OUTPUT_ROOT: outputRoot }, stdio: 'pipe',
      })
    }
    const extensions = path.join(outputRoot, 'extensions')
    const contract = path.join(extensions, 'ordessa.model-provider/contract.js')
    await readFile(contract)
    const manifest = JSON.parse(await readFile(path.join(extensions, selectorId, 'manifest.json'), 'utf8'))
    assert.equal(manifest.id, selectorId)
    assert.equal(manifest.entry, 'entry.js')
    const outfile = path.join(outputRoot, 'assembly.mjs')
    await build({
      stdin: { contents: `
        export { default as provider } from ${JSON.stringify(path.join(extensions, 'ordessa.model-provider/entry.js'))};
        export { ModelProviderToken } from ${JSON.stringify(contract)};
        export { default as selector, ModelSelectorKey } from ${JSON.stringify(path.join(extensions, selectorId, 'entry.js'))};
        export { createChatContributions } from ${JSON.stringify(path.join(extensions, 'ordessa.chat-api/contract.js'))};
        export { OwnedResources } from '@ordessa/extension-api';
        export { createUiComponentsService } from ${JSON.stringify(path.join(repoRoot, 'packages/desktop-platform/ui-components/src/index.ts'))};
        import { createElement } from 'react';
        import { renderToStaticMarkup } from 'react-dom/server';
        import { ComponentOutlet } from ${JSON.stringify(path.join(repoRoot, 'packages/desktop-platform/ui-components/react/index.ts'))};
        export const renderSelector = (binding, location) => renderToStaticMarkup(createElement(ComponentOutlet, { binding, value: { location }, missing: null }));
      `, resolveDir: repoRoot },
      outfile, bundle: true, format: 'esm', platform: 'node', jsx: 'automatic',
      nodePaths: [path.join(repoRoot, 'node_modules')],
      banner: { js: "import { createRequire } from 'node:module'; const require = createRequire(import.meta.url);" },
      plugins: [{ name: 'published-extension-contracts', setup(builder) {
        builder.onResolve({ filter: /^@extensions\// }, ({ path: specifier }) =>
          ({ path: path.join(extensions, specifier.slice('@extensions/'.length)) }))
        builder.onResolve({ filter: /^@ordessa\/ui-components\/api$/ }, () =>
          ({ path: path.join(repoRoot, 'packages/desktop-platform/ui-components/api/ui-components.ts') }))
      } }],
    })
    const assembly = await import(pathToFileURL(outfile).href)
    const provider = assembly.provider()
    const selector = assembly.selector()
    assert.equal(provider.provides, assembly.ModelProviderToken)
    assert.ok(selector.requires.includes(assembly.ModelProviderToken), 'consumer bundled a second ModelProviderToken')
    const resources = new assembly.OwnedResources()
    const uiService = assembly.createUiComponentsService([
      { componentId: assembly.ModelSelectorKey.id, major: 1, providerId: selectorId },
    ])
    const chat = assembly.createChatContributions()
    const calls = []
    const wire = { call: async (method, params) => { calls.push({ method, params }); return { kind: 'Accepted', result: { items: [] } } } }
    const context = { resources }
    const service = provider.activate(context, { composition: { forScope: () => ({ addSettingsSection() {} }) } }, wire, null)
    selector.activate(context, chat, uiService.uiComponents, wire, service)
    const [view] = chat.contributionsBySlot('composer.toolbar').getSnapshot()
    assert.equal(view.id, 'model-provider.composer.model-selector')
    const consumer = new assembly.OwnedResources()
    const binding = uiService.uiComponents.forScope(consumer).bind(view.key, { required: true })
    assert.equal(binding.getSnapshot().status, 'ready')
    const location = { kind: 'session', connectionId: 'fixture', serverInstanceId: 'fixture-server',
      harnessId: 'fixture-harness', sessionId: 'fixture-session', contextRevision: 0 }
    assert.match(assembly.renderSelector(binding, location), /data-testid="model-selector-trigger"/)
    assert.deepEqual(calls, [], 'registration must not contact a real model or probe a provider')
    await resources.dispose()
    assert.equal(chat.contributionsBySlot('composer.toolbar').getSnapshot().length, 0)
    assert.equal(binding.getSnapshot().status, 'missing')
    assert.equal(assembly.renderSelector(binding, location), '')
    await consumer.dispose()
    uiService.dispose()
  } finally { await rm(outputRoot, { recursive: true, force: true }) }
})
