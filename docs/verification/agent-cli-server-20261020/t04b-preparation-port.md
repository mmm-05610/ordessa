# T04-B：preparation 解析器上提为 agents owner 共享端口（2026-10-21）

## 改动

- 新增 `packages/execution/agents/src/ordessa_agents/harness/preparation.py`：
  `PreparationResolver(*, profile_service, catalog, endpoints, authority, roots, harness_config=None)`；
  随类迁移 `_BRAND_BINARY`/`_BRAND_ENV`；`set_harness_config(providers)` 语义不变。
- CLI：删除旧 `LocalPreparationResolver` 与品牌表；改为导入共享类，注入 `roots=_session_roots(state)`；
  `LocalAgentAuthority._allow` → 公开端口 `allow(action, invocation)`（跨 owner 不再访问私有方法）。
- CLI 入口捕获 agents 自有 `PreparationRefused`（code 不变，避免丢原因文案）。
- 新增 `packages/execution/agents/tests/harness/test_preparation_port.py`（6 例）。

## 主控独立复核（实测输出）

```
grep -rn "ordessa_environments" packages/execution/agents/src      → 无输出（exit 1）
grep -rn "LocalPreparationResolver" apps packages tests            → 无输出（旧副本全退役，无别名/转发）
python_workspace.py --install                                      → exit 0
from ordessa_agents.harness.preparation import PreparationResolver → ok
  signature: (self, *, profile_service, catalog, endpoints, authority, roots, harness_config)
pytest packages/execution/agents/tests/harness/test_preparation_port.py → 6 passed
```

## 诚实边界

- `roots` 只做"批准根键→调用方路径"的绑定，解析器不读磁盘、不做路径包含性断言（用户可自选
  environment root；目录归 endpoint owner）。这是为了不误拒自定义 root，已记录。
- 依赖边未新增：agents 仍不 import environments。
- 下一步（进行中）：Server 用该共享雷与 endpoint 桥接装配 instances/native 部件，并把
  `agents.start → get/query → stop` 打到远程。preparation 是否为 Server 侧零配置可用，取决于品牌
  原生程序与配置前提（真实品牌需显式 command/env）。
