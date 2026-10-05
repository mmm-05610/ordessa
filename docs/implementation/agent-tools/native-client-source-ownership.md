# 三家产品协议副本退出（PARTIAL）

日期2026-10-05；前置471cf57ec1e6d6b1f2e9938fcc6bfcb3f9a8eb84，clean。主会话唯一源码/Git/测试/账本作者；au003_codex、pi_ownership_audit、claude_ownership_audit仅只读盘点，各自未测试/写文件/Git/开代理。保留先前三家真实修复，未改AU合同。

## 迁移证据

Codex独立client保留initialize/thread create/resume/turn/事件与反向请求/approval/cancel/command/typed error，已增强串行锁、原native ID/journal write barrier、immutable prepared frame、lease ACK及unknown fence。Pi独立client保留原RPC全部方法，增强unknown输入门、settled前unknown、原帧一次消费/guard，provider/lifecycle继续原Invocation/UnitRecords。Claude产品客户端与独立stream_json除运输import完全相同，独立包另有显式SDK/fence/provider/lifecycle。没有机械复制后宣称生产可用。

删除三个产品协议文件codex.py/pi.py/claude_code.py，不留兼容导出。五个产品重复测试已完整迁至独立包：Codex27、Pi process15/guard12/client12、Claude16，共82函数；主会话AST核81函数原测试体一致，唯一Pi guard旧“unknown后允许raw prompt”已由此前检查点中的更强“禁止raw input、保持get_state原响应/sent数量”替代。不是为了通过测试撤掉断言。原完整源/测试SHA、对应函数路径见[evidence/agent-unit-model/native-client-ownership-migration.json](evidence/agent-unit-model/native-client-ownership-migration.json)，Git基线可恢复历史源。

独立Codex测试ScriptedChannel.next_message曾延迟导入产品Message，改为原共享ordessa_harness_transport.Message，全部原测试断言保留。产品init文档标明余七家是未启用暂存材料，公共运输/_http/_acp保留。主会话复核19个保留源/测试SHA全不变；CLI wheel继续排除整个native_clients，不使七家成为可用产品能力。新增源码边界门先核三家源/provider存在，再拒绝源码与测试导入product，含3条植入import正反例；核七家与运输资源存在，缺席即红。

## 主会话串行验收

PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python，所有句柄terminal，未出现pytest失败。全部是C：结构/受控协议/实际Python pipe/HTTP，不是原生Harness P或模型M。

- `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src PY -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q --tb=short`：166P/0F exit0、2.14s。
- `PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src PY -m pytest -c plugins/harness/pi/pyproject.toml plugins/harness/pi/tests -q --tb=short`：213P/0F exit0、3.19s。
- `PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src PY -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q --tb=short`：149P/0F exit0、7.84s。
- `PY -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_agent_unit_source_ownership.py -q --tb=short`：7P/0F exit0、0.13s，新增7项源码边界门。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/native_clients -q --tb=short`：113P/0F exit0、25.92s；七家/运输原测试，不因三家去重删除其验证。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`：9P/0F exit0、7.87s。fresh source/wheel/fresh venv独立CLI四管理命令、真实Core/SQLite＋受控ownerHTTP仍正确。native_clients全部不在wheel。

五AU工单strict、diff-check与19保留文件hash检查exit0，只是结构/源码门。未修改core/server/三家协议实现，不沿用上轮Core269P/3F成新绿；既有三个kernel_direction问题仍登记。源码搜索同时发现历史旧工厂/桥/Server路径仍存在，不能只用零命中产品副本声称AU003完成。

## 不可无声删除的旧资源与下一步

旧大包三家的生产/profile/附件/配置/原file dialect/模板/恢复能力仍有消费者，独立包未完整承接，不能整目录删除或转成兼容shim。Claude attachments、instance model/endpoint/credential/restart-resume、ACP deployment；Pi native model/settings/dialect、model-provider/ACP context/projection/session scanner；Codex旧account/artifact/configuration/continuation能力均另需核对。其他permissions/subagents/runtime-preferences中的品牌adapter不是产品协议副本，不误删。

旧pyproject已无三家自动entrypoint，但entrypoints.create_codex/create_pi/create_claude和generic.factory.build_registration仍可直接生成旧运行时；plugin.HarnessesPlugin/create_plugin仍默认Codex，model plugin/bridge/live_service与Server composition仍聚合三家。无自动发现不证明无旁路。这些路线要单独typed退役/明确注入独立贡献并真实复验，同时保留七家过渡源与稳定标识。尚未修改用户部署或数据库。

生产capture/receipt/effect/Session/writer、显式Directory/Invocation授权、材料/SecretRef解析、冷恢复/全生命周期、节点wire/按请求键恢复、三Skill、独立包安装闭包和三家P/M仍缺。总目标/AU003均PARTIAL；M0、原生P缺席。未安装更新第三方、登录、触及用户DB/凭据/全局配置/服务、push/主树合并。费用unknown。源码去重检查点后继续旧运行时入口退役。
