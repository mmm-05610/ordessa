---
id: AU003
slug: three-providers
batch: agent-unit-v1
baseline: "3086825a6177438c042431cdb94812ded576ee6c"
depends_on: [{"order":"AU002","condition":"本树AU002阶段提交与核心管理反例通过"}]
write_paths: ["plugins/harness/**","packages/backend/harness-transport/**","products/server/**","products/agent-tools/deployment/**","products/agent-tools/src/ordessa_agent_tools/native_clients/**","docs/implementation/agent-tools/status.md","docs/implementation/agent-tools/evidence/agent-unit-model/**"]
forbidden: ["用户数据和凭据", "主树合并和push", "其他执行者未核对改动", "未经授权安装/真实模型/用户服务重启"]
ruling: R-3103
terminal: ["AU003_DONE", "AU003_PARTIAL"]
waive: []
serialize_with: ["AU001","AU002","AU004","AU005"]
parallel_units: ["pi: plugins/harness/pi/** 与独立测试，不写共享接口", "codex: plugins/harness/codex/** 与独立测试，不写共享接口", "claude: plugins/harness/claude-code/** 与独立测试，不写共享接口"]
---

## Objective
三家独立插件封装真实AgentUnit。以本包README裁决和contracts.md为准。

## Current state
观察HEAD见baseline；已有未提交三家和核心切片。源码现状：pacthold/agents/runtime.py已使用AgentContributionSet；core/lifecycle.py有版本化RuntimeProvider；产品cli.py目前只有init/doctor/capabilities/profiles。开工必须重新核对事实，不沿用这些观察冒充当前完成。

## Scope
逐家比较ACP/官方SDK/旧桥/新客户端并记录证据。实现Provider、Unit管理与使用入口，拆独立包且移除三家旧注册；从产品迁出品牌协议并去重。保留另外七家成果，确保三家不再由大插件偷偷启用。Pi/Codex/Claude只在自己包与测试内并行，共享装配主执行者处理。
只处理write_paths。本包合同文件只读；必要新共享包须先记录复用依据且不能扩张内核。不得改持久标识或未授权用户数据迁移。

## Requirements
### Requirement: 完成指定结果且不制造旁路
#### Scenario: 正向接入
**WHEN** 三家独立插件封装真实AgentUnit的主路径执行
**THEN** 结果符合contracts.md，记录对应身份、作用、证据和限制，而不是品牌stub成功。
### Requirement: 缺席与未知拒绝
#### Scenario: 缺资源或缺确认
**WHEN** 提供者、授权、版本比较或必要确认依据缺席
**THEN** typed拒绝或unknown，不启动fallback、不重发、不发布虚假ready。
### Requirement: 保持单一所有权
#### Scenario: 并发或迟到回执
**WHEN** 多调用者改同scope或旧回执晚到
**THEN** 不覆盖较新实际事实，不使用Profile填补不可观察配置。

## Stages
- [ ] 1. 核对真实工作基线、已有写者与前置，记录证据并阶段提交。
- [ ] 2. 按Scope实现；列接口映射和代表性正反例；阶段提交。
- [ ] 3. 接入调用方并完成定向测试、导入/发行/安全检查；阶段提交。
- [ ] 4. 主执行者复跑门，登记缺口、清理与成本，打不覆盖的检查点继续后续。

## Gates
| Gate | Assertion | Counter-example | Absent / unknown ⇒ |
| --- | --- | --- | --- |
| G1 单核心 | 沿用CoreRegistry及原持久操作/授权链 | 新增独立provider字典或直接副作用绕过claim必须失败 | fail，不能靠无命中当通过 |
| G2 配置事实 | applied有对应操作与scope确认，不双写actual | 仅接收ACK或旧快照当生效必须失败 | unknown/PARTIAL，禁止猜测 |
| G3 生命周期 | 授权撤销/退役后拒绝后续写，borrowed不误删 | 旧连接继续发送或断开当停止必须失败 | fail/PARTIAL |
| G4 产品边界 | CLI仅调用公开服务/授权入口 | 恢复产品品牌客户端或私有Harness import必须失败 | fail，缺源码/包不能通过 |
| G5 验证真实性 | 逐项C/P/M与精确计数退出码 | fixture宣称真实任务成功必须失败 | 对应层未验证，整体PARTIAL |

## Validation
以下为可运行窄基线；实现后扩充本单测试，不用减少断言/skip掩盖新红。
```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_runtime_admission.py -q
python3 /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/work-orders/agent-unit-model/orders --strict
git diff --check
git status --short
```

## DoD
实现、正反例、真实环境层级证据、回归计数与退出码、成本/清理、status分账齐全。
无真实资源按对应层PARTIAL，不伪造结果，不将材料校验当产品完成。

## Acceptance
AU003_DONE仅在本单全部门与所需真实层验证齐全；否则AU003_PARTIAL，逐项列缺口且继续可做任务。

## Notes for the executor
唯一主执行者提交、记账和复跑；只显式stage核对过的源码/证据，不能裸add全部dirty。
材料可随本单显式提交；不改本包语义代替用户裁决。新冲突记录到自己的status并继续其他可行项。

## Batch report
待执行：填写门结果、真实命令/退出码/计数、证据路径、剩余缺口。未跑不得勾选Stages。
