# L1 目标结构与依赖

## 目标树

```text
apps/{desktop,server}/                 可启动入口
packages/
  frontend/
    extension-api/                    声明、服务、scope契约
    extension-runtime/                发现+Lumino唯一调度+authority/scope
    workbench/                        导航/布局/视图/浮层/设置/焦点
    contracts/                        通用carrier；不反向导出业务
    ui/                               基础控件与styles
    ui-components/                    组件提供者/出口
    connections/                      协议无关本地连接
    interaction-surfaces/             输入/流/终端/嵌入式载体
    native-bridge/                    主进程broker/隔离执行合同
    server-bridge/                    wire/关联/认证主进程转送
  backend/
    environment-api/                  stdlib DTO与Ports，零registry
    pacthold/                         唯一Environment实现
    persistence-sqlite/               可注入Store实现
    platform-services/                可选文件/OS秘密/诊断适配，无治理权威
    server-plugin-api/                只transport扩展合同
plugins/                              按领域平铺，完整结构见plugin-architecture.md
products/{desktop,server}/            选版本/策略/存储/启用集
```

内部模块名可调整但职责不能合并到巨型manager。Python保留src布局与原发行/import名；上述pacthold/src中的environment/participants/capabilities/instances/objects/activities/execution/resources/bindings/observations/lifecycle/persistence为内部模块组，不是另12个发行包。Frontend保持npm root workspaces，Python每包pyproject。

## 依赖合同

- environment-api只stdlib；pacthold只依赖中性合同，不依赖Server/plugins/具体SQLite实现；SQLite依赖Ports而非runtime内部。
- server-plugin-api依赖中性contract；Server消费pacthold.public和传输契约，产品注入实现。
- extension-api不依赖Workbench/业务/Electron；runtime使用Lumino单调度，无第二loader/Workbench调度器。
- Workbench消费API/ui/components/命令公开契约，禁止加载插件、管理domain store或桥接秘密。
- connections/surfaces禁止Agent/Profile/ACP品牌字段；surface绑定只通用target/schema/来源/credit。
- native/server桥api入口与main实现分离，renderer不会因import api加载Electron或秘密。
- Agent配置/会话/提交领域服务归Agent；Profile目录与操作源归Profile；供应商目录和认证引用归Model Provider；Harness解释品牌原生行为；Chat草稿属于独立DraftOwner，非Chat edit接口无Chat硬依赖。
- 通用commands注册/执行归frontend runtime，快捷键/面板组织归Workbench，业务handler归领域；旧commands入口仅兼容forwarder。共享carrier的Token只构造一次。

E4/F4数据空间、宿主交互、秘密与诊断见contracts/platform-services.md；E5持久关联见contracts/resource-references.md。platform-services仅注入适配，不能有第二Environment/激活/退出注册表；SQLite只是可选实现。A1 Agent合同见contracts/agent-domain.md，其配置/提交字段不进内核。

## 单一权威的切换判据

E3/F3（contracts/relationships.md）强制补充受管理能力关联：注册、发现、绑定、调用、观察、Usage和退出共用同一Environment身份、准入门与StorePort；不增PluginBus/关系核心。领域owner维护业务值，Environment仅维护访问及生命周期。前端远程DomainAccess不是第二writer，Server不复制能力目录权威。新增业务协议不得要求修改内核。

注册表有唯一对象实例identity；HTTP挂载、目录/标签、compat均是带来源revision的投影，不具备另一套commit/stop/result主写。新旧facade必须引用同Environment identity，不能仅“共用数据库文件”。

同一领域target只有一个事实所有者；跨schema/major/窗口不另开写槽。runtime只登记槽，不持领域值。Confirmed/Operations属于同配置owner，Resolved为纯派生；桥可以保request→op/cursor，不能拥有pending/current镜像。

完整native别名、connector session/run/interaction状态迁移、frontend preflight原子fence、未知delivery角色义务与三序号恢复按contracts/lifecycle-evidence.md强制执行。仅改Profile/model两个store不足以完成唯一领域状态。

## 原生内部不纳管

输入入口本身可记录一次边界活动；内部工具/推理帧不强制execution。可靠提交与原生直通按合同声明保证等级，均保入口授权和不自动重发。失联不等停止。共享外部服务不归环境杀进程。

## 移动与兼容

仅移动源码时保持package name/exports/entrypoint/extension id/数据库文件标识。旧specifier只可在明确登记兼容入口上转向唯一实现，不复制Token，不反向re-export领域。物理旧底座目录最终删除；兼容契约如确需保留可在新包exports体现，每项有消费者数和退出条件。

R4替换先前保留plugins/assets路径的约束：按plugin-architecture.md领域归属迁移源码，保持发行/import/extension ID及数据身份；不是根据目录美观整体搬业务。connector与compat必须逐职责拆分，不可换目录后保留旧第二主写。
新增F5合同见contracts/frontend-infrastructure.md。extension-api发布中性工具合同，extension-runtime提供状态工厂/任务等待/UI存储协调，Workbench呈现通知进度和上下文，ui-components提供独立React选择订阅及编辑工具，server-bridge维护已授权只读投影/普通查询。领域owner持状态实例及业务值，不是runtime中央业务Store；内部state/tasks/storage/queries/editing目录不自动成为新发行包。依赖方向和原单写者原则不变。
