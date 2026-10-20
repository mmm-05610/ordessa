// PA-11 发行物代码卫生：发行目录里**不得**残留任何测试驱动代码。
// 构建期由 build.mjs 调用（真实构建即真实门），另有单测直接测这个闸门本身。
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'

/** 只认这些标记：它们逐字出现在主进程内联的 smoke 驱动里。 */
export const FORBIDDEN_MARKERS = [
  'MODULAR_LOADER_READY',
  'executeJavaScript',
  'agent-placeholder',
  'conn-status-toggle',
  'agent-sessions',
  'data-testid="increment"',
  'MODULAR_UI_FOUNDATIONS',
  'MODULAR_FE_TWO_TURN_SMOKE',
]

/** 逐文件扫描 dist，返回违规定位。空数组 = 通过。 */
export async function findTestDrivers(distDir) {
  const violations = []
  const walk = async (dir) => {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) { await walk(file); continue }
      if (!/\.(c?js|mjs)$/.test(entry.name)) continue
      const source = await readFile(file, 'utf8')
      for (const marker of FORBIDDEN_MARKERS) {
        if (source.includes(marker)) violations.push(`${path.relative(distDir, file)} contains ${JSON.stringify(marker)}`)
      }
    }
  }
  await walk(distDir)
  return violations
}

export async function assertNoTestDrivers(distDir) {
  const violations = await findTestDrivers(distDir)
  if (violations.length) throw Error('Release hygiene: test driver code reached the distribution:\n  ' + violations.join('\n  '))
  return true
}
