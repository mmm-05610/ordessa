// PA-02 / PC-05：版本号**单一来源** = `apps/desktop/package.json`；构建号在构建期注入，
// 产出 `dist/build-info.json`，关于面板、主进程、诊断 meta.json、发行清单四处都只读它
// （四处相等是 C-09 §A4 的要求，不允许各写一份）。
//
// 第三方许可证入口（PA-04 / PC-06）：构建期从工作区各包的 package.json 聚合 license 声明，
// 应用自身许可证全文随产物走；P-C 再把它聚合到 /opt/ordessa/licenses/。
import { mkdir, readFile, readdir, writeFile, copyFile } from 'node:fs/promises'
import path from 'node:path'

/** 版本号的唯一来源。构建号：CI 注入 ORDESSA_BUILD_NUMBER，本地回落为可读的 dev 标记。 */
export function buildInfo(pkg, { buildNumber, builtAt } = {}) {
  const build = buildNumber ?? process.env.ORDESSA_BUILD_NUMBER ?? `${pkg.version}-local`
  return {
    name: pkg.name,
    productName: pkg.productName ?? pkg.name,
    version: pkg.version,
    build,
    description: pkg.description ?? '',
    author: typeof pkg.author === 'string' ? pkg.author : pkg.author?.name ?? '',
    license: typeof pkg.license === 'string' ? pkg.license : 'UNLICENSED',
    homepage: pkg.homepage ?? '',
    repository: typeof pkg.repository === 'string' ? pkg.repository : pkg.repository?.url ?? '',
    builtAt: builtAt ?? new Date().toISOString(),
  }
}

/** 校验：注入信息必须自洽（版本号格式、构建号非空、四处相等的前提是同一对象）。 */
export function assertBuildInfo(info) {
  if (!/^\d+\.\d+\.\d+$/.test(info.version)) throw Error(`Invalid app version: ${info.version}`)
  if (!info.build) throw Error('Build number must not be empty')
  for (const field of ['name', 'productName', 'description', 'author', 'license', 'homepage', 'repository']) {
    if (typeof info[field] !== 'string') throw Error(`Product metadata field is not a string: ${field}`)
  }
  return info
}

async function packageDirs(root, acc = []) {
  for (const entry of await readdir(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === 'node_modules' || entry.name === 'dist' || entry.name.startsWith('.')) continue
    const dir = path.join(root, entry.name)
    if (await readFile(path.join(dir, 'package.json'), 'utf8').then(() => true, () => false)) acc.push(dir)
    await packageDirs(dir, acc)
  }
  return acc
}

/** 聚合工作区包的许可证声明（PA-04 第三方许可证入口的数据源）。 */
export async function collectLicenses(repoRoot, selfName) {
  const root = JSON.parse(await readFile(path.join(repoRoot, 'package.json'), 'utf8'))
  const patterns = root.workspaces ?? []
  const found = new Map()
  for (const dir of await packageDirs(repoRoot)) {
    const rel = path.relative(repoRoot, dir).split(path.sep).join('/')
    if (!patterns.some(pattern => pattern.replace(/^\*\*\//, '').replace(/\/\*\*$/, '') === rel.split('/').slice(0, 2).join('/')
      || rel.startsWith('plugins/') || rel.startsWith('packages/') || rel.startsWith('apps/') || rel.startsWith('products/'))) continue
    const pkg = JSON.parse(await readFile(path.join(dir, 'package.json'), 'utf8'))
    if (pkg.name === selfName || typeof pkg.license !== 'string') continue
    found.set(pkg.name, { name: pkg.name, version: pkg.version ?? '0.0.0', license: pkg.license })
  }
  return [...found.values()].sort((a, b) => a.name.localeCompare(b.name))
}

/** 生成 dist/build-info.json 与 dist/licenses/。缺许可证全文不阻塞，只登记。 */
export async function writeBuildInfo({ repoRoot, outDir }) {
  const pkg = JSON.parse(await readFile(path.join(repoRoot, 'apps/desktop/package.json'), 'utf8'))
  const info = assertBuildInfo(buildInfo(pkg))
  await mkdir(outDir, { recursive: true })
  await writeFile(path.join(outDir, 'build-info.json'), JSON.stringify(info, null, 2) + '\n')
  const licenses = await collectLicenses(repoRoot, pkg.name)
  const licensesDir = path.join(outDir, 'licenses')
  await mkdir(licensesDir, { recursive: true })
  await writeFile(path.join(licensesDir, 'third-party.json'), JSON.stringify(licenses, null, 2) + '\n')
  const full = path.join(repoRoot, 'LICENSE')
  let licenseText = false
  try { await copyFile(full, path.join(licensesDir, 'LICENSE.txt')); licenseText = true } catch { /* 未登记即缺省 */ }
  return { info, licenses, licenseText }
}
