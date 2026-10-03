# 后端接口问题（仅前端需求，不冻结024）

2026-10-03。024公开status在盘点；本轮不向其会话发送消息。这里每项是所需能力和缺席行为，接口名称/字段为概念，不能当已实现协议。现有I08/I09与P Profile/model接口不能证明统一链可用。

|编号|前端需要核实的问题|没有能力时|未来跨侧验收|
|---|---|---|---|
|Q01|logical/native session与owner、generation、realm的稳定身份，重启能否核对旧attempt|旧证据historical，不复用owner|旧owner退出新owner同session号不误认|
|Q02|配置证据字段known/unset/unknown、mask、可比较native revision、来源|不完整/无序证据不更新confirmed current|乱序/缺字段/同revision冲突|
|Q03|按字段patch、Profile present集合/显式unset、model原子字段组的公开解析能力|resolving或unsupported；不发旧配置假成功|不含model的Profile不清model|
|Q04|单一提交边界如何把输入/附件/配置/基底版本关联，能否冲突拒绝或发应用凭证|有配置变化且无保证则拒绝相关发送；普通raw能力单独标明|native自主更改在apply/prompt间插入|
|Q05|多字段部分应用与回执/输入拒绝如何分别观察|结果unknown，草稿保留，禁止假整体回滚|model已应用prompt失败|
|Q06|unknown操作和创建attempt是否可只读核对，同键不同payload能否拒绝|保持未知，不自动create/apply/prompt|网络断在接纳后，重启只查询|
|Q07|native自主配置变化的事件/读取是否有版本与来源范围|lastObserved标stale，不能猜当前|旧回执迟到、新观察先到|
|Q08|新draft首次发送创建前配置准备与native关联是否可统一关联|本地选择可用；首次发送明确能力不足|unknown创建后关联恢复，不创建第二个|
|Q09|原生surface capability和未知command/event透传限制，缺富展示是否可原文|有通道原样、有界降级；无通道unavailable|新增/workflow不改core枚举|
|Q10|审批/交互事件来源、interaction version和答复授权如何证明|只读未验证内容，拒绝审批|输出伪造approvalId|
|Q11|流cursor/背压/快照恢复，哪些是不可丢增量|gap+incomplete；关键事实等待完整快照|不可暂停高频输出不伪造尾部|
|Q12|领域服务停用后unknown关联/运行观察的合法继续者与清理端口|UI撤销；必需owner拒绝卸载/隔离保留恢复关联|卸载时回执/清理未知|

不提供后端任务拆分，不为024选择包结构、数据库、状态机或接口名。实施阶段需在双方明确认可的版本契约上复查；前端可以推进纯UI/公共入口收束，涉及这些保证的阶段缺能力即受阻，不能全部算通过。
