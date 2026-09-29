/**
 * 产品产物位置的唯一解析点（B-003）。
 *
 * 纪律：
 *   · 两种布局，一种解析：开发树（apps/desktop/dist 与 products/desktop/dist
 *     各自独立）与安装布局（build-deb 把两者**合并**拷进同一目录，
 *     即 $ORDESSA_BUNDLED_ROOT/app/dist）。只按开发树的相对路径解析，装机后
 *     会得到一个不存在的 /opt/products/desktop/dist，discover 静默返回空目录，
 *     界面就成了零扩展的空壳。
 *   · 顺序是显式的、可测的：显式覆盖（ORDESSA_BUNDLED_ROOT/app/dist）→
 *     开发树相对路径 → 原样回退。回退给回**不存在的相对路径**而不是 undefined：
 *     那样与今天逐字节同一条 discover 路径（fail-closed 的空目录），开发树
 *     零回归，也不给安装布局凭空加一条新分支。
 *   · 这个文件只做路径解析，不吞异常。
 */
import { existsSync } from 'node:fs'
import path from 'node:path'

export interface ProductLayout {
  /** 扩展发现根：里面有 extensions.json 与 extensions/<id>/。 */
  dist: string
  /** 产品清单目录：诊断导出要读的 extensions.json / extensions.lock.json 所在处。 */
  manifestDir: string
}

/** 开发树：electron 入口在 apps/desktop/dist/electron-main.cjs，往上三层是仓库根。 */
function devTree(distDir: string): ProductLayout {
  return {
    dist: path.resolve(distDir, '../../../products/desktop/dist'),
    manifestDir: path.resolve(distDir, '../../../products/desktop'),
  }
}

/**
 * 解析产品产物位置。`exists` 可注入，便于门在不碰真实磁盘布局的前提下测三种形态。
 */
export function resolveProductLayout(
  distDir: string,
  env: Record<string, string | undefined> = process.env,
  exists: (candidate: string) => boolean = existsSync,
): ProductLayout {
  const root = env.ORDESSA_BUNDLED_ROOT
  // 1. 显式覆盖：启动器 packaging/debian/ordessa.in 导出 ORDESSA_BUNDLED_ROOT，
  //    安装布局下产品产物与宿主产物合并在 <root>/app/dist。
  if (root) {
    const installed = path.join(root, 'app', 'dist')
    if (exists(installed)) return { dist: installed, manifestDir: installed }
  }
  // 2. 开发树：相对解析。存在与否都返回——今天的代码就是这个值，装机与开发
  //    走同一条 discover 分支，路径不存在时它自己 fail-closed。
  return devTree(distDir)
}
