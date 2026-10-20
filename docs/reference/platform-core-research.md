# 平台核心收敛：开源参考与取舍

研究日期：2026-09-27。依据官方文档阅读，非对这些项目进行本地复现或完整代码审计。下表的采用建议是针对 Ordessa 的设计判断，不是原项目对 Ordessa 的背书。

| 项目 | 参考机制 | 用在 Ordessa 哪里 | 不照搬什么 |
| --- | --- | --- | --- |
| [Eclipse Theia：Services and Contributions](https://theia-ide.org/docs/services_and_contributions/) | 服务是可消费能力，贡献点是向所有者扩展；依赖公开接口而非具体实现类 | 平台/业务各自拥有公开 API 和贡献点；Workbench 不懂贡献者业务 | 不引入 Inversify 替换现有 Lumino，不照搬整个 IDE 容器 |
| [JupyterLab：Extension Development](https://jupyterlab.readthedocs.io/en/stable/extension/extension_dev.html) | 多种基础能力也能以扩展提供；插件通过 Token 提供/消费服务；共享依赖影响 Token 身份 | Workbench 成为平台包仍按扩展加载；契约模块必须单实例 | 不再造一套前端依赖求解器，不要求所有扩展具备 UI |
| [Backstage：Backend Services](https://backstage.io/docs/backend-system/architecture/services/) | 服务引用与实现分离；区分 root/plugin 作用域，显式服务依赖 | Server 的通用服务、插件依赖授权和生命周期；删除业务门面总表 | 不把任意业务对象放进全局容器，也不机械复制其全部服务 |
| [Backstage：Extension Points](https://backstage.io/docs/backend-system/architecture/extension-points/) | 插件拥有扩展接口，扩展方无需修改宿主 | Core 贡献接缝与业务自有配置面 | 不把每个领域扩展点写成 server-plugin-api 的字段 |
| [Caddy：Extending Caddy](https://caddyserver.com/docs/extending-caddy) | 模块有明确配置/初始化/验证/清理阶段；模块拥有其资源 | 插件激活事务、验证与副作用阶段分离、清理所有权 | 本轮不做整套无缝热配置与新旧实例并存机制 |
| [Nomad：Task Driver Plugins](https://developer.hashicorp.com/nomad/plugins/author/task-driver) | 驱动管理自己的任务句柄，区分启动/等待/停止/销毁与恢复句柄 | ExecutionProvider 自身运行责任、持久句柄、恢复仍活运行与恢复 Session 的区别 | 不把所有内部资源都交内核，也不引入集群调度器 |

## 对本仓最直接的结论

1. 微内核不等于功能越少越好：必须提供足够的生命周期、贡献归属和公共服务，插件才不必互相操纵内部对象。
2. 微内核也不等于把一切纳入内核：品牌配置、用户策略、业务数据格式继续由插件负责。
3. 共同机制不要求一套跨前后端实现。前端视图 scope、后端插件 scope、执行租约是不同生命期，应通过明确接口协作。
4. 有公共接口不代表解耦完成：实例和资源的所有权、缺席行为、故障结果必须写进契约并有反例。
5. 物理目录不能替代设计。业务代码即使搬到插件，只要宿主仍识别业务字段和执行专用收尾，边界仍未完成。

## Spec Kit 文档采用方式

参考 [官方 plan 模板](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)。先写需求/验收与研究决策，再冻结数据模型和契约、实现方案，最后拆任务；不是把一个目标交给 agent 自行补出全部架构。

本文与综合方案目前属于前两步材料。正式实施包仍需补全：每个 API 的精确签名及状态转移、持久迁移协议、source→owner 清单、任务写入边界、命令与反例。未完成这些之前不宣称已经满足无人值守实施条件。
