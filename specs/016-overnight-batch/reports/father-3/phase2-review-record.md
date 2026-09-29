# 阶段二产物审阅记录（overnight-3）

日期：2026-09-29。按 father.md 阶段二审阅口径执行："把文件内容直接喂
run-review 所用模型口径即可"——即 `pi -p --no-session --no-tools --model
mimo-v2.6-pro`（run-review.sh 的后备调用形态），五份文档原文一次性喂入
（输入 26,743 字节：recon-zcode-tui.md + phase2-design-{lsp,mcp,profile,
chat}.md 修订前版本），无工具、只依据文本审阅。

## 审阅输出（原文存 /tmp/phase2-review-out.txt，结论转录如下）

- recon-zcode-tui.md：有保留——证据纪律整体严谨，仅"本会话即由该 CLI 承载"
  属不可回指自证。
- phase2-design-lsp.md：有保留——目标格"实施"与裁决字面冲突；"其余三家证据
  已足"与同表待核项自相矛盾。
- phase2-design-mcp.md：通过。
- phase2-design-profile.md：有保留——dsh 生效语义待核却钉死 applyMode。
- phase2-design-chat.md：有保留——dsh 行把"ACP 通道存在"越推为"会话身份经
  ACP"；L3/L5 级别名缺本文集内定义。
- 总评：**有保留**。8 条必须修问题。

## 处置（8/8 落实，同日修订入档）

| # | 问题 | 处置 |
| --- | --- | --- |
| 1 | lsp 目标格"实施"与裁决冲突 | 三格改"**实施（待授权派单）**"＋文首加格内授权前提声明 |
| 2 | lsp"其余三家证据已足"自相矛盾 | §5 改为逐家前置清单（hermes LSP 页取证、dsh 生效方式取证、kilo 重启身份恢复取证；opencode 证据已足） |
| 3 | L3/L5 级别名缺定义 | **部分误报**：information-recon-priority.md §一 确有 L3（官方文档带抓取日期）/L5（一手受控观测/E2）定义；已按建议在 lsp/chat 文首补级别引用行，消解读者不确定 |
| 4 | recon 自证句＋封装路径缺失 | 删"本会话即由该 CLI 承载"；run-qoder.sh/run-review.sh 补可复现路径 |
| 5 | profile dsh applyMode 未证钉死 | 拆两列：写入语义=generation 替换（有据）；生效时点未证→applyMode=待核 |
| 6 | chat dsh 越精度边界 | 改"ACP 通道存在已证；sessionRef 映射待实测，未证前同 opencode 只读降级，不默认复用现有 bridge 语义" |
| 7 | mcp"四家无一例外"绝对断言 | 明写"Ordessa 侧设计不变量与测试约束，非对四家运行行为的断言" |
| 8 | 两域装配 owner（INT/AR vs C0）不一致 | **核实两处引用各自属实**（LSP-report :118；CMP-chat-report V08）→ 不擅自统一，两文各加显式待裁注记：派单前不得互推 |

修订后五份文档现版即终版；本记录为该轮审阅的闭环凭据。
