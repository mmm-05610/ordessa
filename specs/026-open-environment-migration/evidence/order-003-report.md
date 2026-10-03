# 003 证据 — 空环境与中性对象模型

2026-10-03。前序：002@8155d4b1a5。交付物：`packages/pacthold/src/pacthold/environment.py`
（`pacthold.environment.Environment`，经 `pacthold.public` 导出）+
`packages/pacthold/tests/environment/test_empty_environment.py`（11 测试）。

## 任务对照

- **T003-01** environment-api 独立 pyproject/stdlib 契约：002 已建（`packages/backend/environment-api`，
  dist `ordessa-environment-api`）；本单验证 pacthold 发行/import名不变（`pacthold` 2.0.0a1），
  `public.Environment` 链 = core.registration + environment.py + ordessa_environment_api，零业务/零具体 Store。
- **T003-02** 唯一索引归 root：installations/enabled/activations（plugin+generation）/instances/
  capabilities/objects（owner_instance+owner_generation+object_id 全键）/activities
  （env_namespace+principal+request_id）/usages 全部为实例级 dict；完整身份不匹配 →
  `IdentityMismatchError`（测试 test_object_identity_requires_the_full_triple：错 generation/错实例/
  错 environment 三反例）。
- **T003-03** 复用 core registration：activate 直接走 `CoreRegistry.stage/commit`（冲突 typed、
  staged 不发布；快照不变反例 test_registration_conflict_publishes_nothing）。纯 query/static 能力
  （合同目录）不建 ExecutionPlan。
- **T003-04** 显式空启用集：`enabled` 初始空；install ≠ enable（test_installed_is_not_enabled）；
  未启用 activate → `AdmissionRefusedError`；lookup(mode="history-read") 与 use/invoke 分离
  （test_history_read_and_invoke_are_separate_permissions：retired 后 lookup 可、use/bind 拒）。
- **T003-05** 隔离 wheel/venv：
  `pip wheel --no-deps -w /tmp/oe-wheels packages/backend/environment-api packages/pacthold` →
  两个 wheel；fresh venv（/home/maoqh/.local/bin/python3.12 -m venv /tmp/oe-isolated）+
  `pip install --no-index --find-links /tmp/oe-wheels pacthold` → `Environment('iso-wheel-env')` 启动
  只读成功，sys.modules 零产品模块，api 来自 site-packages（非 repo/editable）。exit 0。
  反例注入：①核心反向 import——n4r1 守卫自带 tripwire（植入 `ordessa_server` import 必红，通过）；
  environment-api 侧零 host import 测试禁 `pacthold`（002 套件）。②第二 root——两 Environment 不共享
  索引（test_two_environments_share_nothing）；同数据根单 writer 排他是 005 Store 层 fence（C2），
  本单如实记录边界。
- **T003-06** 公开入口与实例 identity：`pacthold.public` 新增 `Environment/EnvironmentClosedError/
  InstallationRecord`；无模块级 registry（全部实例字段；跨进程=无共享）。004/005 同 root 消费接口：
  构造参数 `store: StorePort|None / policy / fingerprint_port`（002 冻结 Protocol），004 在其上加
  drain/retire/关系门，005 注入持久实现。

## 门对照

- G003-1：Environment('x') 无 Server/Harness/Profile/SQLite 依赖启动只读（in-tree 子进程测试 +
  隔离 venv 双证）；reliable 缺 Store/FingerprintPort → `GuaranteeUnavailableError` 发前拒、
  零活动记录（test_reliable_...断言 query None）；raw 不受影响。✓
- G003-2：001@51889021a0 + 002@8155d4b1a5 同树 SHA；S/I 证据=本文件+台账。✓
- G003-3：pacthold 229 passed（218 基线 + 11 新，0 删除）；n4r1 守卫 3 测试经 allowlist 修订后仍红-
  感知（tripwire 通过）；无新增未解释红。✓
- G003-4：无凭据/用户数据/binary；/tmp 隔离 venv/wheel 属受控 fixture。✓

## 守卫修订记录（不删断言）

1. `test_public_contract.py`：facade 链允许 `pacthold.environment`（原 core-only）；新增产品前缀
   禁入断言（public/core/environment 链禁 ordessa_server/ordessa_harness/compat）——加强非放宽。
2. `test_n4r1_kernel_direction.py`：`ALLOWED_MODULES={ordessa_environment_api}`（合同包在内核之下，
   stdlib-only 自带门）；其余 ordessa_*/plugins 前缀全禁不变；tripwire 保持。
3. `pyproject.toml`：pacthold dependencies += ordessa-environment-api（本地 dist，006/012 同步
   安装清单与 deb 闭包）。

## 命令与结果

| 命令 | exit | 结果 |
| --- | --- | --- |
| `.venv/bin/python -m pytest packages/pacthold -q` | 0 | 229 passed（GREEN_NO_SKIPS） |
| `.venv/bin/python -m pytest packages/backend/environment-api -q`（PYTHONPATH 注入） | 0 | 33 passed |
| 隔离 wheel 构建+venv 安装+启动 | 0 | ISOLATED_BOOT_OK，零产品模块 |

## 边界与缺口（如实）

- drain/retire/reply/subscribe 交付面属 004（本单仅 mark_retired 历史化转换供测试）。
- C2 同根 writer 排他未实现（005）；in-memory 环境重启不保历史（合同允许：缺持久实现拒该保证）。
- invoke 的 handler 分发为中性占位（ActivityReceipt 恒 concluded）——004 接真实 dispatcher 时替换，
  不伪称已执行外部效果。
