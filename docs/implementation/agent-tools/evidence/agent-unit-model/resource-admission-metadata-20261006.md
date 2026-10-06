# 014 同注册表资源准入元数据（PARTIAL）

前置7f7b98fb73，tracked clean，.env仅未跟踪且不读。028 contracts §3与AU interface-map已冻结同Registry可信接纳原则。本片仅发现元数据，不实现材料作用。

## 写权和实现

三名gpt-6-luna：core_impl独占registration/environment/core resource_admission及agents.public；wire_impl独占新增test_resource_provider_admission_view；core_review只读审查及后续材料提案。主会话独占工单/文档/Git与串行测试。所有生产编码和新测试由Luna完成。

同CoreRegistry stage保存原C1 descriptor字段副本与规范supports快照（未声明None与明确空集合分别保持）；commit整批先验证再发布，原resource_provider二元返回及C1 DTO/SPI不变。Environment单/list发现先独立`${env}:agents.resources` object read，按原registry实例匹配唯一active Host activation。未提交、draining、退役不广告，精确查询缺席/漂移拒绝，未声明coverage旧C1仍可注册但新发现typed unavailable。元数据不含provider对象/callable，不调用acquire/release/reconcile/SecretPort，不开启capability。

DTO属于core层，agents.public再导出，保持原public facade只能core/environment依赖。descriptor与ActivationRef各复制字段，输出强改不影响provider/registry或Host事实。支持集合tuple规范固定。明确注册发布前typed失败清理仍staged的批次，未确定发布结果不回滚；此仅CoreRegistry，不碰Agent Operation/Step/Usage/unknown占用。

## 定向命令与失败账

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_resource_provider_admission_view.py -q --tb=short
```

首19项17P2F exit1、0.19s：两处新增测试误用不存在resource_descriptors，按实际resource_provider_admission四元读原快照，只修测试引用，no-alias断言保留。复跑19P0F exit0、0.16s。

独立审查发现返回ActivationRef与Host内部ref别名及in-process便利activate发布前拒绝遗留pending ID。作者分别复制身份值、只清理证明尚未发布的stage批次，新增2反例。首21项20P1F exit1、0.20s：插入新增函数时原双provider正例末端policy断言错归新增函数，NameError；恢复原断言原位置/意义，未删除断言或扩大fixture掩盖。最终 **21P0F exit0、0.18s**，包括两个提供者同Environment、独立ACL、未声明/None/空支持、stage/活动漂移、原地descriptor/support mutation、返回副本、退役与失败后正确再激活。发现作用方法均0。

## 核心/C1/API回归

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
```

首306P1F exit1、8.25s：原test_facade_chain_ast_forbids_business_modules拒Environment import agents.resources。没有改guard；DTO移至core/resource_admission，再公开导出。复跑307P0F exit0、8.25s。后续身份副本/注册清理修复后最终 **307P0F exit0、8.22s**（核心261＋集成13＋API33），无skip，所有原C1/platform边界测试保留。

## 产品回归

```bash
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

最终 **788P0F exit0、217.74s**，句柄19499已terminal，无skip。冻结期间只准备下一合同/测试计划，没有改运行中的源码和测试。不与21/307项组合累计独立场景数。

## 分级、审阅与剩余

新增21项为in-memory真实Environment/CoreRegistry的受控单元/合同证据，不含SQLite材料获取、实际材料消费者或Harness进程。上述集成回归仍包括自有Python/SQLite crash恢复；P新增0/M0。所有计数为各次快照，有重叠不相加。runner GREEN_NO_SKIPS与worker/sidecar/ACP assets ABSENT同时记录，资源缺席不当产品绿。

跨作者静态审查及主会话读审发现并修复descriptor/Host身份别名、facade逆向依赖与明确失败pending ID清理；最后指定维度未发现新阻断。未知commit异常保留staged batch的路径仅静态审查，本批新增测试覆盖typed验证拒绝后安全再激活，不冒unknown覆盖。

本片不提供材料路由、获取、授权租约、秘密解析、生产writer/回执、任务结果或CLI/Skill完整体验。metadata读取不是材料获取许可。用户已采用非秘密受权材料扩展，下一批继续原issuer/Operation/Step/Usage及lost-receipt查询；全optional拒单基准恢复仍待答，未私改。第三方安装/用户服务、数据、凭据、全局配置操作/push/主树合并均0；费用unknown，tokens以平台账为准。

## 工单材料验证

新增014首strict exit1（缺节/terminal/waive及共享路径串行声明），只修工单结构与具体写域后全14工单strict exit0；它不是产品可用证据。阶段完成以实际测试及边界账为准。

014 batch strict首exit1（缺退出码标签、外批009依赖缺固定SHA条件），补固定7f7b98fb73及标签；再exit1（缺缺口标签），补明确门/缺口后exit0。只调整材料，不代替产品测试。
