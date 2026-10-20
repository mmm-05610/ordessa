import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { captureTemplateArtifactContext, verifyTemplateArtifactEmission } from '../../generation/harness_template_context.mjs'
import { stageTemplateGraph } from '../../generation/harness_template_graph.mjs'
import { scanDependencyBoundaries } from '../../checks/dependency-boundaries.mjs'
import { templateArtifactContextDeclaration as codex, enhancementTemplateResources as codexResources } from '../../../plugins/harness/codex/tooling/profile_enhancement.mjs'
import { templateArtifactContextDeclaration as claude, enhancementTemplateResources as claudeResources } from '../../../plugins/harness/claude-code/tooling/profile_enhancement.mjs'
import { templateArtifactContextDeclaration as pi, profileTemplateResources as piResources } from '../../../plugins/harness/pi/tooling/profile_templates.mjs'
const sha256 = content => createHash('sha256').update(content).digest('hex')
function fixture(t) {
  const root = mkdtempSync(path.join(tmpdir(),'ordessa-artifact-context-'))
  t.after(() => rmSync(root,{recursive:true,force:true}))
  for (const name of ['packages','plugins','apps','products']) mkdirSync(path.join(root,name))
  const owner = path.join(root,'packages','controlled')
  const tooling = path.join(owner,'tooling')
  const upstreamPackageRoot = path.join(root,'upstream')
  for (const directory of [path.join(tooling,'npm'),path.join(owner,'src'),path.join(upstreamPackageRoot,'dist')]) mkdirSync(directory,{recursive:true})
  writeFileSync(path.join(root,'package.json'),JSON.stringify({name:'context-controlled-fixture',workspaces:[]}))
  writeFileSync(path.join(tooling,'npm/package-lock.json'),JSON.stringify({packages:{'node_modules/controlled-upstream':{version:'1.0.0',integrity:'sha512-Zg=='}}}))
  writeFileSync(path.join(upstreamPackageRoot,'package.json'),JSON.stringify({name:'controlled-upstream',version:'1.0.0'}))
  const original = 'export const agent = 1\n'
  writeFileSync(path.join(upstreamPackageRoot,'dist/agent.js'),original)
  const source = path.join(owner,'src/entry.mjs')
  writeFileSync(source,"import { agent } from './agent.js'; export { helper } from './helper.mjs'\n")
  const helper = path.join(owner,'src/helper.mjs')
  writeFileSync(helper,'export const helper = 2\n')
  const declaration = {schema_version:1,owner_id:'controlled',package_name:'controlled-upstream',package_lock:'npm/package-lock.json',output_directory:'dist',edges:[{source:'../src/entry.mjs',emitted_module:'dist/entry.mjs',specifier:'./agent.js',upstream_member:'dist/agent.js',sha256:sha256(original)}]}
  const declarationFile = path.join(tooling,'context.json')
  const save = () => writeFileSync(declarationFile,JSON.stringify(declaration))
  save()
  const resources = {'entry.mjs':source,'helper.mjs':helper}
  const input = {declarationFile,resources,upstreamPackageRoot}
  const capture = () => captureTemplateArtifactContext(declarationFile,input)
  return {root,source,declaration,declarationFile,resources,upstreamPackageRoot,capture,save,input}
}
test('own declarations bind exactly six source imports to the original artifact positions', () => {
  let count = 0
  for (const [declarationFor,resourcesFor] of [[codex,codexResources],[claude,claudeResources],[pi,piResources]]) {
    const declarationFile = declarationFor()
    const declaration = JSON.parse(readFileSync(declarationFile,'utf8'))
    const outputs = new Map(Object.entries(resourcesFor()).map(([name,source]) => [path.resolve(source),name]))
    for (const edge of declaration.edges) {
      count += 1
      const source = path.resolve(path.dirname(declarationFile),edge.source)
      assert.equal(outputs.get(source),path.posix.basename(edge.emitted_module))
      assert.ok(readFileSync(source,'utf8').includes(edge.specifier))
      assert.equal(path.posix.normalize(path.posix.join(path.posix.dirname(edge.emitted_module),edge.specifier)),edge.upstream_member)
      if (edge.sha256_from) {
        const pin = JSON.parse(readFileSync(path.resolve(path.dirname(declarationFile),edge.sha256_from.file),'utf8'))
        assert.equal(edge.sha256_from.pointer,'/nativeExtension/source')
        assert.match(pin.nativeExtension.source,/^[a-f0-9]{64}$/u)
      } else assert.match(edge.sha256,/^[a-f0-9]{64}$/u)
    }
  }
  assert.equal(count,6)
})
test('explicit original bytes and source graph verify actual emitted files', t => {
  const f = fixture(t), captured = f.capture()
  assert.equal(captured.edges.length,1)
  assert.equal(Object.isFrozen(captured.edges[0]),true)
  const destination = path.join(f.upstreamPackageRoot,'dist')
  stageTemplateGraph(destination,f.resources)
  assert.deepEqual(verifyTemplateArtifactEmission(destination,captured),{declarationFile:f.declarationFile,edges:1,files:2})
  writeFileSync(path.join(destination,'entry.mjs'),'changed\n')
  assert.throws(() => verifyTemplateArtifactEmission(destination,captured),/TEMPLATE_ARTIFACT_EMISSION_DRIFT/)
})
test('no context discovery and no missing or drifted upstream inputs', t => {
  const f = fixture(t)
  assert.throws(() => captureTemplateArtifactContext(f.declarationFile,{resources:f.resources}),/TEMPLATE_ARTIFACT_CONTEXT_REQUIRED/)
  writeFileSync(path.join(f.upstreamPackageRoot,'dist/agent.js'),'changed\n')
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_UPSTREAM_DRIFT/)
  rmSync(path.join(f.upstreamPackageRoot,'dist/agent.js'))
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_INPUT_MISSING/)
})
test('wrong locked package version and member symlink fail closed', t => {
  const f = fixture(t)
  writeFileSync(path.join(f.upstreamPackageRoot,'package.json'),JSON.stringify({name:'controlled-upstream',version:'2.0.0'}))
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_LOCK_MISMATCH/)
  writeFileSync(path.join(f.upstreamPackageRoot,'package.json'),JSON.stringify({name:'controlled-upstream',version:'1.0.0'}))
  const member = path.join(f.upstreamPackageRoot,'dist/agent.js')
  rmSync(member); symlinkSync(f.source,member)
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_INPUT_INVALID/)
})
test('unknown source import and unused declaration remain refusals before emission', t => {
  const f = fixture(t)
  writeFileSync(f.source,"import './agent.js'; import './undeclared.js'\n")
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_EDGE_UNDECLARED/)
  assert.equal(existsSync(path.join(f.upstreamPackageRoot,'dist/entry.mjs')),false)
  writeFileSync(f.source,"export { helper } from './helper.mjs'\n")
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_EDGE_UNUSED/)
})
test('nonliteral imports do not acquire an artifact-context allowance', t => {
  const f = fixture(t)
  writeFileSync(f.source,"import './agent.js'; await import(selected)\n")
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_EDGE_DYNAMIC/)
})
test('emission relocation, escape and upstream output collision are refused', t => {
  const f = fixture(t)
  f.declaration.edges[0].emitted_module='wrong/entry.mjs';f.save()
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_EMISSION_MISMATCH/)
  f.declaration.edges[0].emitted_module='dist/entry.mjs'
  f.declaration.edges[0].source='../../outside.mjs';f.save()
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_PATH_INVALID/)
  f.declaration.edges[0].source='../src/entry.mjs';f.save()
  f.resources['agent.js']=path.join(f.upstreamPackageRoot,'dist/agent.js')
  assert.throws(f.capture,/TEMPLATE_ARTIFACT_OUTPUT_COLLISION/)
})
test('only explicitly declared transformed members can verify enhanced emission', t => {
  const f = fixture(t), captured=f.capture(), destination=path.join(f.upstreamPackageRoot,'dist')
  stageTemplateGraph(destination,f.resources)
  const enhanced='export const agent = 3\n'
  writeFileSync(path.join(destination,'agent.js'),enhanced)
  assert.throws(() => verifyTemplateArtifactEmission(destination,captured),/TEMPLATE_ARTIFACT_EMISSION_DRIFT/)
  assert.equal(verifyTemplateArtifactEmission(destination,captured,{transformedMembers:{'dist/agent.js':sha256(enhanced)}}).edges,1)
  assert.throws(() => verifyTemplateArtifactEmission(destination,captured,{transformedMembers:{'dist/other.js':sha256(enhanced)}}),/TEMPLATE_ARTIFACT_TRANSFORM_INVALID/)
})
test('scanner records verified artifact evidence without removing any source imports', async t => {
  const f=fixture(t)
  const ordinary=await scanDependencyBoundaries(f.root)
  assert.ok(ordinary.filesScanned >= 2)
  assert.ok(ordinary.importsScanned > 0)
  assert.equal(ordinary.errors.some(error => error.kind==='missing-scan-root'),false)
  assert.equal(ordinary.errors.filter(error => error.kind==='unresolved-local-resource').length,1)
  const captured=await scanDependencyBoundaries(f.root,{templateArtifactContexts:[f.input]})
  assert.equal(captured.status,'PASS_BOUNDED')
  assert.equal(captured.importsScanned,ordinary.importsScanned)
  assert.equal(captured.artifactEdges.length,1)
  assert.equal(captured.artifactEdges[0].sha256,f.declaration.edges[0].sha256)
  writeFileSync(f.source,"import './agent.js'; import './unregistered.js'\n")
  const refused=await scanDependencyBoundaries(f.root,{templateArtifactContexts:[f.input]})
  assert.equal(refused.status,'FAIL')
  assert.ok(refused.errors.some(error => error.kind==='invalid-template-artifact-context'))
  assert.ok(refused.errors.some(error => error.kind==='unresolved-local-resource' && error.specifier==='./unregistered.js'))
})

test('an unknown edge under an actual package source root never acquires a context allowance', async t => {
  const f=fixture(t)
  writeFileSync(f.source,"import './unregistered.js'\n")
  const ordinary=await scanDependencyBoundaries(f.root)
  assert.equal(ordinary.status,'FAIL')
  assert.equal(ordinary.importsScanned,1)
  assert.ok(ordinary.errors.some(error => error.kind==='unresolved-local-resource' && error.specifier==='./unregistered.js'))
  const captured=await scanDependencyBoundaries(f.root,{templateArtifactContexts:[f.input]})
  assert.equal(captured.status,'FAIL')
  assert.equal(captured.importsScanned,ordinary.importsScanned)
  assert.equal(captured.artifactEdges.length,0)
  assert.ok(captured.errors.some(error => error.kind==='invalid-template-artifact-context'))
  assert.ok(captured.errors.some(error => error.kind==='unresolved-local-resource' && error.specifier==='./unregistered.js'))
})
