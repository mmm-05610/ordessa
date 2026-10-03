# 独立构建与发行闭包（012必需）

## 发现矩阵（001基线，012重验）

1. root npm suite列表与每workspace实际test脚本/测试文件；
2. 各Python发行包pytest --collect-only，tests/install/external_adapter子进程干净wheel测试和现CI排除项逐ID单列；
3. tests/integration/acp-connector独立npm lock安装与suite，不混root lock；
4. Go ACP bridge按固定toolchain列go list ./...和各包go test发现/退出；可重现构建及协议受控回归，新核心依赖导致的桥安装消费变动需覆盖；
5. fixture外部插件独立build/install，不能PYTHONPATH偷渡未声明依赖；
6. Electron fixtures/GUI场景与打包门，引用旧截图不是当前证据。

未知发现/空collect必须FAIL。旧继承红分类保留，不用总数相等替case identity+cause。

## 默认发行闭包

R4 plugin.manifest.json仅逻辑装配目录，入口manifest/products仍现权威；检查logical目录、实际wheel/npm入口与所选ID/锁一致，不新增运行依赖解析器。平台可选OS/DataArea适配在所需能力启用时纳入真实产物闭包，缺required不能用源码editable补。flatten后的旧发行/import/extension ID都要在解包安装中验证，无第二Token/第二服务实例。

products选择的每个required extension/participant对照实际wheel/npm/bundle/entrypoint/lock/适配资产清单，不仅计划installed列表。environment-api、persistence-sqlite、pacthold、transport API、Server与默认Harness/已启资源及全部声明依赖必须从解包产物存在并可import。

packaging缺required目录/wheel/entrypoint即FAIL，不能skip后返回“计划全部installed”。可选disabled明确不装，enabled可选若不足则按合同typed unavailable，但不能把required默认聊天缺失当健康。

deb解包后在隔离venv与独立renderer/extension目录起默认产品：控制peer两轮聊天、配置选择、历史fixture、无Profile变体。禁止引用repo/src、editable install、开发PYTHONPATH或现venv来补依赖；测试证明真实模型未调用且发出的事件来自包内启用链。

本地deb构建不等系统安装，不签名/发布/改更新通道。真实系统资产仅获授权只读验证完整摘要；若运行必需资产非内置，发行安装机制必须明确提供/检查或可操作typed unavailable，不能README口头说用户手动补就叫开箱即用。
