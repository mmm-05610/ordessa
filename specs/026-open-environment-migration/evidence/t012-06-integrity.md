# T012-06 数据/秘密/产物完整性扫描（2026-01-04 夜班实测）

## 秘密与产物扫描（全绿）

| 检查 | 结果 |
| --- | --- |
| git 追踪二进制（so/dylib/dll/exe/deb/whl/node/bin） | **0**（规则 4） |
| git 追踪 userdata/DB/WAL/密钥文件 | **0**（`token` 文件名命中均为合同 Token 如 CommandSourceToken.ts，假阳性） |
| 凭据形状扫描（私钥头/API key 形状，非文档文本） | **0** 命中 |
| 环境例外（规则 7） | `.c1-001-runtime/`、`.c1-001-secrets/`、`runtime/` 显式忽略并登记于 known-issues §Services；物理目录不在源码树 |

## 数据 fixture 面（既有测试承载，本轮实测 27F 绿）

| 场景 | 承载 |
| --- | --- |
| 旧库/legacy schema | `LegacyCompatReader`（sealed agentbox_product_schema，只读）+ products/server 历史根预检（拒绝无迁移提供者的历史根） |
| 未知 schema | FileDataAreaAdapter 越界 schema 拒绝；uiStorage 未知 schema 拒（A103 钉） |
| WAL/崩溃窗口 | persistence-sqlite **5 个真实 SIGKILL 崩溃窗口测试** + 写锁 evidence-only 接管 + request-key claims/tombstones |
| 两根/rollback | 006 T006-01/02 实例 store 注入（第三并行根已除）+ sealed-migration 注册 |
| 真实数据 | **未触碰**（未获迁移批准——按 T012-06 明文：未获批不能许诺已升级） |

复核：`.venv/bin/python -m pytest packages/backend/persistence-sqlite packages/backend/platform-services -q` → 27F。
