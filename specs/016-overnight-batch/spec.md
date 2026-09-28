# 016 · 无人值守夜批 实施规格

状态：**2026-09-28 深夜批次，用户授权无人值守执行**。六包、三父、六子。
父亲目录只是编排文档+儿子工作树的容器；儿子才是真工作树。父亲会话（zcode）
逐包派 qoder 执行、可开子代理、自调审阅；**只提交不并回**，明早用户验收。

## 六包一览

| 包 | 目录/分支 | 基线 | 一句话职责 |
| --- | --- | --- | --- |
| PE1 permissions-authority | `plugins/permissions`（推进 `codex/plugin-permissions`） | main | 权限插件产出「授权事实」查询面（谁/批了什么/范围/时效），供 core 的 C4 admission 闸门消费（pi 阻塞三前半） |
| PE2 harness-native-evidence | `plugins/harness`（推进 `codex/plugin-harness` @ `ef554ac63d`） | harness 支 | harness 产出「原生观测事实」（native receipt/会话身份/launch 溯源），同一闸门后半 |
| HK hooks | `plugins/assets/hooks`（新支 `codex/plugin-hooks`） | main | 可执行扩展首包：hook 定义（来源/哈希/版本 pin/批准）、事件匹配、逐品牌投影、阻断语义如实 |
| LSP | `plugins/assets/lsp`（新支 `codex/plugin-lsp`） | main | 五家原生 LSP 配置投影（server 定义/语言映射/formatter/可用性诚实检查）；codex/claude/dsh=unsupported |
| SR search | `plugins/assets/search`（新支 `codex/plugin-search`） | main | 各品牌原生搜索配置投影 + 可选 SearXNG 自托管绑定（AGPL-3.0，进程隔离，默认不装） |
| PX prompts-EXT | `plugins/assets/prompts`（推进 `codex/plugin-prompts`） | main+该支 | 执行 main 上 addendum 的 EXT-00..05 八家扩展 + R0 实测补账 |

015 两树（runtime-preferences / memory）独立在跑，**本批任何包不得触碰其目录**。

## 共同红线（六包全适用，父文档重申）

1. 写入面只在各自插件目录 + `specs/016-overnight-batch/reports/`；harness/permissions
   两包同样只动自己目录，需要别域改动登记 api-requests 报回，不越界。
2. 禁真实模型调用（E3）；受控测试一律假端点/假凭证（E2）。
3. 不 fake green：断言不许删、失败不许藏、unsupported 必须带证据。
4. 数据/凭据不入仓；SearXNG 若选装只在产品 data-root（环境例外目录）。
5. **无人值守附加**：qoder 不可用或单包两次失败 → 父会话自己代打并在报告标注
   「qoder 失败、zcode 代打」；审阅（pi + mimo-v2.6-pro）是附加证据**不是验收**，
   审阅失败如实记「未审阅」。
6. **只提交不并回**：儿子在自己分支提交；不 merge、不 rebase、不动 1+x 其他支。

## 成功条件（通用）

每包 tasks 全勾或如实标注卡点；report.md 齐全（含 qoder/审阅执行记录）；
不要求其他包完成（六包间无横向代码依赖，PE1/PE2 语义配对但各自独立可测）。
