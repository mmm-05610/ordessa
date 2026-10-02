import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, readFileSync, rmSync, symlinkSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { compileCodexModelCatalog, writeCodexModelCatalog } from './codex-model-catalog.mjs'

const capabilities = { toolCall: true, reasoning: true,
  reasoningOptions: [{type: 'effort', values: ['low', 'medium', 'high']}],
  modalities: {input: ['text']}, limits: {context: 64000} }

test('catalogue is built from declared facts, not an official model template', () => {
  const catalog = compileCodexModelCatalog('third-party-test', capabilities)
  assert.equal(catalog.models.length, 1)
  const model = catalog.models[0]
  assert.equal(model.slug, 'third-party-test')
  assert.deepEqual(model.supported_reasoning_levels.map(x => x.effort), ['low', 'medium', 'high'])
  assert.equal(model.context_window, 64000)
  assert.deepEqual(model.input_modalities, ['text'])
  assert.equal(model.use_responses_lite, false)
  assert.ok(model.base_instructions.startsWith('You are a coding agent'))
  assert.equal(model.upgrade, null)
  assert.equal(model.comp_hash, undefined)
})

test('unknown facts and malformed facts cannot become advertised capabilities', () => {
  for (const invalid of [undefined, {}, {...capabilities, reasoningOptions: []},
    {...capabilities, reasoningOptions: [{type: 'budget', values: ['high']}]},
    {...capabilities, reasoningOptions: [{type: 'effort', values: ['high', 'high']}]},
    {...capabilities, limits: {context: -1}}, {...capabilities, apiKey: 'synthetic-secret'},
    {...capabilities, modalities: {input: ['video']}}])
    assert.throws(() => compileCodexModelCatalog('test', invalid))
  const sparse = compileCodexModelCatalog('test', {toolCall: true, reasoning: false})
  assert.equal(sparse.models[0].context_window, undefined)
  assert.deepEqual(sparse.models[0].supported_reasoning_levels, [])
  assert.equal(sparse.models[0].default_reasoning_level, null)
})

test('catalogue files are content addressed, immutable and instance scoped', t => {
  const home = mkdtempSync(path.join(tmpdir(), 'ordessa-model-catalog-'))
  t.after(() => rmSync(home, {recursive: true, force: true}))
  const first = writeCodexModelCatalog(home, 'test', capabilities)
  assert.equal(writeCodexModelCatalog(home, 'test', capabilities), first)
  assert.equal(statSync(first).mode & 0o777, 0o400)
  const second = writeCodexModelCatalog(home, 'test', {...capabilities, limits: {context: 128000}})
  assert.notEqual(first, second)
  assert.equal(JSON.parse(readFileSync(first)).models[0].context_window, 64000)
  assert.ok(first.startsWith(home + path.sep))
})

test('existing symlink catalogue directory is refused', t => {
  const home = mkdtempSync(path.join(tmpdir(), 'ordessa-model-symlink-'))
  const outside = mkdtempSync(path.join(tmpdir(), 'ordessa-model-outside-'))
  t.after(() => {rmSync(home, {recursive: true, force: true}); rmSync(outside, {recursive: true, force: true})})
  symlinkSync(outside, path.join(home, 'model-catalogs'))
  assert.throws(() => writeCodexModelCatalog(home, 'test', capabilities))
})
