# Implementation plan

## 目标目录（只表示实际需要的模块，不建空包）

```text
plugins/assets/mcp/
  api/                 轻量 DTO、错误与可选贡献类型
  backend/             定义、版本、分配、解析、catalog、managed client/leases
  adapters/            pi / codex / claude 品牌 C2 编译与观察
  frontend/            Settings / Profile / Chat 的 UI glue
  tests/               纯解析、受控服务、双会话、权限和迁移门
```

API 可按现有 Python/TS 发布方式物理拆包，不能为了目录图让前后端互相 import 实现。Profile/Chat/Settings 可选 glue 与核心业务分 entry，避免 UI 缺席导致 MCP 后端不加载。仅业务文件进本域；产品组合只声明已有公开贡献，不新增 Server wire 分支。

## 顺序与停止条件

1. **T00 对齐接缝**：核验 main 已集成 SHA、Server contribution/port、Harness C1/C2/C4、Profile facet、Chat/Settings UI、Permission 权威与既有 credential service；逐符号列「已有/缺失/待合入」。任何接口缺失先向所有者报最小公共契约，**不**私造 host、全局 registry 或第二 secret store。
2. 冻结旧 `mcp` 资产样本、`server_assets`/Profile binding、wire 形状、摘要和回滚；迁移只搬本域拥有数据，不碰 Skills/Commands。移除 compat 的 mcp 写入路径前保证查询等价。
3. 落定义+修订+作用域解析，纯函数与数据库迁移先绿；保存不启动、启用不等于工具许可。
4. 落三品牌 matrix 的固定版本/ACP 入口受控探针，先判 lane 与隔离可行性。native C2 只编译 intent；managed 使用固定 SDK 的受限 client。对每个格子记录 observed/unknown/unsupported。
5. 接入唯一 submission gate 与 Permission；真实 native/managed 调用各有拒绝反例，无该门不开放生产工具调用。接 credential refs，不经桌面帧。
6. 增 Settings/Profile/Chat 贡献，不碰 Workbench 核心；产品装配用公开 API，卸载/缺席测真。
7. 双会话、关闭、异常、未知恢复、升级、无模型 smoke；按 verification 映射出证据。无法证明的品牌明确保留阻塞，不拿 mock 通过冒充实机或 ACP 通过。

## 并行 worktree 与所有权

独立工作树可先做定义/迁移、品牌探针和 UI，但共同契约必须 T00 冻结，且**同一文件只有一位 owner**。Server/Pacthold/Workbench 的核心任务已经并行推进，本包不得抢这些文件。`plugins/server-compat` 的删除/缩减最后做一次单 owner 整合，不让 MCP 与其他 assets 任务同时改同段 `composition.py`。品牌 probe 可并行在本域分目录写，最终 MCP owner 统一裁决 lane 与连接租约。

## 前置阻塞与退路

| 门 | 阻塞事实 | 预定义退路 |
| --- | --- | --- |
| B1 平台最终导出 | Harness C2/C4、Server/前端注册点尚是设计或未合入 | 可先实现纯定义/迁移；生产组合停，不 import 内部模块。 |
| B2 受限 tool call 授权 | Permission 跨 Harness 最终裁定与 native 拦截可能未交付 | 仅交目录管理；受控 mock 验证不能称 production。若 native 不能强制，标 unsupported。 |
| B3 Pi 受管桥 | 官方 extension API 存在不代表 Ordessa 当前 ACP adapter 暴露安全工具桥 | 固定版本探针并在 MCP/Harness 接缝实现最小桥；缺桥时 Pi 管理可用、调用不可用。 |
| B4 native 会话隔离 | Codex/Claude 全局/项目原生 MCP 可能额外加载，改配置后 resume 未证 | 受控私有配置根/严格来源试验；不成立则评审 managed lane，不静默改全局。 |
| B5 数据/凭据 | 旧资产与 live credential 引用需映射，用户秘密不可读入仓 | 合成样本先跑；实际数据迁移需要独立备份/授权，未知数据不删。 |

单品牌卡住不妨碍其他品牌完成纯模块或受控格子，但不能在整体报告写三品牌全绿。首版不做完整 MCP 协议新实现，也不顺手做 LSP、搜索、工作系统派工。
