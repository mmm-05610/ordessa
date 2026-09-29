# Ordessa memory 域（015 P-B）

mem0 自托管 server 的叶子插件：compose 子栈置备与生命周期、抽取 LLM 接线、
轮次捕获管线、记忆注入管线、facet `assets.memory` 与记忆绑定预设。

- 引擎：**mem0**（`mem0ai/mem0`，Apache-2.0），本地自托管（Docker），遥测显式关闭。
  上游版本 pin 与 SHA 见 `src/ordessa_memory/common.py` 与
  `specs/015-runtime-preferences-memory/reports/P-B-memory.md`；**上游代码不入本仓**——
  置备器把 pin 的 checkout 放到产品 data-root 的 vendor 目录（仓外）再由 compose 构建。
- 数据：`.env`（随机密钥）、Postgres 数据、history、备份全部在产品 data-root
  的本插件目录下（环境例外目录），绝不入库；凭据在仓内只以引用存在。
- 抽取/embedding 属真实模型调用：**默认关**，显式授权且 model-provider 解析出
  bundled 同名 provider（openai/anthropic/gemini）才可用；受控测试一律走假
  OpenAI 兼容端点（E2），不做真实模型调用。
- 无 Docker/compose v2 前置时置备器如实报 unsupported，不用本地假实现冒充。

## 结构

| 模块 | 职责 |
| --- | --- |
| `plugin.py` | server 插件声明面：`memory.*` wire 族、`assets.memory.service` port、C2 + error-families 贡献 |
| `bridge.py` | 八品牌真实 C2 适配器（honest compile 语义见模块头注） |
| `facet.py` | `assets.memory` facet 定义 + Profile 侧注册清单（AR-5 键镜像） |
| `common.py` | 词汇表、标注行、注入块字节稳定渲染 |
| `provisioning.py` | Docker 检测 / .env 生成 / compose 子栈 / 生命周期（up/stop/health/upgrade/uninstall） |
| `llm_wiring.py` | bundled provider 解析（AR-2）与 `POST /configure` 载荷 |
| `mem0_client.py` | mem0 REST 客户端（stdlib urllib，X-API-Key） |
| `store.py` | 私有记录（绑定/捕获队列/授权/诊断），data-root SQLite |
| `capture.py` / `events.py` / `injection.py` | 捕获管线 / AR-3 事件缝 / 注入管线 |

## 测试

```sh
pip install -e 'plugins/assets/memory[dev]'
pytest plugins/assets/memory/tests
```
