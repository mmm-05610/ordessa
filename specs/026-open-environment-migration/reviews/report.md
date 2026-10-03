# 方案攻击与修订报告

2026-10-03。审查对象：026 Spec Kit，非生产实现。三个代理未参与初稿编写，仅只读返回攻击；主会话唯一方案写者。修订后由同三个原审查者逐项复核，不声称是未见过旧稿的第四人完全独立证明。

## 第一轮：19项原始问题与处置

| ID / 级别 | 初稿反例（保留） | 修订位置与验收 | 复核 |
| --- | --- | --- | --- |
| ARC01 P1 | 换socket/logical ID可同native session再开writer绕unknown | E2 alias，T010-09，A55 | 设计闭合 |
| ARC02 P1 | 未知delivery role只raw展示，旧idle解除范围退出 | E2未分类义务，T007-09，A56 | 设计闭合 |
| ARC03 P1 | frontend preflight跨await出现新dispatch/required publish，撤必需owner | E2 admission fence，T008-08，A57 | 设计闭合 |
| ARC04 P1 | 新observer seq/not-found冒native revision，PID复用解除unknown | E2三序号/RecoveryBinding，T002-08/T007-09，A58 | 设计闭合 |
| ARC05 P1 | 新配置owner正确但旧ACP client runs/firstSends仍独立解锁 | E2 connector逐字段迁移，T010-09，A59 | 设计闭合 |
| ARC06 P2 | backend保未知payload但Desktop SDK过滤丢，fixture直连仍绿 | E2实际SDK穿透，T009-01，A60 | 设计闭合 |
| ARC07 P2建议 | 三品牌都通过但resolver硬编码第四Agent无法公共接入 | E2独立第四Agent，T007-09，A61 | 设计闭合 |
| SAFE01 P1 | native已接纳，跨库journal未保存请求关联，重启丢查询ID | C2mapping-marker-intent顺序，T011-09，A49 | 设计闭合 |
| SAFE02 P1 | 同根旧writer暂停，新writer超时抢claim，旧进程恢复双发 | C2同根排他，T005-09，A50 | 设计闭合 |
| SAFE03 P1 | reliable unknown同K显式切raw/换generation绕spent | C2稳定key，T011-09，A51 | 设计闭合 |
| SAFE04 P1 | 附件指纹A，await后native读被替换路径B | C2不可变内容，T011-09，A52 | 设计闭合 |
| SAFE05 P2 | 批准manifest源码A，导入变化B或越界链接 | C2不可变源，T001-07，A53 | 设计闭合 |
| SAFE06 P2 | 旧key缺失/正文过期清墓碑，旧K再发或已知事实退unknown | C2墓碑/独立读，T005-09，A54 | 设计闭合 |
| EXEC01 P1 | 005删CoreStore public后Server红，无写权又要等006 | 005同步consumer/工厂范围，T005-09，A62 | 设计闭合 |
| EXEC02 P1 | 合同/路径迁移缺root/CI/scripts/packaging必要写权 | 002/006/008/012显式写权，migration-map与Scope | 设计闭合 |
| EXEC03 P1 | U/P缺授权使后序纯编码/打包无法ready | plan codeReady-SI与fullDone，所有依赖+registry，A63 | 设计闭合 |
| EXEC04 P1 | deb缺required wheel但服务健康，源码能聊包里不能聊 | shipping实际闭包/解包两轮，T012-09，A64 | 设计闭合 |
| EXEC05 P2 | static内部fixture冒外部包，三个样例未全独立构建 | E2/shipping三外部产物，T007-09/A61 | 设计闭合 |
| EXEC06 P2 | Python/Go/install/独立rig未发现，root测试绿覆盖不足 | 001发现矩阵、shipping，A65 | 设计闭合 |

第一轮13项P1、6项P2（含1建议）均保原级别，不按修复后好评降级。第一轮是方案反例，不是假报已经复现生产故障。

## 复核返回

- 架构代理：ARC01–07原反例文义闭合，无新增阻塞；提醒把A60显式接T009-01，已补。
- 安全代理：SAFE01–06设计及可派验收闭合，无新增阻塞；追加同inode改写/截断与decoder卸载+history-read权限组合，已补A52/A54。
- 执行代理：EXEC01–06主要反例封堵，静态核对12工单/96唯一任务；指出独立rig实际路径tests/integration/acp-connector及S6前置文案歧义，已核源码并修。

## 本轮能证明与不能证明

能证明：方案有分层职责、合同、依赖、明确任务/反例/缺席规则；针对上述19种错误实施路径已有必须满足的规范与验收。设计结构校验通过且6种缺陷变异被拒。

不能证明：实际数据迁移、跨进程排他、native关联、IPC隔离、GUI、三品牌真实聊天、发行闭包实现已经符合。所有这些在001–012尚NOT_STARTED，不能用文档review绿替产品绿。

## 原始依据

024后端V3及025前端V4最终修订、两树source库存；执行代理核源码CoreBinding旧构造、CI旧路径、deb skip required风险与ACP client剩余状态。review不改这些原实现，本轮不运行生产构建/模型、不修改服务、未Git提交/push。
