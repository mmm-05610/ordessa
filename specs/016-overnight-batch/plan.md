# 016 · plan（夜批事实底）

## 事实（写包时已核实/已检索）

- F1 S-06 双事实裁定在案（seams.md）：闸门机制归 core（pi 在建），authority
  归 permissions、native_evidence 归 harness，均归本批。事实到位前 ready=False
  诚实拒绝是双方约定口径。
- F2 C4/admission 消费面在 main：`apps/server/src/ordessa_server/acp_admission.py:94-140`
  permits；`ConfigurationApplicationService.apply`（configuration_service.py:150）。
- F3 permissions 插件在 main（011-q5 收口态，api/backend/adapters 三件结构）；
  分支 `codex/plugin-permissions` 已被 main 吸收（差异 0），夜批直接推进该支。
- F4 harness 支 `codex/plugin-harness` @ `ef554ac63d`（含 P-D claude 附件通路 +
  main 同步）；C4 native receipt 协议（operation 绑定 native owner receipt +
  一致 readback）经 P-A `51c7905108` 树立在案。
- F5 harnesses.toml slots 词汇含 hooks（多家有该 slot）；hook 阻断语义有已知
  反例：Codex MCP hook 错误/缺失**不阻断**操作（classification.md §四.4）——
  不得把观察性 hook 承诺成强制约束。
- F6 LSP 原生五家（harnesses.md 行号）：pi :130（LSP/formatter server 定义、
  语言映射）、hermes :110（LSP/搜索/媒体后端）、opencode :151-152（tool-lsp、
  lsp-stdio）、qwen :178（`.lsp.json`、extension lspServers、实验开关）、
  kilo :199（lsp、formatter）；codex/claude/dsh 无原生 → unsupported。
  LSP 均依赖机器已装可执行程序——可用性必须显式检查，不得只写配置。
- F7 搜索原生面（harnesses.md）：claude :18 web search **Desktop 专属，不得推定
  CLI/ACP 可用**；hermes :110 搜索后端可盘点；其余各家按 harnesses.md 逐家核实，
  无原生者 honest unsupported。
- F8 SearXNG（外部检索 2026-09-28）：AGPL-3.0-or-later，自托管元搜索，
  JSON API（`/search?q=…&format=json`，需 settings.yml 显式开启）；
  mcp-searxng 包装层 MIT。AGPL 服务只能**进程隔离选装**（HTTP 调用，不链入、
  不入库），默认不装；装则在产品 data-root，THIRD-PARTY-NOTICES 标注。
- F9 LSP→MCP 桥生态存在（mcp.so/mcpmarket 多个开源桥）。**v1 不引入**：LSP 走
  五家原生投影；桥接方案登记为后续研究项，不实施。
- F10 prompts 八家 addendum 在 main：`specs/011-q2-prompts-commands/addendum-eight-brands.md`
  （EXT-00..05 + R0 实测补账，36 项未勾账本）。

## 包间关系

PE1/PE2 语义配对（同一闸门的两路事实）但代码零交集；HK/LSP/SR/PX 四包互相
独立。无执行顺序约束（父会话按串行派工即可）。

## 待裁（明早，不阻塞夜批）

- **SR 整包已裁（用户裁定：搜索开关/预算属 tool 范畴，归既有域；产品自建搜索后端（SearXNG，AGPL-3.0 仅可进程隔离）转待裁，不实施。**
- LSP 桥接（F9）是否立项另裁。
- HK 观察性 hook 是否升格强制语义——按品牌逐家如实，未来裁。
