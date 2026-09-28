# 016 · 无人值守夜批 实施规格

状态：**2026-09-28 深夜批次，用户授权无人值守执行**。十一包、三父、十一子。大类表补全（MPX/EXT）；存量域补完（CMP 系）：全部 011 账本处于「归并≠验收」未勾态，逐域甄别补做。SR 已裁（tool 范畴归既有域，自建后端待裁）。
父亲目录只是编排文档+儿子工作树的容器；儿子才是真工作树。父亲会话（zcode）
逐包派 qoder 执行、可开子代理、自调审阅；**只提交不并回**，明早用户验收。

## 十一包一览

| 包 | 目录/分支 | 基线 | 一句话职责 |
| --- | --- | --- | --- |
| PE1 permissions-authority | `plugins/permissions`（推进 `codex/plugin-permissions`） | main | 权限插件产出「授权事实」查询面（谁/批了什么/范围/时效），供 core 的 C4 admission 闸门消费（pi 阻塞三前半） |
| PE2 harness-native-evidence | `plugins/harness`（推进 `codex/plugin-harness` @ `ef554ac63d`） | harness 支 | harness 产出「原生观测事实」（native receipt/会话身份/launch 溯源），同一闸门后半 |
| EXT extensions | `plugins/assets/extensions`（新支 `codex/plugin-extensions`） | main | 可执行扩展全域：hooks 定义/批准/哈希/pin/投影（原 HK 已审），扩容原生插件（pi/hermes/opencode/qwen/kilo）与自定义工具，三类共用机制 D 批准链 |
| MPX model-provider-params | `plugins/assets/model-provider`（推进 `codex/plugin-model-provider` @ 20085c0198） | 该支 | 参数配置补缺：推理强度/预算/超时/请求级 retry 四类键投影（014 裁定请求级参数归 model-provider），直接扩其既有三品牌 adapter，不立新包 |
| LSP | `plugins/assets/lsp`（新支 `codex/plugin-lsp`） | main | 五家原生 LSP 配置投影（server 定义/语言映射/formatter/可用性诚实检查）；codex/claude/dsh=unsupported |
| CMP-skills | `plugins/assets/skills`（推进 `codex/plugin-skills`） | 该支 | q1 账本 23 项甄别补完：已实现已验/已实现未验→补验/未做→补做；E3、core 依赖、被取代项注明卡点 |
| CMP-subagents | `plugins/assets/subagents`（推进 `codex/plugin-subagents`） | 该支 | q3 账本 21 项同模式甄别补完 |
| CMP-mcp | `plugins/assets/mcp`（推进 `codex/plugin-mcp`） | 该支 | q4 账本 5 项甄别补完 |
| CMP-profile | `plugins/profile`（推进 `codex/plugin-profile` @ 2c48889a25） | 该支 | z1 账本 17 项甄别补完（014-A r2 已验部分直接归档） |
| CMP-chat | `plugins/chat`+`plugins/agent`（推进 `codex/plugin-chat` @ 4d555a09b2） | 该支 | z2 账本 26 项 + workbench-sidebar 设计账 10 项甄别（被取代项注明而非硬做） |
| PX prompts-EXT | `plugins/assets/prompts`（推进 `codex/plugin-prompts`） | main+该支 | 执行 main 上 addendum 的 EXT-00..05 八家扩展 + R0 实测补账 |

015 两树（runtime-preferences / memory）独立在跑，**本批任何包不得触碰其目录**。
账本甄别三档口径：已实现且 014/分支报告有证据→直接勾并附证据指针；已实现无证据→
受控补验后勾；未实现→今晚补做（受 E2 约束）或注明卡点（E3/core 依赖/被后续架构取代）。
**同分支单子**：model-provider 的 z3 五项并入 MPX-5；harness 的 c0 廿四项并入 PE2-7；
permissions/sandbox 的 q5 五项并入 PE1-7——不另开树。

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
7. **复用优先（用户红线）**：机制不重造——C2/C4、既有 adapter 骨架、EXT 的批准/哈希/pin 链三类共用；品牌原生能力优先投影，不自建替代实现；每包 report 附「复用了什么/自建了什么」清单，自建超三成要在报告里说明理由。

## 成功条件（通用）

每包 tasks 全勾或如实标注卡点；report.md 齐全（含 qoder/审阅执行记录）；
不要求其他包完成（六包间无横向代码依赖，PE1/PE2 语义配对但各自独立可测）。
