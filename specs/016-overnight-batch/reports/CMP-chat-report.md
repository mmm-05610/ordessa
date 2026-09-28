# CMP-chat-report · 016 夜批（son-cmp-chat，支 codex/plugin-chat）

日期：2026-09-29 凌晨。执行者：**zcode 代打**（qoder 同夜写权限墙，派工 log
`…/logs/son-cmp-chat-qoder-*.log`）。甄别清单：main 版
`specs/011-z2-chat/tasks.md`（R0–R4 + V01–10 + D01–04 + I01–07 = 26 项）+
`docs/design/workbench-sidebar/tasks.md`（WS01–10 = 10 项）。写入面自查：
本批零代码改动（甄别=复验+归档），仅本报告。

## 0. 受控复验（真实退出码）

| 门 | 线报告（收口时） | 本批复验 |
| --- | --- | --- |
| chat-api vitest | 15/15 | **23 passed**（分支后续合并净增 8，全绿） |
| chat frontend vitest | 35/35 | **50 passed**（5 文件；净增 15 全绿） |
| chat-api / frontend tsc | ×2 全 0 错 | **×2 干净** |

（vitest/tsc 用主仓 node_modules 工具链跑树内源；模块解析经目录 walk-up
命中，无跨树写入。）

## 1. z2 账本 26 项甄别表（三档：A/A' 同 CMP-profile 定义）

| ID | 三档 | 证据与结论 |
| --- | --- | --- |
| R0 | **A** | baseline.md（98be5571cb 冻结）在树；基线 `96fef2db47` |
| R1 | **A** | 检查点三笔（chat-api v1/r2/r3：54ad26c15d/31fb2db46d/3d8c3fa410）+ foundation 消费 8844c475bc；api-requests.md 在树 |
| R2 | **A'**（归属切割） | 原 D/I/V 项逐项有实现/验收/归属（line report §2）；残余=真实服务面归 C0（见 V03/V08 行）；复验套件全绿 |
| R3 | **A'** | 检查点/接线清单（integration-request §1/§4/§6）/许可账（upstream-manifest + ZCode-LICENSE + THIRD-PARTY-NOTICES）齐备；复验 4/4 门绿 |
| R4 | **A** | `0cfb01e28b` 任务账勾选（含依赖归属）；report REVIEW_READY 口径、未完成项如实列 PARTIAL |
| D01–D04 | **A** | contract.ts 六槽位/四 key props/ChatLocation/快照三态 + 类型反例；D04 差异清单在 upstream-manifest.json dropped 字段（复验文件在树） |
| V01 | **A'**（S0 绑定达成） | 本线基线实跑 + foundation 合入即正式平台 SHA（8844c475bc） |
| V02 | **A** | 三检查点；无 any 逃逸审计；范围外修改一次性列齐（R-Z2-1/2/3/5/6） |
| V03 | **A'**（归属切割） | 项目门/文本发送真实 facade 证明（composer-flow）；命令目录/附件 prepare/三态 submit 真实服务**归 C0**（共同 plan S1 归属）——残余义务去向：integration-request §6 + C0 账 |
| V04 | **A** | display 11 例（流式两分/渲染失败保留原文/思考折叠/同名工具不串展/failed-unknown 不混淆/命令仅来自验证字段），复验绿 |
| V05 | **A** | 项目弹窗/直达草稿/取消零调用/发送门禁/审批唯一操作面（approval-project 10 例），复验绿 |
| V06 | **A** | +/斜杠共用面板全反例组（panel-draft 7 + chat-api 23），复验绿 |
| V07 | **A'**（fixture 层完成） | 选择/粘贴/预览/重试/objectURL 所有权/未就绪阻止；**真实内容 hash 往返依赖 R-Z2-2（C0）**——去向已登记 |
| V08 | **C→归属登记**（待 C0，非本线可做） | 产品装配归 C0（integration-request §1）；两扩展试构建通过（be672a59a0）。非本线卡点，按派工"被取代项注明"口径登记归属 |
| V09 | **登记未测** | 真实浏览器矩阵/Electron 门依赖装配；维持登记，不虚勾 |
| V10 | **A** | 本报告即交付物；线内独立审阅见 z2 report §6 |
| I01–I05 | **A** | 逐文件 provenance（upstream-manifest git-hash + kept/dropped/adapted）、许可副本（复验在树）、展示/输入/面板/贡献各测试组复验绿 |
| I06 | **A'**（归属切割） | 适配完成；旧 UI 切换归 C0（integration-request §4 断言映射登记） |
| I07 | **登记未测** | 浏览器矩阵依赖装配；维持登记 |

## 2. workbench-sidebar 设计账 10 项甄别

**WS01–WS10 全部 = 已实现已验（他支完成）**：workbench-sidebar 线在独立树
（`codex/workbench-sidebar` 支）完成并留档——本树
`docs/design/workbench-sidebar/report.md` §1 逐项映射表（WS01 baseline、
WS02 PROVENANCE SHA 29628c9/Apache-2.0、WS03–WS08 实现+浏览器证据、
WS09 门禁表 50 测试绿、WS10 报告+审阅）+ §2 门禁复跑记录（vitest 50、
node 7/7、typecheck PASS、根聚合 21/22 唯一红=登记预期红）。
**本包不复验**：工作产物在 `packages/workbench/**` 于彼支，未并 main（其
报告明示未 push/未合并），本树无可复验对象；勾选态维持未勾（设计快照口径，
交接文档明示不要求两树双向同步）。归并/验收该线成果归 INT/用户晨裁。

## 3. 结论

z2 账本 26 项：**A×21、A'×4（V01/V03/V07/I06 归属切割，去向均已登记
integration-request）、登记未测×2（V09/I07，依赖装配）、归属登记×1
（V08 待 C0）**。workbench-sidebar 10 项：全部他支已实现已验（证据在树、
工作在他支）。无虚勾：所有"未测/待 C0"项维持原口径。

## 4. 复用与自建清单（红线 7）

本批零代码：纯甄别+复验+归档。复用=z2/chat-api 全部交付物与测试、
workbench-sidebar 线留档证据、walk-up 工具链复验法。

## 5. 审阅

（待后备审阅后回填）
