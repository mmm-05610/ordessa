import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
export function compileTemplateGraph(resources) {
  const sourceToOutput = new Map(Object.entries(resources).map(([name,source]) => [path.resolve(source),name]))
  const rewrites = []
  const files = []
  for (const [name,source] of Object.entries(resources)) {
    if (!name || path.basename(name) !== name) throw new TypeError('Invalid explicit staged template name')
    let content = readFileSync(source, 'utf8')
    const sourceContent = content
    // Only known explicit graph edges change. Upstream package imports remain native.
    content = content.replace(/(['"])(\.[^'"\n]+)\1/gu, (whole,quote,specifier) => {
      const output = sourceToOutput.get(path.resolve(path.dirname(source),specifier))
      if (output) rewrites.push(Object.freeze({name,from:specifier,to:'./'+output}))
      return output ? quote + './' + output + quote : whole
    })
    files.push(Object.freeze({name,source:path.resolve(source),sourceContent,content}))
  }
  return Object.freeze({files:Object.freeze(files),rewrites:Object.freeze(rewrites)})
}
export function stageTemplateGraph(destination, resources) {
  const graph = compileTemplateGraph(resources)
  for (const {name,content} of graph.files) writeFileSync(path.join(destination,name),content)
  return graph.rewrites
}
