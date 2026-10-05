# Claude ACP 附件工具迁移（AU003 PARTIAL）

基线 b228c0774edc46d194a8f878db264f77d96b5559。主会话唯一源码、测试、Git和账本作者；Claude审阅代理只读。旧工具活跃消费者仅旧包导出与六项能力测试，没有生产投递调用方。

原192行模块字节不变迁入独立 Claude 包 `acp_attachments.py`，无旧导出/shim；Continuation保留。六个测试保留，五项AST相同，第六项的旧生产能力声明断言独立留在原能力测试。哈希与AST收据见同目录 `claude-acp-attachments-migration.json`。新增同长度错误内容、mapping身份、bool/float/零/负长度六反例；新发行测试构建四个自有wheel并在fresh venv安装，只用no-index/no-deps，无第三方安装。验证旧Harness、Server、CLI、SDK均缺席，图片字节往返、错误hash/audio拒绝，provider默认四个纯方法、不授start。

## 实测命令与结果

解释器 `PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，前缀 `PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src`。

- `$PY -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests/test_acp_attachments.py -q --tb=short`：迁移原六项，6P，exit0，0.10s。
- 同配置，attachment与distribution两文件：12P/1F，exit1，4.65s。fresh安装继承源码PYTHONPATH，pip误将源码可见包当已有，最终隔离运行缺包。修复为安装阶段清除PYTHONPATH/PYTHONHOME/VIRTUAL_ENV并设置临时cwd；缺包断言保留。
- `$PY -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_capability_declarations.py plugins/harness/tests/test_agent_unit_source_ownership.py plugins/harness/tests/test_core_identity.py -q --tb=short`：87P/1F，exit1，1.47s。新增门错误扫描依赖原store/issuer的既有生命周期集成测试。门明确约束独立生产源码与迁移的两个纯附件测试；旧集成测试保持不变、仍在下一完整包复跑中。未删除断言或隐藏该依赖。
- `$PY -m pytest -c plugins/harness/pyproject.toml plugins/harness/claude-code/tests/test_acp_attachments.py plugins/harness/claude-code/tests/test_acp_attachments_distribution.py plugins/harness/tests/test_capability_declarations.py plugins/harness/tests/test_agent_unit_source_ownership.py plugins/harness/tests/test_core_identity.py -q --tb=short`：101P，exit0，6.15s。
- `$PY -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q --tb=short`：162P，exit0，12.69s，含原生命周期集成覆盖。快照不累加。

## 证据边界与剩余

以上为纯转换/受控owner C与自有安装进程；native Harness P、真实任务 M未执行，M0。历史 ACP 0.81.2能力声明不是当前SDK附件可用性；独立provider没有新增supported method，没有fallback/新授权/材料获取/投递链。SDK附件接线未实现。历史 `docs/server-round1/fullstack/claude-production-packaging.md:177-179` 的旧定位保留为历史记录（不属于此工单写权），当前定位以独立包README及此收据为准。旧model/Server装配与其他品牌独有能力尚未完成迁移；不能整目录删除或宣称AU003完成。继承Core三红、其他资源ABSENT及未测范围保持上一账本登记，本轮未冒全Core/Server回归。

无用户数据库/凭据/全局配置、第三方更新/登录、用户服务重启、模型调用、push或主树合并。新wheel/venv为测试临时资产，不入Git。资料门不证明产品完成。
