# 015 · 运行偏好域 + 记忆补缺域 实施规格

状态：**已裁定待执行**（2026-09-28 用户确认全部裁定；设计与上游事实见
`docs/design/runtime-preferences/README.md`）。两包同批、两棵独立工作树，互不依赖
对方的产物（P-B 消费 P-A 的 memory 键仅作为 facet 契约，不消费其代码）。

## 背景一句

八家 harness 的压缩/记忆/shell/重试四组运行级参数无统一管理（机制 F×A：类型化
参数）；四家品牌（Pi、dsh、Qwen、Kilo）无原生长期记忆。本批建两个叶子插件：
P-A 把四组参数做成纯配置域，P-B 用 mem0 自托管 server 给无原生记忆的品牌补缺。

## 两包职责矩阵

| | P-A runtime-preferences | P-B memory |
| --- | --- | --- |
| 目录/分支 | `plugins/assets/runtime-preferences` / `codex/plugin-runtime-preferences` | `plugins/assets/memory` / `codex/plugin-memory` |
| 拥有 | 四组参数（compaction/memory/shell/retry）的 facet `assets.runtime-preferences`、八家品牌 adapter（assess/compile/verify）、profile 四 item、逐键 applyMode | mem0 compose 子栈置备/生命周期、LLM 接线、捕获与注入管线、第三方标注、facet `assets.memory`、记忆绑定预设 |
| 消费 | harness C2/C4（main 已有）、profile facet 形状、model-provider adapter 骨架**样式**（只仿形，不 import） | model-provider（provider 解析）、harness C2/C4、agent 域会话事件（AR-3 实测）、prompts 域 instruction facet 合并（AR-4） |
| 明确不做 | 记忆服务本体、请求级参数（归 model-provider）、管理员约束键做预设、任何内容资源 slot | MCP 工具面（后续可选）、mem0 dashboard（不起）、云平台、给有原生记忆的四家默认挂载 |

## 共同红线

1. 写入面只在自己插件目录（+ specs 报告）；不改 harness/model-provider/prompts/其他
   插件的任何文件。需要别域改动时登记 api-requests/integration-request，不越界代写。
2. 数据不入仓：P-B 的 .env、Postgres 数据、记忆正文全部落在产品 data-root（环境例外
   目录），凭据只以引用存在。
3. 真实模型调用（抽取/embedding）默认关，开启须显式授权；受控测试一律用假
   OpenAI 兼容端点（E2 模式），不得 fake green、不得删断言。
4. P-B 产品内一切记忆相关界面/诊断/清单必须标注"记忆引擎 mem0（Apache-2.0）·
   本地自托管（Docker）"，并声明遥测已关闭。
5. 失败诚实：Docker 缺失、bundled provider 不匹配、注入挂点缺失、applyMode 未知，
   一律报 unsupported/未知，不静默降级、不假装成功。

## 成功条件

- P-A：八家 × 四组参数逐格有"可用（含官方证据）/不支持（含证据）/未知"三态结论；
  facet 注册过 C2 conformance（重叠注册拒、版本区间拒）；两会话隔离反例绿。
- P-B：受控假端点下走通"轮次捕获→抽取调用形状→存储→注入块产出"全链；两 profile
  记忆命名空间隔离；服务停止时会话正常进行（记忆缺席≠错误）；标注四处可见；
  report.md 如实登记 Docker 前置与 bundled provider 限制。
