# T012-04 干净 venv wheel 导入与 bare host（2026-01-04 夜班实测 ✅）

| 步骤 | 结果 |
| --- | --- |
| wheel 构建（--no-deps，6 包） | ✅ pacthold 2.0.0a1、ordessa-server-plugin-api、ordessa-environment-api、ordessa-persistence-sqlite、ordessa-platform-services、ordessa-server 2.0.0a1 |
| 干净 venv（python3.12，隔离安装 wheel 闭包） | ✅ 与仓库 .venv 物理隔离（系统 python3=3.14 无 ensurepip，按 baseline 的 3.12 建） |
| bare host 检查 `apps/server/tests/install/check_bare_host_wheel.py` | ✅ **BARE_HOST_WHEEL_OK imported=30 distributions=host-only**——30 模块全导入，闭包**不含** pacthold-runtime-compat / ordessa-server-product（断言拒绝 legacy 兼容链入 bare host，实测通过） |

注：首次误在仓库 .venv 运行该检查被其断言正确拒绝（runtime-compat 在开发环境属预期）——
该脚本的设计就是"必须跑在裸 venv"，断言拒绝开发环境是其正确行为。

| deb 生成 | ✅ `packaging/.out/ordessa_0.1.0_amd64.deb`（EXIT=0；ORDESSA_UPDATE_PUBKEY 用 /tmp 一次性测试公钥——**私钥在 /tmp/throwaway-keys 未入仓、不签名、不 publish**） |
| deb 解包闭包 | ✅ `dpkg-deb -x` 成功；闭包含 ordessa_server/server_product/server_plugin_api/server_compat + 打包解释器；入口 `ordessa`/`acp` 在 `/opt/ordessa/bin` |
| 无凭据 clean smoke（解包载荷扫描） | ✅ 无 .pem/secret/credential 文件（`ordessa-server-credential` 为入口脚本名、`token.py` 等为 Python stdlib——均为假阳性） |

待续（T012-04/09 余项，命令可达）：独立 extension build 的单独验收、解包产物启动 smoke（需运行
环境）、T012-09 的 required wheel/启用清单逐项闭包表与默认/无 Profile controlled 两轮。
