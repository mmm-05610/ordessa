# T012-04 干净 venv wheel 导入与 bare host（2026-01-04 夜班实测 ✅）

| 步骤 | 结果 |
| --- | --- |
| wheel 构建（--no-deps，6 包） | ✅ pacthold 2.0.0a1、ordessa-server-plugin-api、ordessa-environment-api、ordessa-persistence-sqlite、ordessa-platform-services、ordessa-server 2.0.0a1 |
| 干净 venv（python3.12，隔离安装 wheel 闭包） | ✅ 与仓库 .venv 物理隔离（系统 python3=3.14 无 ensurepip，按 baseline 的 3.12 建） |
| bare host 检查 `apps/server/tests/install/check_bare_host_wheel.py` | ✅ **BARE_HOST_WHEEL_OK imported=30 distributions=host-only**——30 模块全导入，闭包**不含** pacthold-runtime-compat / ordessa-server-product（断言拒绝 legacy 兼容链入 bare host，实测通过） |

注：首次误在仓库 .venv 运行该检查被其断言正确拒绝（runtime-compat 在开发环境属预期）——
该脚本的设计就是"必须跑在裸 venv"，断言拒绝开发环境是其正确行为。

待续（T012-04 余半，命令可达）：独立 extension build、deb 生成/解包/无凭据 clean smoke、
打包检查不签名/publish（本轮 deb 生成见后续提交追记）。
