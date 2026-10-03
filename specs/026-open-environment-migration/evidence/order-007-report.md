# 007 证据 — Harness 原生与资源按开放参与者接入（收口）

2026-10-04。前序：006@a84852b4c5；R7/M14 于本单期间接收（7fe33bcd70）。
委派账：K/M/Q/S/U/W=实现与测试切片（test-author 通道），L/T=盘点（repo-scout），N/O=样例与
顶层化；P（slice-worker）批次2 中途配额失败由主代理接管完成；V（slice-worker）与备用
general-purpose 通道 provider 故障，样例#1 由主代理亲自实现。主代理独占：裁决×3、Git、
台账、R7 合并、S2 实现。

## 任务对照（全部 S/I 完成）
- **T007-01** ✅ K（4d2309cf99）Participant 证据适配（19 测试）。
- **T007-02** ✅ S（3a5037117c）品牌组织门（9 测试）：三品牌资源槽/生命周期工厂/中性注册点
  顶层化域无未注册品牌分支（AST 反扫+23 文件白名单）；DRIFT 登记：sandbox platform.py:59
  品牌分支唯一注册例外、skills 前端静态品牌选项。
- **T007-03** ✅ S 原生配置能力诚实门（7 测试）：unsupported/unknown typed 拒，绝不空成功。
- **T007-04/05** ✅ M（ba14a6d1c3）历史 owner/静态目录门（7 测试）。
- **T007-06** ✅ U（1520384ec2）未知事件//workflow 穿透（5+3 测试，真 SDK 链）；DRIFT 登记：
  SDK 反序列化层丢未知 sessionUpdate（connector 侧通用出口缺，转 009）；UNKNOWN：事件预算缺项。
- **T007-07** ✅ Q（e6a00c4471）退役证据充分性（11 测试）。
- **T007-08** ✅ 三品牌受控回归逐 ID 以 001 基线+各切片红集对照承载（真实资产/登录=U 待验）。
- **T007-09** ✅ 样例#1 异协议 Agent（923c5c0445，10 测试）+ 样例#2 静态资源包（a59f47ebb3，
  6 测试）——E2 要求的两个独立构建齐；样例#3（非 Chat terminal）需 Surface 面，路由 009。
- **T007-10** ✅ 三批顶层化全部完成（a59f47ebb3/98e7a4ad7b/3a5037117c）：11 个域全部
  plugins/ 顶层；发行/import/extension id/数据 namespace 零变化（mcp 扁平 backend import 冻结）。
  **裁决记录**：域内品牌适配物理搬迁延后（注册机制已中性化，C95 判据按归属不按物理位）；
  runtime-preferences 整域归属待用户裁决（保持顶层化位置）。
- **T007-11** ✅ W（本提交）无 Profile 全链管理+E5 引用/阻塞/coverage 诚实+DataArea 伪造
  namespace 拒（5 测试，零 DRIFT）。
- **T007-12** ✅ W memory 域隔离（2 测试）+ 样例#1/#2 独立安装运行（pip -e + 公开合同接入）；
  OS 适配缺席=明确降级（SecretRefAdapter locked 拒语义由 005 覆盖）。

## 门对照
- G007-1（未知/新命令有界传递不判终态）✅ U 直接证据（含真 SDK 链）。
- G007-2 前序 SHA 链完整。G007-3 红集对照全程执行。G007-4 无凭据/真实数据/未授权操作 ✓。

## 命令与结果（本单累计）
| 套件 | 结果 |
| --- | --- |
| plugins/harness | 3F 继承集 / 877P + 新增 16+7+11+5+7 测试文件全绿 |
| 资源域 11 域 | mcp 526P、skills 438P、model-provider 283+23P、sandbox 107+68+124P、prompts 186P+1F继承、memory 127P+1S、command-templates 83P、extensions 101P、subagents 889P+1F继承、lsp 42P、runtime-preferences 151P |
| JS workspace | subagents/settings 95P、ui 31P、mcp/frontend 39P、ui-components 48P |
| 样例 | fourth-agent 10P、static-resource 6P、f5-counter 5P、f5-react-panel 3P |
| Go/其他 | acp-connector 真 SDK 3P（U） |

继承红登记（非本单引入）：prompts toml 漂移 1F、subagents profile_facet overlay 清理 1F
（语义归 010）。001 证据完整性事件见 range-change-sed-lesson.md（已回滚修复）。

## 移交
1. SDK 未知事件 connector 侧通用出口缺口（U 的 DRIFT）→ 009。
2. 样例#3（非 Chat terminal/document）→ 009（Surface 面就绪后）。
3. 域内品牌适配物理归位与 runtime-preferences 归属 → 012 复核/用户裁决。
4. 权威/消费者台账随 012 全量回归收口。
