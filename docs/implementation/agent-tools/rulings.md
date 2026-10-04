# Agent Tools 本树实施依据

## R-0001 用户本轮实施范围

2026-10-04：用户要求独立CLI＋三Skill产品；只写本实施树，其他树只读。公开核心接缝先行，客户端、Skill、测试、分发资产统一在products/agent-tools。基线SHA及切换方式必须另行确认，确认前只读盘点与工单准备。用户后续明确要求多个子代理；本轮三个子代理只读，主会话独占合同、status与Git。采用incremental-work-order的工单/证据纪律；按用户指定角色留在此树执行，不初始化主树第二调度系统或另开会话。

此条记录现有授权，不新增产品协议裁决。028 V2.1按用户指示作为设计依据；原R-1601及旧028执行包尚未同步，不能沿用冲突旧工单。基线建议尚未批准，所有单prepared，禁止执行产品改动。

## R-0002 基线及请求键口径获准

用户go批准固定adce和归档后ff-only，本树已完成且15份原材料hash未变。用户后续明确选择保留现有核心请求键：environment/principal/request-id唯一，kind/target/payload/CAS仅参与比较摘要；不按kind另派第二请求。028外树只读不改，冲突语句由本树消费合同记录覆盖，后续同步上游另行处理。

## R-0003 核心公开面薄绑定获准

用户明确选择沿用wire/1、Bearer与唯一MethodRegistry，以pacthold.agents核心owner发布agents.capabilities及agents.profiles.*；DTO直接镜像核心，schema由核心发布并生成客户端镜像。插件不能冒领该owner。CLI不注册插件、不消费profiles.v2。此裁定只批准薄绑定方向，节点、输入与原生provider仍须按028逐项落地，不能以Profile数据可读写视为运行节点可用。

## R-0004 DirectoryBinding授权来源获准

用户明确批准Workspace签发＋部署显式DirectoryAuthorityPort，缺许可或端口拒绝；Bearer和OS访问不自动变成执行授权。实施合同见directory-authority-proposal.md已批准部分。仍不改外树028材料。

## R-0005 InvocationContext授权来源获准

用户明确批准部署显式InvocationAuthorityPort，由核心结合持久step claim、可信provider身份、management epoch和Directory许可签发/重核，缺端口拒绝；Cleanup仅已取得对象的停止/核实/释放。提案见invocation-authority-proposal.md。本裁决不意味着生产authority已存在、运输fence已实现或真实模型已授权。下一步冻结具体DTO与可信验证边界并做隔离合同反例。

## R-0006 本地初始化发现请求

用户要求CLI或Skill补初始化探查系统可用Harness二进制。本单采用CLI init＋Skill指导，本机文件线索与远端Server真实provider就绪分离。授权覆盖只读本机PATH扫描、新选观察报告；不扩大为模型、登录、全局配置或安装授权。候选领域表仍由Harness public API发布。
