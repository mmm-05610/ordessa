import { lstat, readdir, readFile, realpath, stat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createHash } from 'node:crypto'
import { moduleReferenceParser } from '../generation/javascript_module_references.mjs'
import { captureTemplateArtifactContext } from '../generation/harness_template_context.mjs'
const { scriptKind, collectSpecifiers } = moduleReferenceParser(ts)

const repoRoot = path.resolve(import.meta.dirname, '../..')
const defaultPolicyPath = path.join(import.meta.dirname, 'package-boundaries.json')
const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx', '.mts', '.cts', '.js', '.jsx', '.mjs', '.cjs'])
const SKIP_DIRS = new Set(['.git', 'node_modules', 'dist', 'build', 'coverage', 'design-source', 'worktree'])
const DEFAULT_OPTIONS = {
  allowJs: true,
  module: ts.ModuleKind.ESNext,
  moduleResolution: ts.ModuleResolutionKind.Bundler,
  noEmit: true,
  resolveJsonModule: true,
  jsx: ts.JsxEmit.Preserve,
  target: ts.ScriptTarget.Latest,
}

function globRegExp(pattern) {
  const source = pattern
    .replace(/[.+^${}()|[\]\\]/g, '\\$&')
    .replace(/\*\*/g, '\u0001')
    .replace(/\*/g, '[^/]*')
    .replace(/\u0001/g, '.*')
  return new RegExp(`^${source}$`)
}

function matchesWorkspace(rel, patterns) {
  let included = false
  for (const pattern of patterns) {
    const excluded = pattern.startsWith('!')
    if (globRegExp(excluded ? pattern.slice(1) : pattern).test(rel)) included = !excluded
  }
  return included
}

async function loadPackagePolicy(policyPath, errors) {
  const policy = await readJson(policyPath, 'package boundary policy', errors)
  if (!policy) return undefined
  const strings = value => Array.isArray(value) && value.every(item => typeof item === 'string' && item.length > 0)
  const relativePattern = value => typeof value === 'string' && !path.isAbsolute(value) && !value.includes('\\') &&
    !value.split('/').some(part => !part || part === '..' || part === '.')
  const fields = new Set(['schema_version', 'standard', 'denied_edges', 'retired_paths', 'retired_python_modules', 'retired_distributions'])
  if (policy.schema_version !== 1 || Object.keys(policy).some(key => !fields.has(key)) ||
      (Object.hasOwn(policy, 'standard') && (typeof policy.standard !== 'string' || !policy.standard.trim())) ||
      !Array.isArray(policy.denied_edges) || !policy.denied_edges.length ||
      !policy.denied_edges.every(edge => edge && typeof edge.rule === 'string' && edge.rule &&
        Object.keys(edge).length === 3 && strings(edge.from) && edge.from.length && edge.from.every(relativePattern) &&
        strings(edge.to) && edge.to.length && edge.to.every(relativePattern)) ||
      !strings(policy.retired_paths) || !policy.retired_paths.length || !policy.retired_paths.every(relativePattern) ||
      !strings(policy.retired_python_modules) || !policy.retired_python_modules.every(item => /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$/.test(item)) ||
      !strings(policy.retired_distributions) || !policy.retired_distributions.every(item => /^[a-z0-9][a-z0-9-]*$/.test(item.toLowerCase().replace(/[-_.]+/g, '-')))) {
    errors.push({ kind: 'invalid-package-boundary-policy', file: policyPath, message: 'Expected schema 1 with explicit denied edges and retired identities/relative paths' })
    return undefined
  }
  return policy
}

function packageRule(policy, source, target) {
  return policy?.denied_edges.find(edge => edge.from.some(pattern => globRegExp(pattern).test(source)) &&
    edge.to.some(pattern => globRegExp(pattern).test(target)))?.rule
}

function retiredIdentity(policy, name) {
  const key = name.toLowerCase().replace(/[-_.]+/g, '-')
  return policy?.retired_distributions.some(item => item.toLowerCase().replace(/[-_.]+/g, '-') === key)
}

function retiredSpecifier(policy, specifier) {
  return policy?.retired_python_modules.some(name => specifier === name || specifier.startsWith(name + '.') || specifier.startsWith(name + '/')) ||
    retiredIdentity(policy, specifier)
}

async function inspectRetiredPackagePaths(rootDir, policy, errors) {
  if (!policy) return
  const active = new Set([...SOURCE_EXTENSIONS, '.py', '.pyi', '.json', '.toml', '.yaml', '.yml', '.lock'])
  async function visit(file) {
    const info = await lstat(file)
    if (info.isSymbolicLink()) {
      errors.push({ kind: 'retired-package-content', file, message: 'Retired owner contains a symlink' })
    } else if (info.isDirectory()) {
      for (const entry of await readdir(file)) {
        if (!SKIP_DIRS.has(entry) && entry !== '__pycache__') await visit(path.join(file, entry))
      }
    } else if (info.isFile() && active.has(path.extname(file))) {
      errors.push({ kind: 'retired-package-content', file, message: 'Retired kernel/c1-api owner contains active source or metadata' })
    }
  }
  for (const relative of policy.retired_paths) {
    try {
      let componentPath = rootDir
      for (const component of relative.split('/')) {
        componentPath = path.join(componentPath, component)
        if ((await lstat(componentPath)).isSymbolicLink()) throw new Error('Retired owner path contains a linked component')
      }
      await visit(path.join(rootDir, relative))
    } catch (error) {
      if (error?.code !== 'ENOENT') errors.push({ kind: 'retired-package-path-invalid', file: relative, message: error.message })
    }
  }
}

async function isFile(filePath) {
  try { return (await stat(filePath)).isFile() } catch { return false }
}

async function packageManifestDirs(rootDir) {
  const found = []
  async function visit(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (!entry.isDirectory() || entry.name.startsWith('.') || SKIP_DIRS.has(entry.name)) continue
      const child = path.join(dir, entry.name)
      if (await isFile(path.join(child, 'package.json'))) found.push(child)
      await visit(child)
    }
  }
  await visit(rootDir)
  return found
}

async function readJson(filePath, label, errors) {
  try {
    return JSON.parse(await readFile(filePath, 'utf8'))
  } catch (error) {
    errors.push({ kind: 'invalid-json', file: filePath, message: `${label}: ${error.message}` })
    return undefined
  }
}

async function discoverWorkspaces(rootDir, errors) {
  const rootManifest = await readJson(path.join(rootDir, 'package.json'), 'root package.json', errors)
  if (!rootManifest) return new Map()
  const workspaces = Array.isArray(rootManifest.workspaces)
    ? rootManifest.workspaces
    : rootManifest.workspaces?.packages ?? []
  if (!Array.isArray(workspaces) || workspaces.some(pattern => typeof pattern !== 'string')) {
    errors.push({ kind: 'invalid-workspaces', file: path.join(rootDir, 'package.json'), message: 'workspaces must be an array of patterns' })
    return new Map()
  }

  const manifests = await packageManifestDirs(rootDir)
  const packages = new Map()
  for (const dir of manifests) {
    const rel = path.relative(rootDir, dir).split(path.sep).join('/')
    if (!matchesWorkspace(rel, workspaces)) continue
    const manifestPath = path.join(dir, 'package.json')
    const manifest = await readJson(manifestPath, 'workspace package.json', errors)
    if (!manifest) continue
    if (typeof manifest.name !== 'string' || !manifest.name) {
      errors.push({ kind: 'unnamed-workspace', file: manifestPath, message: `workspace ${rel} has no package name` })
      continue
    }
    const previous = packages.get(manifest.name)
    if (previous) {
      errors.push({ kind: 'duplicate-workspace-name', file: manifestPath, message: `${manifest.name} is also declared by ${previous.rel}` })
      continue
    }
    packages.set(manifest.name, { name: manifest.name, dir, rel, manifest })
  }
  return packages
}

const DEPENDENCY_SECTIONS = [
  'dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies',
]

function packageNameFromNpmAlias(specifier) {
  if (!specifier.startsWith('npm:')) return undefined
  const target = specifier.slice(4)
  if (!target) return null
  const separator = target.startsWith('@') ? target.indexOf('@', target.indexOf('/') + 1) : target.indexOf('@')
  const name = separator < 0 ? target : target.slice(0, separator)
  if (!/^(?:@[a-z0-9._-]+\/)?[a-z0-9._-]+$/i.test(name)) return null
  const version = separator < 0 ? '' : target.slice(separator + 1)
  return { name, version }
}

function workspaceDependencyTarget(name, range, workspaces) {
  const direct = workspaces.get(name)
  if (typeof range !== 'string') return { error: `workspace dependency ${name} must have a string specifier` }
  if (/^(?:file|link|portal|patch):/.test(range)) {
    return { error: `local or rewritten dependency protocol is outside the workspace resolver: ${range}` }
  }

  // npm aliases name the actual package in the specifier, not by the dependency key.
  // Resolve aliases to enumerated workspaces before treating a bare dependency as external.
  if (range.startsWith('npm:')) {
    const aliasedName = packageNameFromNpmAlias(range)
    if (aliasedName === null) return { error: `malformed npm dependency alias ${range}` }
    if (aliasedName !== undefined) {
      const aliased = workspaces.get(aliasedName.name)
      if (aliased) return { workspace: aliased }
      const localScope = [...workspaces.keys()].some(workspaceName => workspaceName.startsWith('@')
        && aliasedName.name.startsWith(`${workspaceName.split('/')[0]}/`))
      if (aliasedName.version.startsWith('workspace:') || localScope) {
        return { error: `npm alias ${name} targets missing workspace ${aliasedName.name}` }
      }
    }
    return {}
  }
  if (range.startsWith('workspace:') && !direct) {
    return { error: `workspace protocol dependency ${name} is not an enumerated workspace` }
  }
  return direct ? { workspace: direct } : {}
}

function validateWorkspaceDependencies(workspaces, errors, violations, policy) {
  for (const pkg of workspaces.values()) {
    const fromArea = pkg.rel.split('/')[0]
    if (retiredIdentity(policy, pkg.name)) {
      violations.push({ kind: 'retired-package-identity', file: path.join(pkg.rel, 'package.json'), dependency: pkg.name })
    }
    for (const section of DEPENDENCY_SECTIONS) {
      if (!Object.hasOwn(pkg.manifest, section)) continue
      const dependencies = pkg.manifest[section]
      if (!dependencies || typeof dependencies !== 'object' || Array.isArray(dependencies)) {
        errors.push({ kind: 'invalid-workspace-dependencies', file: path.join(pkg.rel, 'package.json'), section,
          message: `${section} must be an object mapping package names to string specifiers` })
        continue
      }
      for (const [name, range] of Object.entries(dependencies)) {
        if (typeof range !== 'string' || !range.trim()) {
          errors.push({ kind: 'invalid-workspace-dependency-specifier', file: path.join(pkg.rel, 'package.json'), section, dependency: name,
            message: `${section}.${name} must be a non-empty string` })
          continue
        }
        const alias = packageNameFromNpmAlias(range)
        if (retiredIdentity(policy, name) || (alias && retiredIdentity(policy, alias.name))) {
          violations.push({ kind: 'retired-package-dependency', file: path.join(pkg.rel, 'package.json'), section, dependency: name, specifier: range })
        }
        const resolved = workspaceDependencyTarget(name, range, workspaces)
        if (resolved.error) {
          errors.push({ kind: 'unresolved-workspace-dependency', file: path.join(pkg.rel, 'package.json'), section,
            dependency: name, specifier: range, message: resolved.error })
          continue
        }
        const target = resolved.workspace
        if (!target) continue
        const toArea = target.rel.split('/')[0]
        const file = path.join(pkg.rel, 'package.json')
        const rule = packageRule(policy, file, path.join(target.rel, 'package.json').split(path.sep).join('/'))
        if (rule) violations.push({ kind: 'package-boundary-dependency', rule, file, section, dependency: name, specifier: range, target: target.rel })
        if ((fromArea === 'packages' || fromArea === 'plugins') && toArea === 'apps') {
          violations.push({ kind: 'workspace-depends-on-app', file, section, dependency: name, specifier: range, target: target.rel })
        } else if ((fromArea === 'packages' || fromArea === 'plugins') && toArea === 'products') {
          violations.push({ kind: 'workspace-depends-on-product', file, section, dependency: name, specifier: range, target: target.rel })
        } else if (fromArea === 'packages' && toArea === 'plugins') {
          violations.push({ kind: 'public-package-depends-on-plugin', file, section, dependency: name, specifier: range, target: target.rel })
        }
      }
    }
  }
}

async function sourceFiles(rootDir, errors) {
  const files = []
  const retiredProducts = path.join(rootDir, 'products')
  const activeSourceExtensions = new Set([...SOURCE_EXTENSIONS, '.py', '.pyi'])
  const activeMetadataExtensions = new Set(['.json', '.toml', '.yaml', '.yml', '.lock'])
  try {
    const retiredStat = await lstat(retiredProducts)
    if (retiredStat.isSymbolicLink() || !retiredStat.isDirectory()) {
      errors.push({ kind: 'retired-products-root-invalid', file: retiredProducts,
        message: 'retired products root must be an ordinary directory when present' })
    } else {
      async function inspectRetired(dir) {
        for (const entry of await readdir(dir, { withFileTypes: true })) {
          const target = path.join(dir, entry.name)
          if (entry.isSymbolicLink()) {
            errors.push({ kind: 'retired-products-active-content', file: target,
              message: 'retired products tree contains a symlink' })
          } else if (entry.isDirectory()) {
            await inspectRetired(target)
          } else if (entry.isFile() && (activeSourceExtensions.has(path.extname(entry.name)) ||
              activeMetadataExtensions.has(path.extname(entry.name)))) {
            errors.push({ kind: 'retired-products-active-content', file: target,
              message: 'retired products tree contains source or active project metadata' })
          }
        }
      }
      await inspectRetired(retiredProducts)
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') errors.push({ kind: 'retired-products-root-invalid', file: retiredProducts,
      message: error.message })
  }

  const defaultProduct = path.join(rootDir, 'apps/server/deployment/default-product')
  const defaultProductMetadata = path.join(defaultProduct, 'pyproject.toml')
  try {
    const productStat = await lstat(defaultProduct)
    if (productStat.isSymbolicLink() || !productStat.isDirectory()) {
      errors.push({ kind: 'missing-default-product-entry', file: defaultProduct,
        message: 'required default product directory is missing or linked' })
    } else {
      try {
        const metadataStat = await lstat(defaultProductMetadata)
        if (metadataStat.isSymbolicLink() || !metadataStat.isFile()) {
          errors.push({ kind: 'missing-default-product-entry', file: defaultProductMetadata,
            message: 'required default product metadata is missing or linked' })
        }
      } catch {
        errors.push({ kind: 'missing-default-product-entry', file: defaultProductMetadata,
          message: 'required default product metadata is missing or linked' })
      }
    }
  } catch {
    errors.push({ kind: 'missing-default-product-entry', file: defaultProduct,
      message: 'required default product directory is missing or linked' })
  }

  // products/ is retired. The live server product is an apps-owned deployment;
  // the desktop product is apps/desktop/packaging/product. Keep scanning every
  // active source owner and fail if a retired product source/manifest reappears.
  for (const rootName of ['packages', 'plugins', 'apps']) {
    const root = path.join(rootDir, rootName)
    try {
      const rootStat = await lstat(root)
      if (rootStat.isSymbolicLink() || !rootStat.isDirectory()) throw new Error('not an ordinary directory')
    } catch {
      errors.push({ kind: 'missing-scan-root', file: root, message: `required scan root ${rootName}/ is missing or linked` })
      continue
    }
    async function visit(dir) {
      for (const entry of await readdir(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
          if (!entry.name.startsWith('.') && !SKIP_DIRS.has(entry.name)) await visit(path.join(dir, entry.name))
        } else if (entry.isFile() && SOURCE_EXTENSIONS.has(path.extname(entry.name))) {
          files.push(path.join(dir, entry.name))
        }
      }
    }
    await visit(root)
  }
  return files.sort()
}

function exportTargets(exportsField, subpath, kind) {
  const substitute = value => value
  const selectConditions = value => {
    if (typeof value === 'string') return [substitute(value)]
    if (Array.isArray(value)) return value.flatMap(selectConditions)
    if (!value || typeof value !== 'object') return []
    const subpathMap = Object.keys(value).some(key => key.startsWith('.'))
    if (subpathMap) {
      if (Object.hasOwn(value, subpath)) return selectConditions(value[subpath])
      const patterns = Object.keys(value).filter(key => key.includes('*'))
        .map(key => ({ key, index: key.indexOf('*') }))
        .filter(({ key, index }) => subpath.startsWith(key.slice(0, index)) && subpath.endsWith(key.slice(index + 1)))
        .sort((a, b) => b.key.length - a.key.length)
      if (!patterns.length) return []
      const { key, index } = patterns[0]
      const capture = subpath.slice(index, subpath.length - key.length + index + 1)
      return selectConditions(value[key]).map(target => target.replaceAll('*', capture))
    }
    const conditionOrder = kind === 'require'
      ? ['types', 'require', 'node', 'default']
      : ['types', 'import', 'node', 'default']
    for (const condition of conditionOrder) if (Object.hasOwn(value, condition)) return selectConditions(value[condition])
    return []
  }

  if (exportsField && typeof exportsField === 'object' && !Array.isArray(exportsField) &&
      Object.keys(exportsField).some(key => key.startsWith('.'))) {
    return selectConditions(exportsField)
  }
  return subpath === '.' ? selectConditions(exportsField) : []
}

function extensionCandidates(target) {
  const ext = path.extname(target)
  const substitutions = {
    '.js': ['.ts', '.tsx', '.d.ts', '.js'],
    '.jsx': ['.tsx', '.jsx'],
    '.mjs': ['.mts', '.d.mts', '.mjs'],
    '.cjs': ['.cts', '.d.cts', '.cjs'],
  }
  if (substitutions[ext]) {
    const stem = target.slice(0, -ext.length)
    return substitutions[ext].map(candidateExt => `${stem}${candidateExt}`)
  }
  if (ext) return [target]
  return ['.ts', '.tsx', '.mts', '.cts', '.d.ts', '.js', '.jsx', '.mjs', '.cjs', '.json']
    .map(candidateExt => `${target}${candidateExt}`)
}

async function resolveTarget(target, packageDir) {
  if (!target.startsWith('./')) return undefined
  const absolute = path.resolve(packageDir, target)
  const relative = path.relative(packageDir, absolute)
  if (relative.startsWith('..') || path.isAbsolute(relative)) return undefined
  for (const candidate of extensionCandidates(absolute)) if (await isFile(candidate)) return candidate
  try {
    if ((await stat(absolute)).isDirectory()) {
      for (const index of ['index.ts', 'index.tsx', 'index.mts', 'index.cts', 'index.js', 'index.jsx', 'index.mjs', 'index.cjs', 'index.json']) {
        const candidate = path.join(absolute, index)
        if (await isFile(candidate)) return candidate
      }
    }
  } catch { /* missing target is reported by the caller */ }
  return undefined
}

function workspaceForSpecifier(specifier, workspaces) {
  return [...workspaces.values()]
    .filter(pkg => specifier === pkg.name || specifier.startsWith(`${pkg.name}/`))
    .sort((a, b) => b.name.length - a.name.length)[0]
}

async function resolveWorkspaceSpecifier(specifier, kind, workspaces) {
  const pkg = workspaceForSpecifier(specifier, workspaces)
  if (!pkg) return undefined
  const subpath = specifier === pkg.name ? '.' : `./${specifier.slice(pkg.name.length + 1)}`
  const exportsField = pkg.manifest.exports
  let targets
  if (exportsField !== undefined) {
    targets = exportTargets(exportsField, subpath, kind)
  } else if (subpath !== '.') {
    targets = [subpath]
  } else {
    targets = [pkg.manifest.types, pkg.manifest.typings, pkg.manifest.source, pkg.manifest.module, pkg.manifest.main, './index.ts', './src/index.ts']
      .filter(value => typeof value === 'string')
      .map(value => value.startsWith('./') ? value : `./${value}`)
  }
  for (const target of targets) {
    const resolved = await resolveTarget(target, pkg.dir)
    if (resolved) return { file: resolved, workspace: pkg }
  }
  return { workspace: pkg, error: `workspace export ${specifier} has no resolvable file target` }
}

function matchesPathAlias(specifier, compilerOptions) {
  for (const pattern of Object.keys(compilerOptions.paths ?? {})) {
    const escaped = pattern.split('*').map(piece => piece.replace(/[.+^${}()|[\]\\]/g, '\\$&')).join('.*')
    if (new RegExp(`^${escaped}$`).test(specifier)) return true
  }
  return false
}

function makeConfigReader(rootDir, errors) {
  const cache = new Map()
  return async filePath => {
    let dir = path.dirname(filePath)
    while (dir === rootDir || dir.startsWith(`${rootDir}${path.sep}`)) {
      const configPath = path.join(dir, 'tsconfig.json')
      if (await isFile(configPath)) {
        if (!cache.has(configPath)) {
          const read = ts.readConfigFile(configPath, ts.sys.readFile)
          if (read.error) {
            errors.push({ kind: 'invalid-tsconfig', file: configPath, message: ts.flattenDiagnosticMessageText(read.error.messageText, '\n') })
            cache.set(configPath, { ...DEFAULT_OPTIONS })
          } else {
            const parsed = ts.parseJsonConfigFileContent(read.config, ts.sys, dir, {}, configPath)
            for (const diagnostic of parsed.errors) {
              if (diagnostic.category === ts.DiagnosticCategory.Error) {
                errors.push({ kind: 'invalid-tsconfig', file: configPath, message: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n') })
              }
            }
            cache.set(configPath, { ...DEFAULT_OPTIONS, ...parsed.options, resolveJsonModule: true, allowJs: true })
          }
        }
        return cache.get(configPath)
      }
      const parent = path.dirname(dir)
      if (parent === dir) break
      dir = parent
    }
    return DEFAULT_OPTIONS
  }
}

async function resolveLocalSpecifier(specifier, filePath, options) {
  const resolved = ts.resolveModuleName(specifier, filePath, options, ts.sys).resolvedModule
  if (!resolved) {
    // CSS is an actual bundler resource: keep its edge in the same ownership checks.
    if (isRelativeSpecifier(specifier) && path.extname(specifier) === '.css') {
      const resource = path.resolve(path.dirname(filePath), specifier)
      if (await isFile(resource)) return await realpath(resource)
    }
    return undefined
  }
  let file = resolved.resolvedFileName
  try { file = await realpath(file) } catch { /* retain TypeScript's resolved path */ }
  return file
}

function classifyPath(filePath, rootDir) {
  const relative = path.relative(rootDir, filePath).split(path.sep).join('/')
  const area = relative.split('/')[0]
  return { relative, area }
}

function isRelativeSpecifier(specifier) {
  return specifier.startsWith('./') || specifier.startsWith('../') || path.isAbsolute(specifier)
}

function pathAliasMatch(specifier, options) {
  return matchesPathAlias(specifier, options)
}

function sourceDiagnostic(sourceFile, diagnostic) {
  const position = diagnostic.start ?? 0
  const line = sourceFile.getLineAndCharacterOfPosition(position).line + 1
  return {
    kind: 'syntax-error',
    file: sourceFile.fileName,
    line,
    message: ts.flattenDiagnosticMessageText(diagnostic.messageText, '\n'),
  }
}

export async function scanDependencyBoundaries(rootDir = repoRoot, { templateArtifactContexts = [], policyPath = defaultPolicyPath } = {}) {
  rootDir = path.resolve(rootDir)
  const errors = []
  const violations = []
  const unresolvedDynamic = []
  const policy = await loadPackagePolicy(policyPath, errors)
  await inspectRetiredPackagePaths(rootDir, policy, errors)
  const workspaces = await discoverWorkspaces(rootDir, errors)
  const files = await sourceFiles(rootDir, errors)
  validateWorkspaceDependencies(workspaces, errors, violations, policy)
  const readOptions = makeConfigReader(rootDir, errors)
  let importsScanned = 0
  const artifactEdges = []
  const artifactBySourceEdge = new Map()
  for (const input of templateArtifactContexts) {
    try {
      const captured = captureTemplateArtifactContext(input.declarationFile, {
        resources: input.resources, upstreamPackageRoot: input.upstreamPackageRoot, typescript: ts,
      })
      for (const edge of captured.edges) {
        const key = edge.source + '\0' + edge.specifier
        if (artifactBySourceEdge.has(key)) throw new TypeError('TEMPLATE_ARTIFACT_CONTEXT_DUPLICATE')
        artifactBySourceEdge.set(key, edge)
      }
    } catch (error) {
      errors.push({kind:'invalid-template-artifact-context', file:input.declarationFile, message:error.message})
    }
  }

  for (const filePath of files) {
    let sourceText
    try { sourceText = await readFile(filePath, 'utf8') } catch (error) {
      errors.push({ kind: 'unreadable-source', file: filePath, message: error.message })
      continue
    }
    const sourceFile = ts.createSourceFile(filePath, sourceText, ts.ScriptTarget.Latest, true, scriptKind(filePath))
    // Parse declarations directly: transpileModule emits JavaScript and throws
    // for .d.ts inputs. Every declaration still participates in import checks.
    const syntax = [...(sourceFile.parseDiagnostics ?? [])]
    if (!sourceFile.isDeclarationFile) {
      try {
        syntax.push(...(ts.transpileModule(sourceText, {
          fileName: filePath,
          reportDiagnostics: true,
          compilerOptions: { allowJs: true, jsx: ts.JsxEmit.Preserve, target: ts.ScriptTarget.Latest },
        }).diagnostics ?? []))
      } catch (error) {
        errors.push({ kind: 'compiler-failure', file: filePath, message: error.message })
      }
    }
    for (const diagnostic of syntax) if (diagnostic.category === ts.DiagnosticCategory.Error) errors.push(sourceDiagnostic(sourceFile, diagnostic))

    const references = collectSpecifiers(sourceFile, filePath, unresolvedDynamic)
    const from = classifyPath(filePath, rootDir)
    const options = await readOptions(filePath)
    for (const reference of references) {
      importsScanned += 1
      if (retiredSpecifier(policy, reference.specifier)) {
        violations.push({ kind: 'retired-package-import', file: from.relative, line: reference.line, specifier: reference.specifier })
      }
      let targetPath
      const workspace = await resolveWorkspaceSpecifier(reference.specifier, reference.kind, workspaces)
      if (workspace?.error) {
        errors.push({ kind: 'unresolved-workspace-resource', file: filePath, line: reference.line, specifier: reference.specifier, message: workspace.error })
        continue
      }
      if (workspace?.file) targetPath = workspace.file
      else targetPath = await resolveLocalSpecifier(reference.specifier, filePath, options)

      if (!targetPath) {
        const artifact = artifactBySourceEdge.get(filePath + '\0' + reference.specifier)
        if (artifact) {
          if (createHash('sha256').update(sourceText).digest('hex') !== artifact.sourceSha256) {
            errors.push({kind:'template-artifact-source-drift',file:filePath,line:reference.line,specifier:reference.specifier,message:'Source changed after explicit artifact capture'})
            continue
          }
          artifactEdges.push({...artifact,line:reference.line,kind:reference.kind})
          continue
        }
        const sameWorkspaceScope = [...workspaces.values()].some(pkg => pkg.name.startsWith('@') && reference.specifier.startsWith(`${pkg.name.split('/')[0]}/`))
        if (isRelativeSpecifier(reference.specifier) || reference.specifier.startsWith('#') || pathAliasMatch(reference.specifier, options) || sameWorkspaceScope) {
          errors.push({ kind: 'unresolved-local-resource', file: filePath, line: reference.line, specifier: reference.specifier, message: 'local path/workspace import could not be resolved' })
        }
        continue
      }

      const to = classifyPath(targetPath, rootDir)
      const rule = packageRule(policy, from.relative, to.relative)
      if (rule) violations.push({ kind: 'package-boundary-import', rule, file: from.relative, line: reference.line, specifier: reference.specifier, target: to.relative })
      if ((from.area === 'packages' || from.area === 'plugins') && (to.area === 'apps' || to.area === 'products')) {
        violations.push({ kind: 'lower-layer-imports-app', file: from.relative, line: reference.line, specifier: reference.specifier, target: to.relative })
      }
      if (from.area === 'packages' && to.area === 'plugins') {
        violations.push({ kind: 'public-package-imports-plugin', file: from.relative, line: reference.line, specifier: reference.specifier, target: to.relative })
      }
    }
  }

  const limitations = [
    'Non-literal dynamic import/require targets are listed as unresolvedDynamic; runtime-selected edges are not statically classified.',
    'External dependency bodies and their transitive imports are outside the scan; unresolved bare non-workspace imports are treated as external.',
    'TypeScript config paths and compiler resolution are used; workspace exports fallback supports exact/subpath wildcard targets and types/import/require/node/default conditions. typesVersions, arbitrary custom conditions, and runtime/bundler plugin resolvers are not fully modeled; unresolved local workspace targets fail closed. Manifest dependency checks resolve direct workspace names and npm aliases whose target names match an enumerated workspace; file/link/portal/patch protocols fail closed because their content targets are not modeled.',
    'This is a bounded source-import check, not an isolated build, emitted-package audit, or complete runtime dependency proof.',
  ]
  const status = errors.length || violations.length ? 'FAIL' : unresolvedDynamic.length ? 'PARTIAL' : 'PASS_BOUNDED'
  return { status, rootDir, filesScanned: files.length, importsScanned, errors, violations, unresolvedDynamic, artifactEdges, limitations }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2)
  let templateArtifactContexts = []
  if (args.length) {
    if (args.length !== 2 || args[0] !== '--template-artifact-contexts' || !path.isAbsolute(args[1]))
      throw new TypeError('Explicit absolute template artifact input file required')
    templateArtifactContexts = JSON.parse(await readFile(args[1],'utf8'))
    if (!Array.isArray(templateArtifactContexts)) throw new TypeError('Template artifact inputs must be an array')
  }
  const report = await scanDependencyBoundaries(repoRoot,{templateArtifactContexts})
  console.log(JSON.stringify(report, null, 2))
  if (report.status !== 'PASS_BOUNDED') process.exitCode = 1
}
