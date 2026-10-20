import { copyFileSync, mkdirSync, readFileSync } from 'node:fs'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

// V8 parses module dependencies without linking or evaluating the module. A quoted
// import in generated source is data and must not become a build-time dependency.
function moduleDependencies(text) {
  return JSON.parse(execFileSync(process.execPath, [
    '--experimental-vm-modules', '--input-type=module', '-e',
    "import { SourceTextModule } from 'node:vm'; import { readFileSync } from 'node:fs'; process.stdout.write(JSON.stringify(new SourceTextModule(readFileSync(0,'utf8')).dependencySpecifiers));",
  ], {input:text,encoding:'utf8',stdio:['pipe','pipe','pipe']}))
}
export function stageBuilderModuleClosure(sourceRoot,builder,destinationRoot) {
 const copied=new Set()
 const inspected=new Set()
 const visit=(source,executable=true) => {
  source=path.resolve(source)
  const relative=path.relative(sourceRoot,source)
  if(relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Builder source escaped explicit root')
  if(!copied.has(source)) {
   copied.add(source)
   const target=path.join(destinationRoot,relative)
   mkdirSync(path.dirname(target),{recursive:true});copyFileSync(source,target)
  }
  if(!executable || inspected.has(source) || !/\.(?:mjs|js)$/u.test(source)) return
  inspected.add(source)
  const text=readFileSync(source,'utf8')
  for(const specifier of moduleDependencies(text)) {
   if(specifier.startsWith('.')) visit(path.resolve(path.dirname(source),specifier))
  }
  // Explicit new-URL inputs are files read by the builder, not modules executed
  // during builder import. Their artifact imports belong to the staging graph.
  for(const match of text.matchAll(/new URL\(\s*(["'])(\.[^"']+)\1\s*,\s*import\.meta\.url\s*\)/gu)) {
   const edge=path.resolve(path.dirname(source),match[2])
   if(/\.(?:mjs|js|json|md|LICENSE|NOTICE)$/u.test(edge)) visit(edge,false)
  }
 }
 visit(builder)
 return path.join(destinationRoot,path.relative(sourceRoot,builder))
}
