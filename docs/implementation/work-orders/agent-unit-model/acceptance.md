# 验收矩阵
## 三层证据
C：受控契约/fixture；P：真实隔离进程且无模型调用；M：授权真实任务。
每家单列版本、实际选择通道、已实现方法、C/P/M、实际入口、限制。不把C当P或M。
无模型授权预算0；无Harness安装授权不安装。缺资源则对应P/M未验证、整体PARTIAL，不能用skip或mock报DONE。

## 必须反例
A01 staged不可发现，重复id/definition拒绝，无半发布。
A02 author不能伪造宿主owner/generation；drain/retire旧连接不得继续写。
A03 缺required材料发前拒绝；optional未应用显式逐项返回。
A04 prepare/start丢回执：原操作unknown，不再次创建实例。
A05 Node/publication必须依赖真实Unit绑定和证据；有记录不等于ready。
A06 same requestId不同payload或expectedRevision拒绝；同payload不重复作用。
A07 两个消费者竞争同scope不互相覆盖；外部native改动不可冒充强CAS。
A08 ACK仅接收时不报applied；延迟旧确认不覆盖新事实。
A09 多项中一项失败明确partial；不自动补偿未知副作用。
A10 restartRequired且未授权不重启；已授权也不隐藏任务/会话损失。
A11 Profile更新不自动修改实例；实例修改不自动保存Profile。
A12 connection timeout/断开不等于cancel/stop；无人审批不autoapprove。
A13 recover不使用最近会话、不重发、不创建替代；绑定不符拒绝。
A14 release不kill borrowed；未知归属不删除。
A15 CLI wheel不包含品牌客户端、服务实现或私有Harness import；三Skill与help一致。
A16 只启用一家不导入/启动另两家；每家disable不影响其他家的实例。
A17 固定配置版本/快照没有明文secret，日志/stdout/errors不泄露token。
A18 全流程至少：固定Profile→prepare→Node→授权连接→配置修改→读取确认→disconnect→明确stop/release。真实M需另授权。

## 回归
复跑核心注册/操作/节点/输入、Harness配置与生命周期、CLI契约、fresh wheel安装及帮助。记录精确命令、退出码、计数、继承红ID和新红区别。
packaging不得将环境绝对路径或损坏artifact作为通用发行默认值。
每个skip列原因；新增必要验收缺席不得DONE。

## 收口标准
代码、契约、迁移及受控测试完成可标CODE_READY；某家P/M不齐则该家PARTIAL。
整体DONE要求本包全部门、三家生产接线与用户授权范围内要求的真实证据齐全；未获得真实任务授权时不报告任务产品完全可用。
