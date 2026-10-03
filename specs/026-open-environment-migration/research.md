# 现状与复用依据

2026-10-03只读检查：main HEAD=b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0；产品树 worktree/021-ordessa-product-closeout HEAD=7951bf06a258d2dc41402556eb61319b8bab5cbe，存在未提交源码、测试和清单。main .gitignore为用户改动，024/025设计未跟踪。此处不是已验证产品运行基线。

源证据：024/inventory、evidence/migration-seams；025/inventory、state-ownership；两模型最终修订优先。旧baseline/AGENTS关于Profile外仓及测试计数已有漂移，不能照旧文档把现有功能排除。源归属冲突由001记录给用户，不自行覆盖规则。

## 复用映射

| 来源 | 目标/动作 | 必须验证 |
| --- | --- | --- |
| desktop-platform/extension-api | frontend/extension-api | Token identity/exports |
| extension-loader + extension-host | frontend/extension-runtime | 保Lumino发现校验和唯一激活；loader不另registry |
| contracts/foundation | frontend/contracts；领域carrier迁Agent | 共享载体不复制，领域不反向export |
| ui/ui-components/connections/bridges | 同名frontend子包 | 公开api/native main隔离、connector消费 |
| packages/workbench + app settings/overlay | frontend/workbench | 展示注册归一；值不进入Workbench |
| Pacthold core runtime/dispatch/providers | backend/pacthold | 保execution/resource机制，扩Environment而非重写 |
| Pacthold具体CoreStore | backend/persistence-sqlite | 抽StorePort；具体构造不反向export到核心 |
| ServerPluginHost依赖、stage/commit/holds | Pacthold participants/capabilities/lifecycle | 单revision事务发布与收尾范围 |
| Server CoreBinding/legacy binding | 注入同Environment的过渡facade→删重复root | 不建第二Runtime，不配global core_db |
| HTTP/stream/wire/auth | apps/server + transport契约 | 保签名/auth/origin，索引只投影 |
| Harness start/connect/close/history | 保原生机制，适配Participant/Surface | native session≠channel≠Activity；历史不授控制权 |
| compat work_core/sidecar/tracker | 新调用转环境，旧数据只读decoder | 无新旧执行双写，旧退役worker不复活 |
| Profile selection/glue | 目录+薄操作贡献 | selections/lastConfirmed/bindings/clickQueues不再主写 |
| Model next-turn-client/chat-api-entry | codec+操作贡献 | pending/queued/current/route不再独立主写 |
| Chat DraftStore/AgentSession | 域owner+稳定draft/target | 按revision消费，不文本相等清空 |
| build/test/product/packaging脚本 | 路径与装配同步 | 不是只改tsconfig，需deb/wheel隔离导入 |

不新增外部依赖实现这些已有机制；新引入第三方包须单独许可/锁定/出处评审。本轮不开展泛开源搜索，避免把整仓迁移变成组件替换项目。

