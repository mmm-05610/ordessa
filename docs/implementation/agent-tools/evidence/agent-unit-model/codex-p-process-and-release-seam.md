# codex 真实进程 P 序列＋store 受控释放接缝（PARTIAL）

前置 `344ba9efab`。主会话唯一共享写者；codex slice-worker 持家族写权完成真实适配器与 P 级序列（写权已释放），architecture-reviewer 第 3 次咨询（生命周期语义裁定：release 走新增受控释放接缝＋关闭 unknown→released 潜伏缺口、新增窄观察端口、apply_profile 签名、wire 门控清单），safety-reviewer 终止面审阅已在上一检查点收口。真实模型 0；无用户凭据/全局配置/服务操作、无 push/主树合并。

## codex 真实进程 P 级（零模型，家族切片）

新增 `runtime_channel.py`（真实 ChannelFactoryPort：绝对路径 `codex app-server` stdio、私根 `{cwd,home,codexHome}` realpath 同父校验、隔离 HOME/XDG/TMPDIR/CODEX_HOME＋凭据形环境键清空、managed stdin 写屏障、显式 close/kill 收回）、`projection.py`（UnitProjectionPort：只经 owner_read_* 免调用属主读、verify_preparation 密封私根、query_creation 双核 correlation）、`lease.py`（ConnectionLeasePort：opaque grant、bind 绑原 transport writer lease、revoke 全灭并 fence、entry close 只断视图不杀进程）；`tests/test_runtime_process.py` 17 项 P＋`runtime-process-evidence.md` 真实性证据。

真实证据：`codex-cli 0.159.0`（绝对路径二进制，SHA 与既有探针一致）；initialize 结果 codexHome==私根 CODEX_HOME 且经 `/proc/<pid>/environ` 核证隔离（凭据键不存在）；thread/start 回执真实 id、thread/read 回读一致、journal sessionId 与新轮回读一致；每写经 lease 在实际写屏障校验、fence 后写拒而进程仍活（disconnect≠stop）、close 退出码 0 且 `ps` 无残留；**真实丢回执**（0.001s 截止）→ journal unknown、再 start typed 拒不重发、`recover_request` 只读回收迟到原始回执并回读确认；身份篡改（伪 sourceRevision/generation/两字段引用）开进程前拒；租约借出/撤销/重绑全反例。零模型边界显式断言（turns 空、无 turn 事件、回执复检空）。

协议兼容性（如实分账）：initialize/thread 往返/错误保真/写屏障/丢回执只读恢复对 **0.159.0 P 级证实兼容**；`thread/list` 省略 params 帧被 0.159.0 拒（-32600）已登记；turn/config/stop 边缘未实测不声明。包协议仍固定 0.157.1 未擅改 pin。失败修正均工具侧（start continuation 身份面、close 收回语义、发行隔离 import 边界——projection 不 import records 以保独立 wheel 隔离），断言未放宽。

## store 受控释放接缝（主执行者；评审 3 裁定）

`record_operation_step(..., release_holder=...)`＋`_write_usages` 释放分支＋`read_usages(environment, holder_ref)`（environment-api 端口＋persistence 实现）：release 步只能携带释放变更、expected/actual holder 必须恰为 release_holder；**只有 active 行可释放**——关闭评审发现的潜伏缺口（此前 concluded 步可把 unknown 行释放掉）；unknown 结果下 released 变更仍拒；released 终态幂等重放、历史不可重写；revision/holder CAS、target/rights 不可变等既有不变量继续生效。反例 `test_usage_release.py` 6 项：unknown 行释放拒且保留占用、release_holder 身份三反例、终态＋幂等＋历史不可改写、接缝守卫（concluded/显式 holder/禁混占用）、unknown 结果下释放拒（回归钉）、read_usages CAS 投影。

## 验证（主会话串行、句柄 terminal；解释器均 .venv-ordessa-py312/bin/python）

| 命令 | 结果 |
| --- | --- |
| `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src:plugins/harness/records/src <py> -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q` | **227P/0F exit0**（210 C＋17 P 真实进程，主会话复核） |
| `<py> -m pytest -c packages/backend/environment-api/pyproject.toml packages/backend/environment-api/tests packages/backend/persistence-sqlite/tests -q` | **76P/0F exit0**（原 70＋释放接缝 6） |
| `PYTHONPATH=…codex/pi/claude-code/harness-transport/records… <py> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration -q` | **312P/0F exit0** |
| `… test_native_unit_confirmation.py test_unit_records.py test_unit_configuration_records.py test_operation_journal.py -q` | 115P/0F（含上检查点终止 8 项） |
| `<py> -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q` | 269P/3F（同三个已登记 kernel_direction 继承 ID） |

失败账（均夹具侧）：revision 硬编码改读实际 step/operation revision、UsageMutation payload 必须 Mapping、operation_ref 撞身份记录改为按 request 派生、OperationRevisionConflict 导入位置；断言未放宽、无 skip。

## 边界与剩余

C：真实临时 SQLite＋受控端口；**P：codex 真实隔离进程 17 项（零模型）**；M：0（授权已有，未调用）。未验证：pi/claude 真实进程 P、turn/config/stop 真实边缘、AgentLifecycle（评审 3 裁定已收，下一实现）、wire 生命周期绑定、三家消费终止族、旧消费者退役、任务/结果、发行与七家扩展。architecture-reviewer 累计 3/3 次达标；子代理本轮 slice-worker×1（codex P）；费用精确值 unknown。
