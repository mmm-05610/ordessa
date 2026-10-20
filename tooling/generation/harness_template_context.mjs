import { createHash } from 'node:crypto'
import { lstatSync, readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { compileTemplateGraph } from './harness_template_graph.mjs'
import { moduleReferenceParser } from './javascript_module_references.mjs'
const require = createRequire(import.meta.url)
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex')
function refuse(reason) { throw new TypeError(reason) }
function record(value, keys, required = keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some(key => !keys.includes(key))
    || required.some(key => !Object.hasOwn(value,key))) refuse('TEMPLATE_ARTIFACT_SCHEMA_INVALID')
}
function portable(value) {
  if (typeof value !== 'string' || !value.length || value.includes('\\') || value.startsWith('/')
    || value.split('/').some(part => !part || part === '.' || part === '..')) refuse('TEMPLATE_ARTIFACT_PATH_INVALID')
  return value
}
function absolute(value) {
  if (typeof value !== 'string' || !path.isAbsolute(value)) refuse('TEMPLATE_ARTIFACT_CONTEXT_REQUIRED')
  return path.resolve(value)
}
function statInput(file) {
  try { return lstatSync(file) } catch { refuse('TEMPLATE_ARTIFACT_INPUT_MISSING') }
}
function memberFile(root, member) {
  const parts = portable(member).split('/')
  let file = root
  if (!statInput(root).isDirectory() || statInput(root).isSymbolicLink()) refuse('TEMPLATE_ARTIFACT_INPUT_INVALID')
  for (const [index,part] of parts.entries()) {
    file = path.join(file,part)
    const stat = statInput(file)
    if (stat.isSymbolicLink() || (index === parts.length-1 ? !stat.isFile() : !stat.isDirectory())) refuse('TEMPLATE_ARTIFACT_INPUT_INVALID')
  }
  return file
}
function declaredFile(directory, relative) {
  if (typeof relative !== 'string' || !relative.length || path.isAbsolute(relative) || relative.includes('\\')) refuse('TEMPLATE_ARTIFACT_PATH_INVALID')
  const file = path.resolve(directory,relative)
  // A declaration lives in its own Tooling directory. Its own source and pin
  // resources may be siblings, never arbitrary repository or host locations.
  const ownerRoot = path.resolve(directory,'..')
  const rel = path.relative(ownerRoot,file)
  if (rel.startsWith('..') || path.isAbsolute(rel)) refuse('TEMPLATE_ARTIFACT_PATH_INVALID')
  return memberFile(ownerRoot, rel.split(path.sep).join('/'))
}
function expectedDigest(edge,directory) {
  if (Object.hasOwn(edge,'sha256') === Object.hasOwn(edge,'sha256_from')) refuse('TEMPLATE_ARTIFACT_SCHEMA_INVALID')
  let digest = edge.sha256
  if (edge.sha256_from) {
    record(edge.sha256_from,['file','pointer'])
    const {file,pointer} = edge.sha256_from
    if (typeof pointer !== 'string' || !/^\/(?:[A-Za-z0-9_-]+\/)*[A-Za-z0-9_-]+$/u.test(pointer)) refuse('TEMPLATE_ARTIFACT_SCHEMA_INVALID')
    digest = JSON.parse(readFileSync(declaredFile(directory,file),'utf8'))
    for (const segment of pointer.slice(1).split('/')) digest = digest?.[segment]
  }
  if (typeof digest !== 'string' || !/^[a-f0-9]{64}$/u.test(digest)) refuse('TEMPLATE_ARTIFACT_SCHEMA_INVALID')
  return digest
}
/** All inputs are explicit. No npm, checkout, environment, or cache discovery. */
export function captureTemplateArtifactContext(declarationFile, {resources,upstreamPackageRoot,typescript} = {}) {
  declarationFile = absolute(declarationFile)
  upstreamPackageRoot = absolute(upstreamPackageRoot)
  const directory = path.dirname(declarationFile)
  const declaration = JSON.parse(readFileSync(declarationFile,'utf8'))
  record(declaration,['schema_version','owner_id','package_name','package_lock','output_directory','edges'])
  if (declaration.schema_version !== 1 || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(declaration.owner_id)
    || !/^(?:@[a-z0-9._-]+\/)?[a-z0-9._-]+$/u.test(declaration.package_name)
    || !Array.isArray(declaration.edges) || !declaration.edges.length) refuse('TEMPLATE_ARTIFACT_SCHEMA_INVALID')
  portable(declaration.output_directory)
  const lock = JSON.parse(readFileSync(declaredFile(directory,declaration.package_lock),'utf8'))
  const locked = lock.packages?.['node_modules/'+declaration.package_name]
  const upstream = JSON.parse(readFileSync(memberFile(upstreamPackageRoot,'package.json'),'utf8'))
  if (!locked || typeof locked.version !== 'string' || typeof locked.integrity !== 'string'
    || !/^sha512-[A-Za-z0-9+/]+={0,2}$/u.test(locked.integrity) || upstream.name !== declaration.package_name
    || upstream.version !== locked.version) refuse('TEMPLATE_ARTIFACT_LOCK_MISMATCH')
  if (!resources || typeof resources !== 'object' || Array.isArray(resources)) refuse('TEMPLATE_ARTIFACT_CONTEXT_REQUIRED')
  const graph = compileTemplateGraph(resources)
  const outputs = new Map(graph.files.map(file => [file.source,file.name]))
  const sourceFiles = new Map(graph.files.map(file => [file.source,file]))
  const declared = new Map()
  const capturedEdges = []
  for (const edge of declaration.edges) {
    record(edge,['source','emitted_module','specifier','upstream_member','sha256','sha256_from'],['source','emitted_module','specifier','upstream_member'])
    const source = declaredFile(directory,edge.source)
    const emittedModule = portable(edge.emitted_module)
    const upstreamMember = portable(edge.upstream_member)
    if (typeof edge.specifier !== 'string' || !edge.specifier.startsWith('./') || edge.specifier.includes('\\')) refuse('TEMPLATE_ARTIFACT_PATH_INVALID')
    if (path.posix.normalize(path.posix.join(path.posix.dirname(emittedModule),edge.specifier)) !== upstreamMember
      || path.posix.dirname(emittedModule) !== declaration.output_directory
      || path.posix.dirname(upstreamMember) !== declaration.output_directory
      || outputs.get(source) !== path.posix.basename(emittedModule)) refuse('TEMPLATE_ARTIFACT_EMISSION_MISMATCH')
    const digest = expectedDigest(edge,directory)
    if (graph.files.some(file => file.name === path.posix.basename(upstreamMember))) refuse('TEMPLATE_ARTIFACT_OUTPUT_COLLISION')
    const upstreamFile = memberFile(upstreamPackageRoot,upstreamMember)
    if (sha256(readFileSync(upstreamFile)) !== digest) refuse('TEMPLATE_ARTIFACT_UPSTREAM_DRIFT')
    const key = source+'\0'+edge.specifier
    if (declared.has(key)) refuse('TEMPLATE_ARTIFACT_CONTEXT_DUPLICATE')
    const captured = Object.freeze({source,sourceSha256:sha256(sourceFiles.get(source).sourceContent),specifier:edge.specifier,emittedModule,upstreamMember,upstreamFile,sha256:digest,
      ownerId:declaration.owner_id,packageName:upstream.name,packageVersion:upstream.version,lockIntegrity:locked.integrity})
    declared.set(key,captured)
    capturedEdges.push(captured)
  }
  // Existing Tooling dependency is used only during preparation. Importing a
  // builder/treeSummary still has no parser-package or artifact-input effects.
  const ts = typescript ?? require('typescript')
  const {collectSpecifiers,scriptKind} = moduleReferenceParser(ts)
  const observed = new Set()
  for (const file of graph.files) {
    if (!/\.(?:mjs|js)$/u.test(file.name)) continue
    const text = file.sourceContent
    const ast = ts.createSourceFile(file.source,text,ts.ScriptTarget.Latest,true,scriptKind(file.source))
    if (ast.parseDiagnostics?.length) refuse('TEMPLATE_ARTIFACT_SOURCE_INVALID')
    const unresolved = []
    for (const reference of collectSpecifiers(ast,file.source,unresolved)) {
      if (path.isAbsolute(reference.specifier) || reference.specifier.startsWith('#')) refuse('TEMPLATE_ARTIFACT_EDGE_UNDECLARED')
      if (!reference.specifier.startsWith('.')) continue
      const target = path.resolve(path.dirname(file.source),reference.specifier)
      if (outputs.has(target)) continue
      const key = file.source+'\0'+reference.specifier
      if (!declared.has(key)) refuse('TEMPLATE_ARTIFACT_EDGE_UNDECLARED')
      observed.add(key)
    }
    if (unresolved.length) refuse('TEMPLATE_ARTIFACT_EDGE_DYNAMIC')
  }
  if (observed.size !== declared.size) refuse('TEMPLATE_ARTIFACT_EDGE_UNUSED')
  return Object.freeze({declarationFile,upstreamPackageRoot,outputDirectory:declaration.output_directory,
    edges:Object.freeze(capturedEdges),files:Object.freeze(graph.files.map(file => Object.freeze({name:file.name,sha256:sha256(file.content)})))})
}
/** Verify the actual new staging tree, including explicitly enhanced members. */
export function verifyTemplateArtifactEmission(destination, captured, {transformedMembers = {}} = {}) {
  destination = absolute(destination)
  const expected = path.join(captured.upstreamPackageRoot,...captured.outputDirectory.split('/'))
  if (destination !== expected) refuse('TEMPLATE_ARTIFACT_EMISSION_MISMATCH')
  for (const file of captured.files) {
    if (sha256(readFileSync(memberFile(destination,file.name))) !== file.sha256) refuse('TEMPLATE_ARTIFACT_EMISSION_DRIFT')
  }
  const allowed = new Set(captured.edges.map(edge => edge.upstreamMember))
  for (const [member,digest] of Object.entries(transformedMembers)) {
    if (!allowed.has(member) || !/^[a-f0-9]{64}$/u.test(digest)) refuse('TEMPLATE_ARTIFACT_TRANSFORM_INVALID')
  }
  for (const edge of captured.edges) {
    const digest = transformedMembers[edge.upstreamMember] ?? edge.sha256
    if (sha256(readFileSync(memberFile(captured.upstreamPackageRoot,edge.upstreamMember))) !== digest) refuse('TEMPLATE_ARTIFACT_EMISSION_DRIFT')
  }
  return Object.freeze({declarationFile:captured.declarationFile,edges:captured.edges.length,files:captured.files.length})
}
