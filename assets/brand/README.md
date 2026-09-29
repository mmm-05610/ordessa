# Ordessa 品牌资产（2026-09-29 归档）

来源：用户提供的品牌包（原仓库根 `brand/`，文件名为下载散名；归档时按
guidelines 的 PRIMARY/APP ICON/HORIZONTAL/VERTICAL 对照表逐张渲染确认身份后
重命名）。**全部 SVG 为内嵌位图版**（base64 PNG 包在 SVG 壳里，非真矢量）——
矢量重制待设计侧提供，当前不影响任何构建。

## 布局

- `icon.svg` —— 应用图标的**单一事实源**：`packaging/icons/export-icons.mjs`
  与 `apps/desktop/scripts/build-icons.mjs` 构建时读取它栅格化全档
  （hicolor 16-256 + win/mac）。当前放 ordessa-icon-light（白底黑符·圆角卡），
  暗色版在 `app-icon/ordessa-icon-dark.svg`，要切换即替换本文件（纯文件替换，
  无代码改动）。
- `logo/` —— horizontal（符号+ordessa 左右）、vertical（符号+Ordessa 上下）、
  wordmark（纯字标小写）、symbol-black/white（对照表 PRIMARY 双色），
  各附 -2048 像素 PNG。
- `app-icon/` —— light/dark 两版 SVG + 2048px PNG。
- `guidelines/` —— 品牌使用规范 PDF + 同页 PNG/SVG（clear space / minimum
  size / correct-incorrect usage）。

## 导出验证（2026-09-29）

`xvfb-run node packaging/icons/export-icons.mjs` → `placeholder: false`，
6 档真设计栅格落 `apps/desktop/dist/icons/hicolor/**` 与
`packaging/.staging/root/usr/share/icons/**`（256px 人工核对与 guidelines
APP ICON 一致）。
