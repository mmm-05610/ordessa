# Ordessa Constitution

Version: 1.0.0 | Date: 2026-09-27 | Scope: 本批平台收敛

## Core Principles

1. 领域独立、机制共享：Pacthold 不依赖 app/product/plugin；宿主不识别品牌/Profile/模型。插件仅消费公开契约。搬目录同时消除语义、包依赖和反向 re-export。
2. 诚实生命周期：Server 管插件，Pacthold 管执行/租约，Host 管贡献，Workbench 管布局。一个进程一个终止责任方。Execution 终结不可恢复；unknown 不冒充已取消或清理；清理异常不覆盖主因。
3. 契约先行：声明依赖、版本、所有权和缺席行为。禁止复制 Token、自造跨树 API、全局业务 service locator、隐式启用所有已安装插件。空宿主有效。
4. 证据不假绿：守卫必须有反例；收集错误算失败；继承红按 ID/原因而非仅数量比较。迁测试保留映射。受控验证不冒充真模型。
5. 安全与回退：保持持久 ID、磁盘格式和协议；真实数据迁移另批。无模型调用、凭据入库、用户服务启停、远端操作。根工作树保持 main。

## Development Workflow

采用 Spec Kit 的 spec → research/plan → data-model/contracts → tasks → analyze → implement/converge，不采用派工单订单/轮询体系。
用户已批准准备本批方案与多个 Qoder 工作树；本批从已合并核心 main `cd7d31f3cf` 派生，替代最初迁移提交的分支起点，仅适用于本批、不重定义历史基线。实现合并仍待审核。
主会话管边界、审阅、复验和 git 检查点；实施可派单一包子代理，不共写文件、子代理不操作 git。小实现问题自行解决；改变契约/数据/安全语义上报，仅暂停受影响任务。

## Governance

共享 spec/plan/contracts 是只读输入；各线只勾本线任务并维护本线报告。阶段提交是检查点而非停止条件。本线全部完成后报待审并停止，不无限空转。不自动合并 main、推送、删除工作树。本文件整理既有规则和用户决定，不扩大权限。
