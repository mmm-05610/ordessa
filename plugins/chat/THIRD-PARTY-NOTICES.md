# Third-party notices — plugins/chat

本目录包含自以下上游项目移植的代码。各来源的版权、许可与修改说明如下。

## ZCode

- 来源：https://github.com/zai-org/ZCode，快照 `29628c9acdb81b703bbd4080c207a0e7ce5e276e`
- 许可：Apache License 2.0（完整文本见本目录 `licenses/ZCode-LICENSE`）
- 版权：Copyright ZCode contributors
- 修改说明：取材文件与逐文件取舍见 `upstream-manifest.json`。所有移植均为
  按符号/逻辑提取并适配本仓库类型与样式体系，非整文件复制；保留了原信息
  层次与交互语义（紧凑工具行、思考折叠纪律、输出冻结跟随、IME 输入纪律）。

## Vercel（ai-elements 派生文件）

上游 ZCode 的 `components/ai-elements/message.tsx`、`reasoning.tsx`、
`prompt-input-textarea.tsx` 派生自 vercel/ai-elements（Copyright 2023
Vercel, Inc.，Apache-2.0），并经 ZCode 修改。本目录的对应移植文件因此同时
携带 Vercel 派生版权：`markdown-body.tsx`、`reasoning-block.tsx`、
`text-input.tsx`（以及结构上参考 `code-block.tsx` 的 `code-block.tsx`）。

## 运行时依赖（按固定取材版本）

| 包 | 版本 | 许可 | 用途 |
| --- | --- | --- | --- |
| streamdown | 2.5.0 | Apache-2.0 | 流式 Markdown 渲染 |
| @streamdown/cjk | 1.0.3 | Apache-2.0 | 中文排版插件 |
| shiki | 4.0.2 | MIT | 代码高亮（公开 token API） |
| use-stick-to-bottom | 1.1.3 | MIT | 会话滚动跟随 |
| radix-ui | ^1.6.7 | MIT | Collapsible/弹层原语（沿用根锁版本） |

以上依赖的许可证文本在打包构建时随 `build.mjs` 的 licenses 段复制进扩展产物；
本目录 `licenses/` 保留一份源引用副本。
