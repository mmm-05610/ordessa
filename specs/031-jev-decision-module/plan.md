# 实施计划

## 基线和授权
本包只授权设计。设计参考根树b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0与Agent树
9e1a6db19bd54df5d6508eaa71098ca96b59bcd9，后者工作中前进到577014c450b275faaf35d1e9c4b6cdbf9b6183de。
实施前主执行者记录真实HEAD/status、现有会话写权、baseline/known issues、相关源码摘要，
由用户确认准确实施树/基线，再进行安装或实现。不自动在main落代码、不抢占正在工作的树。
不能以设计参考SHA为已授权实施baseline，也不能覆盖旧Spec/账本。

## 阶段
| 阶段 | 任务 | 进入条件 | 可独立验收 |
| --- | --- | --- | --- |
| P0 | JD001 | 实施/安装授权明确 | 固定基线、版本锁、公开接缝映射、真实候选兼容试验 |
| P1 | JD002 | P0记录完整 | DTO/codec/ports、schema向量、排他终态 |
| P2 | JD003/JD004 | P1合同冻结 | 图运行器与Jev提供者可在互不重叠目录并行设计实现 |
| P3 | JD005/JD006 | gateway/契约可用 | 任务准入与选择/组合业务代码，共享build串行整合 |
| P4 | JD007/JD008 | 只读缺口已具名 | 公开评估接缝与证据/adapter，先接口后消费者 |
| P5 | JD009 | 前项完成或缺口登记 | 离线例子、可选CLI、真实只读核心和受控纵向验收 |
| P6 | JD010 | 机制验证通过+另行授权 | 真实Jev领域评测，费用/隐私/中文质量报告 |

若P4公共只读接缝暂时未落地，继续离线/已有节点只读路径，create/reconfigure真实验证记PARTIAL，
不能把fake替代为产品成功。P6缺授权不会阻塞P0–P5可独立工作，但整体liveValidated不能报完成。

## 分工与写权
一名主执行者拥有契约裁决映射、组合根、Git、共享public/build/pyproject/locks、tasks和status。
最多3个设计/实现子代理，深度1；接口先冻结，子代理不得更改shared DTO、账本、Git或扩大范围。
P2可并行runtime与providers/jev；P3可并行task_gate与selection/proposals；
P4公共核心接缝属于原核心一位owner，adapter消费者等接口冻结后再接，不能跨树并发写核心。
测试/安装共用环境时串行，子代理报告由主执行者实际复跑。

## 依赖和安装
目标包独立Python发行；base含锁定pydantic-graph运行依赖，jev extra含官方SDK，
ordessa extra仅adapter所需公开包。contracts子模块可导入而不初始化网络/图/核心。
GraphBuilder实际发行版本、SDK0.7.2发布哈希与依赖闭包须JD001验证；
模型暂拟jev-1.13.0，不能latest自动降级。Python目标3.12，包最低>=3.10。
候选不满足API/取消/重试行为时停止受影响路线，先推进契约/业务fake测试，
报告缺口，不静默回到自建执行器。

## 兼容与回退
新增可选模块，不迁移/改写现有Profile和session数据，不修改默认产品启动路径。
回退是产品撤去可选decision装配，不删除Agent/Profile/运行记录；未决原生操作仍原机制核实。
记录仅决策证据、schema version独立；不存在新后台dispatcher和自动resume。
公开只读评估新增版本契约，不改现有prepare/apply语义，不 revive legacy compat。

## 检查点与完成
每阶段记录代码SHA、命令、退出码、计数、场景ID、缺口、授权、预算与清理。
检查点不是停工指令；局部阻塞推进明确不依赖项，不越权安装/调用模型/重启服务。
codeReady、offlineVerified、coreReadOnlyVerified、liveJevValidated分别记账，不能互相替代。

