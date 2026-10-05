# AgentUnit 模型与 Harness 插件组落地包
日期：2026-10-05；版本：AU-1。执行目录：/home/maoqh/.codex/worktrees/agent-tools-product/ordessa。
观察提交：3086825a6177438c042431cdb94812ded576ee6c；当时已有执行者未提交改动，本包不将这些改动视为已验收，也不要求回退。
这是用户确认后的目标设计，不是当前实现完成声明。

## 权威与顺序
本包 design.md、contracts.md、acceptance.md、migration.md 是本次增量合同。它只取代029/030中与本模型冲突的“大Harness插件、产品内品牌协议、第二份原生配置”等安排；原有安全要求仍有效。
顺序：AU001 → AU002 → AU003 → AU004 → AU005。不得与旧AT009–011或三家修复同时出现两个共享文件写者。先结束或协调现有子代理切片，再纳入本包。
保持原本工作树，不另建树、不stash、不清理执行者改动、不覆盖旧status。
执行者在自己的 docs/implementation/agent-tools/status.md 记本包接纳回执、真实工作基线、变更来源、逐单结果和费用；不要修改本包合同正文替代裁决。

## 范围
核心Agent小模块；Pi/Codex/Claude Code独立提供者；薄CLI与三个Skill；产品装配与纵向验证。
其他七家保留已有成果但不启用为已可用家族，不迁走或删除其未核对成果。
不做外置sandbox/worktree/DAG/桌面改版/新安装系统；不恢复legacy-compat。
不安装更新第三方、不改登录与全局配置、不启动或重启用户服务、不调用真实模型，除非另有明确且仍有效的范围授权。
不push、不合并主树。

## 裁决
R-3101：Pacthold唯一内核，现有注册、操作、引用、授权、使用关系与生命周期只扩展不旁路。
R-3102：Profile是配方；Node是核心身份和绑定；Unit是插件拥有的真实工作单元句柄。
R-3103：Harness是插件组，三家各自注册；品牌实现不在agent-tools。
R-3104：配置修改是授权操作；原生配置事实唯一属于实例提供者；请求接受不等于生效。
R-3105：通道逐家选型，可用ACP、官方SDK或原生接口，优先复用；无隐式fallback。

## 分工
一名主执行者持有契约映射、共享核心、产品装配、Git与账本。AU003中三家包在接口冻结后可用至多3个子代理并行；子代理不修改共享接口、公共运输、状态账，不执行Git写入，也不得再开子代理。
其他工单按共享接缝串行。检查点不是停止点；局部阻塞推进其他明确不依赖的项；全部剩余确实阻塞时才交接PARTIAL。

## 验证命令
python3 /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/work-orders/agent-unit-model/orders --strict
批末增加 --batch agent-unit-v1；只有阶段全部完成并有真实证据时才勾选。
材料结构验证不代表产品完成。
