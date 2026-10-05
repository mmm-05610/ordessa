# 三家旧自动发现注册退役：发行切片

工作基线421c1e17f101962c79287c217b109ece1fd74021，主会话独占共享写权。
按AU003/R-3103撤下原 `ordessa-harness` 发行元数据中 `agent_box.plugins` 的
codex、claude、pi三项。独立家族仍通过原Environment/CoreRegistry的显式接纳，
不新增替代发现组、不隐式启动独立提供者、不自动fallback。

保留历史发现组名称、harness-profile-store/opencode/hermes条目、声明文件及原源码；
不改provider/family/data-root/DB/部署标识，不触碰用户安装或数据库。
新wheel的自动发现不会注册这三家，但已安装旧wheel的元数据不因源码修改自动更新。
本次没有对现有用户环境安装/卸载/更新旧包。

test_retired_family_discovery.py验证真实本树源码wheel及隔离fresh venv的安装元数据，
另有改名factory/换group规避的负例。只离线安装本树wheel且不装依赖；
不导入或激活旧插件，不声称其依赖闭包或原生运行已验证。

尚未完成：显式 `entrypoints.create_codex/create_claude/create_pi`、bundle facade、
Server旧原生transport/model adapter装配及其消费者仍须迁出。原受控旧工厂测试32项
通过也证明这些路线仍存在，不能据元数据无旧注册认定运行时无旁路。
新三家生产授权与receipt/生命周期接线完成后，须逐消费者替换并验证旧路线拒绝。
产品品牌客户端及wheel边界另按AU004/AU005验收。AU003保持PARTIAL。
