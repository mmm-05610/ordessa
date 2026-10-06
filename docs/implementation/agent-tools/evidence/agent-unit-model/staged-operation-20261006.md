# 017 原操作分阶段接缝验证（2026-10-06）

基线e4dc70aa5c。core_impl唯一四生产文件，wire_impl唯一产品测试，core_review只读反例审查；主会话指导、合同、串行执行、账本及Git。同env_requests新增nullable阶段元数据，原OperationStorePort不改；root固定后仅一次append+seal，未核实的步骤不能推进，旧授权在recipe改变后失效。没有材料获取或Assembly接线。

## 验证命令与过程

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration/test_staged_operations.py products/agent-tools/tests/integration/test_operation_store.py products/agent-tools/tests/integration/test_invocation_authority.py -q --tb=short
```

过程：首次exit2，0.24s，一个收集错误（新夹具异常导入路径错误）；修正后91P/29F，exit1，1.71s（新DirectoryBinding夹具摘要非法及receipt期望不符）。新文件定向32P/1F，exit1，1.06s，第二处CurrentState目录夹具摘要仍非法；修正夹具使其与root精确一致，未放宽生产校验或删除断言。最终组合120P/0F，exit0，2.05s：新增19函数参数化33项，旧87项，无skip。

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests tests/integration/environment packages/backend/environment-api/tests -q --tb=short
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c packages/backend/persistence-sqlite/pyproject.toml packages/backend/persistence-sqlite/tests -q --tb=short
PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q --tb=short
```

分别307P/0F exit0 8.42s；43P/0F exit0 0.92s；821P/0F exit0 219.19s（session84288 terminal）。全套期间源码和测试冻结，后续018只读准备。以上重复快照不累加为独立验收数。核心runner的worker/sidecar/ACP资产仍ABSENT。

## 反例与范围

33项覆盖不可变副本/恶意实例回调、作用域、根重放、旧reserve混用拒绝、原子故障回滚、双连接CAS、unknown/refused/未claim拒绝推进、seal严格重放、bool版本拒绝、坏元数据、root及current step缺行、旧context失效与原claim查询、未seal publication零写及sealed原publication。

全部为单元/合同和真实临时SQLite的C级集成；无真实隔离服务、材料提供者作用或Harness进程新增证据，P新增0/M0。NULL旧记录兼容已测；已有命名操作但尚无新增列的旧数据库升级场景未单独验证，不宣传用户数据迁移或降级可用。普通非staged操作缺行风险已登记known-issues，下一018单独修复，不能用017绿替代。

材料路由、消费与Usage生命周期、生产输入及结果、CLI/Skill和隔离发行仍PARTIAL。无安装、用户数据库/凭据/全局配置/服务操作、push或主树合并；.env不读不入库。子代理费用与tokens以平台账为准。
