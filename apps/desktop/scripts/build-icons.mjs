// PA-03 图标接线：单一事实位置是 `assets/brand/icon.svg`（用户后续提供设计稿），
// 换图**不改任何代码**。本脚本只负责导出：
//   1. 多尺寸 PNG（16/32/48/64/128/256）
//   2. Linux hicolor 布局 `hicolor/<size>x<size>/apps/ordessa.png` + 可缩放 SVG
//   3. `icons/generated.json` 记录本次导出的来源与缺口
//
// 诚实边界：仓库没有也不允许新增栅格化依赖（写入面纪律），因此
//   · 设计稿缺失 → 用内置占位图生成全部尺寸，构建与运行都不阻塞；
//   · 设计稿存在但本机无栅格化器 → 复制 SVG（矢量始终可用）并继续用占位 PNG，
//     在 generated.json 里如实登记 `rasterized: false`，由 P-C 在打包机用自带工具补齐。
// 两条路径都不抛错，也都不会让"换图"变成代码改动。
import { access, copyFile, mkdir, readFile, writeFile } from 'node:fs/promises'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import path from 'node:path'
import { encodePng } from './png.mjs'

const run = promisify(execFile)
export const ICON_SIZES = [16, 32, 48, 64, 128, 256]
/** hicolor 规范里 hicolor 之外的固定尺寸槽位。 */
export const HICOLOR_SIZES = [16, 24, 32, 48, 64, 128, 256, 512]

/** 内置占位标记：一个深底圆角方块 + 浅色菱形。纯几何，不含任何品牌字样。 */
export function placeholderPixels(size) {
  const radius = size * 0.22
  const center = (size - 1) / 2
  const inside = (x, y) => {
    const dx = Math.max(radius - x, 0, x - (size - 1 - radius))
    const dy = Math.max(radius - y, 0, y - (size - 1 - radius))
    return Math.hypot(dx, dy) <= radius
  }
  return (x, y) => {
    if (!inside(x, y)) return [0, 0, 0, 0]
    const diamond = Math.abs(x - center) + Math.abs(y - center)
    const edge = Math.max(0, Math.min(1, (diamond - size * 0.12) / (size * 0.12)))
    const r = Math.round(24 + (236 - 24) * edge)
    const g = Math.round(26 + (238 - 26) * edge)
    const b = Math.round(31 + (245 - 31) * edge)
    return [r, g, b, 255]
  }
}

async function exists(file) {
  return access(file).then(() => true, () => false)
}

async function rasterize(svg, size, out) {
  const override = process.env.ORDESSA_ICON_RASTERIZER
  const candidates = override ? [override] : ['rsvg-convert', 'inkscape', 'convert', 'magick']
  for (const tool of candidates) {
    try {
      const args = tool.endsWith('convert') || tool.endsWith('magick')
        ? ['-background', 'none', '-resize', `${size}x${size}`, svg, out]
        : tool.endsWith('inkscape')
          ? ['--export-type=png', `--export-filename=${out}`, `--export-width=${size}`, svg]
          : ['-w', String(size), '-h', String(size), '-o', out, svg]
      await run(tool, args)
      if (await exists(out)) return true
    } catch { /* 下一个候选；都没有则回落占位图 */ }
  }
  return false
}

/**
 * 导出图标。返回一份可核查的报告（写进 icons/generated.json）。
 * 任何路径都不抛错：缺设计稿、缺栅格化器都产出可运行的占位产物。
 */
export async function exportIcons({ repoRoot, outDir, source = path.join(repoRoot, 'assets/brand/icon.svg') }) {
  await mkdir(outDir, { recursive: true })
  const flat = path.join(outDir, 'flat')
  await mkdir(flat, { recursive: true })
  const hicolor = path.join(outDir, 'hicolor')
  const haveSource = await exists(source)
  const report = { source, haveSource, rasterized: haveSource, sizes: ICON_SIZES, files: [], warnings: [] }
  let anyRasterized = false
  for (const size of ICON_SIZES) {
    const file = path.join(flat, `${size}.png`)
    let ok = false
    if (haveSource) ok = await rasterize(source, size, file)
    if (!ok) {
      await writeFile(file, encodePng(size, placeholderPixels(size)))
      if (haveSource && !anyRasterized) report.warnings.push(`no rasterizer for ${size}px; placeholder kept`)
    } else anyRasterized = true
    report.files.push(path.relative(outDir, file))
  }
  report.rasterized = haveSource && anyRasterized
  // hicolor 布局：固定尺寸槽位复用同一批 PNG，避免重复栅格化。
  for (const size of HICOLOR_SIZES) {
    const source16 = ICON_SIZES.includes(size) ? path.join(flat, `${size}.png`) : path.join(flat, `${ICON_SIZES.reduce((a, b) => (b > a && b <= size ? b : a), 16)}.png`)
    const dir = path.join(hicolor, `${size}x${size}`, 'apps')
    await mkdir(dir, { recursive: true })
    await copyFile(source16, path.join(dir, 'ordessa.png'))
    report.files.push(path.relative(outDir, path.join(dir, 'ordessa.png')))
  }
  if (haveSource) {
    const scalable = path.join(hicolor, 'scalable/apps')
    await mkdir(scalable, { recursive: true })
    await copyFile(source, path.join(scalable, 'ordessa.svg'))
    report.files.push(path.relative(outDir, path.join(scalable, 'ordessa.svg')))
  } else report.warnings.push('assets/brand/icon.svg absent: placeholder icons are in use')
  await writeFile(path.join(outDir, 'generated.json'), JSON.stringify(report, null, 2) + '\n')
  return report
}

/** 窗口图标：优先 256px，缺失时回落 Electron 默认（缺图不阻塞启动）。 */
export async function windowIconPath(outDir) {
  const file = path.join(outDir, 'flat', '256.png')
  return (await exists(file)) ? file : undefined
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const repoRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '../../..')
  const report = await exportIcons({ repoRoot, outDir: path.join(repoRoot, 'apps/desktop/dist/icons') })
  console.log(`icons: source=${report.haveSource} rasterized=${report.rasterized} files=${report.files.length}`)
  for (const warning of report.warnings) console.warn('icons warning:', warning)
}
