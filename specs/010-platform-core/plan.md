# Implementation Plan: 平台核心收敛

Date: 2026-09-27 | Spec: [spec.md](spec.md)

## Summary

Pacthold 管执行/资源，Server 管插件/传输；前端保留 Lumino，Workbench 迁平台。三个会话写入互斥，通过固定提交传依赖，不通过兄弟树可变文件接线。

## Technical Context

- Language/Version: Python 3.12.14 验证，不无意抬高包下限；TS/Node 按仓库锁。
- Dependencies: 现有 FastAPI/SQLite/Electron/React/Lumino，不引入新容器。
- Storage: 实例级 Store；新表只增不删，历史 SQL/序号语义保持。
- Testing: pytest/JUnit、Vitest、真实构建、临时 Electron/Server 受控冒烟。
- Target: Linux，Windows 未测登记。
- Performance: 不宣称吞吐提升，不新增后台轮询或逐 token 核心落账。
- Constraints: 无真实模型、用户服务操作、main 实现提交、远端操作。
- Scope: 4 故事、3 实施树；平台及必要旧插件适配。

## Constitution Check

依赖方向/诚实生命周期/反例/数据兼容均有任务。起点 main cd7d31f3cf，历史计数不是本批实测。主树不切换，合并另审。

## Project Structure / Ownership

| 线 | 写入范围 | 禁止 |
| --- | --- | --- |
| A Pacthold | packages/pacthold/**；新 plugins/runtime-compat/**；reports/A.md；本线 tasks 勾选 | apps、server-plugin-api、现有业务插件、根 JS |
| B Server | apps/server/**；packages/server-plugin-api/**；products/server/**；plugins/server-compat/**、workspace/**、harness 的 Python 接入和测试；tests/acp_orchestration/**；reports/B.md；本线 tasks | pacthold/runtime-compat 手工修改；Go/JS/TS adapter；前端 |
| C Frontend | apps/desktop/**；packages/desktop-platform/**、workbench/**；plugins/workbench、commands、agent、chat、connections、connectors 内 JS/TS/API/测试/构建；products/desktop/**；tests/acp-connector/**；tooling/**；根 package.json/package-lock.json/JS 配置；reports/C.md；本线 tasks | Python、Go、其他 worktree |

共享 spec/plan/contracts/data-model/research/constitution 只读；各线只勾自己任务。确需越界报告文件和理由。runtime-compat 只承接旧 Pacthold 领域 SDK/具体组合/封存迁移，不新增业务，核心不依赖它；迁移表给每项后续领域归属。

## Dependencies & Parallel Strategy

A 先交付 pacthold.public 类型/签名与 conformance tests 的独立检查点，reports/A.md 给 exact SHA，不用成功空桩冒充实现。
B 立即做宿主清理；Core 接入等 A 固定契约提交。B 可在自己树 merge A exact SHA，确认只含 A 路径；最终 merge A 完整通过 SHA 做产品适配。禁止跟随移动 HEAD、复制 API、自行改 A。
C 独立推进，仅保持 main 现有前端链，不合 desktop-workbench 等旧树。Commands 本批不迁，只规范 API。
修订 C6：Connections 通用能力迁 packages/desktop-platform/connections；旧 Agent facade/UI 迁 plugins/agent/connections，均在 C 写入面。C 不再将整个 Connections 视为业务契约迁移；参考 contracts/connections-platform.md 和 T026–T029。不改 A/B。
根 docs/baseline、architecture 由最终集成统一更新，各线报告给建议，不共写。

## Compatibility

A 提供命名空间迁移注册，将原历史 SQL 封存 runtime-compat，字节/编号保持，新核心版本记录独立。B 默认产品显式装配旧迁移集；裸核心无旧业务表。旧 schema_versions 不删不重编号。仅测试临时夹具；必须改变用户数据格式则阻塞该项并请求确认，不造 fallback。

## Complexity Tracking

runtime-compat 是有限迁移承接，优于核心反向 re-export；不建万能 orchestrator。注册事务只管理进程内可见性，不承诺外部副作用原子性。

## C7 追加（2026-09-27）

用户确认原前端 goal 已结束，授权在 C 同工作树继续 T030–T036。起点 `865a6f57fa`；原 C 报告保留，新报告 reports/C7.md。新增 packages/desktop-platform/ui-components 和必要的产品/构建接线，详细所有权以 contracts/ui-components-platform.md 为准。主代理按原分包派子代理，不在 A/B 或 main 实现。12 个 Agent UI 接口及默认组件留后续插件批次。

## Integration / Rollback

各线阶段提交、亲验，完成报 IMPLEMENTATION_REVIEW_READY，不 push/合 main/删树。B 只可依赖集成 A；主控最终按固定 A→B→C SHA 统一集成全验。git revert 回退代码，不触碰用户数据演示回滚。
