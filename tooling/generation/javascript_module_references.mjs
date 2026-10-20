/** Existing TypeScript syntax traversal, shared by source and artifact checks. */
import path from 'node:path'
export function moduleReferenceParser(ts) {
function scriptKind(filePath) {
  switch (path.extname(filePath)) {
    case '.tsx': case '.jsx': return ts.ScriptKind.TSX
    case '.js': case '.mjs': case '.cjs': return ts.ScriptKind.JS
    default: return ts.ScriptKind.TS
  }
}

function literalText(node) {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text
  return undefined
}

function lineAt(sourceFile, node) {
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1
}

function collectSpecifiers(sourceFile, filePath, unresolvedDynamic) {
  const references = []
  function add(node, kind) {
    const specifier = literalText(node)
    if (specifier !== undefined) references.push({ specifier, kind, line: lineAt(sourceFile, node) })
    else unresolvedDynamic.push({
      file: filePath,
      line: lineAt(sourceFile, node),
      kind: `non-literal-${kind}`,
      expression: node.getText(sourceFile),
    })
  }

  function visit(node) {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      add(node.moduleSpecifier, ts.isImportDeclaration(node) ? 'import' : 'export')
    } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference) && node.moduleReference.expression) {
      add(node.moduleReference.expression, 'require')
    } else if (ts.isImportTypeNode(node)) {
      const arg = node.argument
      if (ts.isLiteralTypeNode(arg)) add(arg.literal, 'import-type')
      else add(arg, 'import-type')
    } else if (ts.isCallExpression(node) && node.arguments.length) {
      const [arg] = node.arguments
      if (node.expression.kind === ts.SyntaxKind.ImportKeyword) add(arg, 'dynamic-import')
      else if (ts.isIdentifier(node.expression) && node.expression.text === 'require') add(arg, 'require')
    }
    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return references
}

return { scriptKind, collectSpecifiers }
}
