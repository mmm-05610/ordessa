# 统一终止方法族冻结与安全加固（PARTIAL）

前置 `b1d2afbf59`。主会话唯一共享写者；safety-reviewer 对冻结面做了只读安全审阅（未知/并发/数据/退出），全部"必须修"与四项"建议修"已落地；codex 家族真实适配器切片并行进行中（另记）。真实模型 0；无用户数据/凭据/服务操作、无 push/主树合并。

## 冻结面（records 单一账本，三家共用，先冻结后实现）

`harness_unit_terminations`（unit_ref+action 主键）＋`TerminationRecordTicket`＋`TERMINATION_VERSION='harness-unit-termination/1'`、`TERMINATION_ACTIONS=('stop','release')`：
- `begin_termination(unit_ref, context, *, input_digest, action)`：消耗原 cleanup 调用授权一次；每 (Unit, action) 永远只开一个 attempt（opening）；同相关性/同身份重放拒、异身份拒、同单元不同动作各一。
- `record_termination(ticket, *, expected_source_revision, state, evidence=None)`：unknown 保占用与活票据、绝不自动释放任何 Usage/进程；confirmed 必须经 **owner 证据端口**（`NativeTerminationEvidencePort.verify_termination`）验证，入库的是端口返回的 provenance refs，调用者字符串永不作为证明；confirmed 终态耗票据。
- `reconcile_termination(...)`：冷恢复——query 授权核原相关性后可结论 retained attempt；不重发、不补开、不释放。
- `owner_read_termination`：属主受信投影（带 `projection: 'owner-read'` 标记），免 invocation。

## safety-reviewer 审阅结论与修复

必须修（两项，均已修＋反例）：
1. confirmed 证据原可由任意字符串伪造（无端口验证）→ 新增 `NativeTerminationEvidencePort`，镜像 record_unit/record_session 的端口验证模式：端口验真、存端口返回 refs、读侧形状复核；缺端口/端口拒/端口返回坏形状均拒。反例：调用者 refs 不入库、伪造证据拒且保持 opening、端口返回 bool 值拒。
2. record 写后校验＋identity 不回绑（拒后已落库的未知结果窗口；可篡改 identity 过 record/read）→ 事务内 UPDATE 前按票据事实重算 identity 严格回绑并做损坏校验；读侧补 state 枚举/revision 类型/identity 与行回绑/outcome str→str 复检/JSON 异常包装。反例：篡改 identity/bool outcome/非法 JSON 均拒为 damaged 且不泄 ValueError。

建议修（四项已修）：跨重启楔死 → `reconcile_termination` 冷恢复（反例：新实例旧票据拒、异 step query 拒、原相关性 query 可 confirmed、reconcile 后 begin 仍单发）；epoch TOCTOU → 实时 epoch 检查移入 BEGIN IMMEDIATE；evidence 二次迭代微窗 → 先拷贝再校验存储同一份；correlation 撞车 → typed 拒（不泄 sqlite3.IntegrityError）。

登记为设计边界（非失败）：owner 读与授权读同返回类型——provider 即属主（管线冻结合同），属主读自家 journal 是受信投影；需要授权读证据的下游必须消费 context 读。record_unit/record_session 的同型事务外 epoch 检查为既有模式，本次未扩面修改，如实注记。

## 验证（专属 Python 串行、句柄 terminal）

| 命令 | 结果 |
| --- | --- |
| `PYTHONPATH=plugins/harness/records/src:plugins/harness/api/src:packages/backend/harness-transport/src <py> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_records.py -q` | **38P/0F exit0**（原 30＋终止/属主读 8：端口证明、unknown 保票据、单发/身份、票据伪造/revision/epoch、属主读严格与四类损坏、伪造证据、端口坏形状、冷恢复 reconcile） |
| `PYTHONPATH=products/agent-tools/deployment:plugins/harness/records/src:packages/backend/harness-transport/src <py> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_owner_wiring.py -q` | 15P/0F exit0（补终止端口坏形状两例） |
| records 包导出 import 核验 | exit0，`NativeTerminationEvidencePort`/`TerminationRecordTicket`/版本常量齐 |

C：真实临时 SQLite＋受控端口；P/M 无。未验证：三家实现 stop/release 消费此面（等 AgentLifecycle 接缝）、真实终止效果证据端口的生产实现、释放语义与 Usage 转移（生命周期切片）。失败账：一处测试侧 mappingproxy 序列化（用库内 canonical 归一化修正），断言未放宽。
