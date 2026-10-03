# L0 产品结果与需求

## 目标

在不丢失现有 Pi/Codex/Claude + Profile 基础 Desktop 行为的前提下，迁为开放环境：一个后端 Environment 权威，一个前端插件运行权威，Workbench 迁到 frontend，领域事实按域有唯一所有者。外部 Agent 的完整能力通过适配与交互面承载，核心不重做其内部工作。

## 范围与非目标

范围包括包归组、公共合同、通用生命周期从 Server 收入 Pacthold、可选持久化注入、状态收束、领域消费者迁移、原生交互承载、安全入口、清单/构建/打包/CI/文档与实测。
不新增品牌，不做协作业务、工作流 DSL、外部包市场、集群内核或恶意代码通用沙箱，不重写原生审批/推理/压缩。新增通用交互和隔离必须满足合同；若无隔离不得标第三方可信执行通过。

### Requirement: R01 包组织与发行身份

#### Scenario: 目标路径
**WHEN** 在实施树构建，**THEN** 公共底座仅位于 packages/frontend 与 packages/backend；Workbench 在 frontend/workbench；旧目录无运行实现，发行名/extension id/import carrier身份不随物理目录静默改变。

### Requirement: R02 单一后端权威

#### Scenario: 多入口同环境
**WHEN** 本地、CLI、网络调用同一能力，**THEN** 进入同一环境、能力发布revision和活动事实；Server/compat不得另建运行根或主写同一终态。

### Requirement: R03 领域与原生边界

#### Scenario: 原生新命令
**WHEN** controlled native peer新增/workflow和未知事件，**THEN** 已授权交互面按合同有界传递或原文降级，Pacthold无需品牌枚举；不能因未知而将其认定为审批或终态。

### Requirement: R04 唯一前端领域状态

#### Scenario: 两种选择顺序
**WHEN** 选Profile再选模型或反过来，**THEN** 后操作覆盖它提供的字段；不含model的Profile保留model；显式unset另有语义；所有控件订阅同一配置所有者；同Profile重选产生新操作。

### Requirement: R05 可选插件

#### Scenario: 无Profile
**WHEN** 不启用Profile，**THEN** Harness会话与独立模型选择不依赖Profile身份、serializer或store；无Chat的资源/终端插件仍能接入。

### Requirement: R06 草稿、发送与实际配置

#### Scenario: 输出时选择
**WHEN** Agent输出时更改配置，**THEN** 不打断输出，下次提交冻结文字/附件/目标/操作/基底版本；原生已应用和输入已接纳分开记录。确认缺席不能伪装成功。

### Requirement: R07 未知结果与保证等级

#### Scenario: 接纳后断线
**WHEN** 发送回执未知，**THEN** 保留请求ID和草稿关联，不自动重发；可靠模式缺指纹/Store/原生必要证据则发前拒绝；普通原生交互不因指纹缺失整体禁用，也不宣称可靠恢复。

### Requirement: R08 正常退出

#### Scenario: 收尾与外部服务
**WHEN** 移除参与者，**THEN** 停新工作，允许已有责任的必要收尾；owned实例要退出范围证据，borrowed服务仅释放本方关系；未知责任不擦除，独立插件不连带重建。

### Requirement: R09 数据与恢复

#### Scenario: 历史读取
**WHEN** 原执行插件移除或恢复旧历史，**THEN** 中性历史和unknown仍可读；旧ID不自动授予新控制权；数据根/旧库/登录/草稿不静默重置。不获真实迁移许可则仅fixture验证。

### Requirement: R10 分层安全

#### Scenario: 假句柄
**WHEN** 不兼容提供者、伪scope/lease、过期代次、输出伪审批或第三方主进程模块发起操作，**THEN** 在正确边界拒绝；可信进程内插件不冒称sandbox。

### Requirement: R11 可扩展产品证据

#### Scenario: 三类外部样例
**WHEN** 独立构建Agent交互、静态资源、非Chat终端/文档三个样例，**THEN** 通过公开合同接入，不修改核心品牌分支，无需必选Profile/Chat。

### Requirement: R12 完整交付

#### Scenario: 无凭据测试
**WHEN** 无真实登录/Key/系统资产/GUI资源，**THEN** offline与controlled可继续，但相应真实验收明确BLOCKED，不冒报完整迁移完成。DONE需工单012定义全部必需场景、构建与发布前检查齐全。

### Requirement: R13 插件私有数据空间

#### Scenario: 移目录与卸载
**WHEN** 插件源码移动或停用，**THEN** 既有数据身份不变、数据默认保留；业务schema归插件，平台控制访问与迁移准入；跨插件越权或构造时静默升级必须拒绝。对应E4及A76–A78。

### Requirement: R14 保存的资源关联

#### Scenario: 资源变更与新保存竞争
**WHEN** 保存对象引用资源且目标资源同时变更，**THEN** 同Environment关系门保护双方；插件停用后关系仍在，跨库结果未知不当无引用；不能扫描Profile私有内容判断可删除。对应E5及A79–A82。

### Requirement: R15 一般宿主交互

#### Scenario: 选择返回晚于插件退出
**WHEN** 文件/目录选择或普通确认晚返回，**THEN** 已失效请求不再写业务；取消无写入，选择不授访问权，普通确认不当原生审批。对应E4/F4及A83/A84。

### Requirement: R16 秘密与诊断服务

#### Scenario: 无秘密实现或诊断失败
**WHEN** 密钥环锁定/缺席，**THEN** 相应秘密需求拒绝而无明文fallback；诊断不执行业务、不改变权威结果，秘密明文不交renderer或日志。复用已有实现，细化E4；对应A85–A88。

### Requirement: R17 插件公开边界与多入口

#### Scenario: 独立安装资源插件
**WHEN** 独立安装仅后端或仅前端的资源插件，**THEN** 按公开能力和缺席规则工作，不硬依赖Chat/Profile；逻辑清单不二次调度；品牌适配集中Harness，既有发行身份保持。对应plugin-architecture与A89–A95。

R01–R17的合同、实施阶段和验收追踪见execution-detail.md；该表不缩减case-registry中的必需场景。
