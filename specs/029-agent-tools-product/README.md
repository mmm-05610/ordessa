# 029 · Agent 工具产品：CLI 与多 Skill

状态：隔离工作树和基础运行环境已准备；本包是目录/架构设计，不是已实现的CLI。未启动服务、未安装Skill到用户目录、未调用模型、未修改运行数据、未提交或推送。

目标：提供通用CLI及配套Skill，供人、Agent、脚本或其他工具创建/编辑Profile，准备Agent节点，使用其原生能力并管理节点。不绑定调用者的品牌、模型或宿主。产品先交付CLI＋三个按任务划分的Skill；MCP只是后续可选入口，不是使用本插件的前置条件。

## 总体架构

```text
人 / 任意Agent / 脚本 / 其他工具
   │ 直接调用CLI；支持Skill的Agent也可读取配套说明
   ▼
Agent Tools CLI             MCP工具入口（后续）
   └─────────────┬───────────────┘
                 ▼
         Agent Tools操作层与客户端
          │管理调用             │授权原生交互
          ▼                     ▼
  Ordessa Server公开通道    Harness原生入口
          │                     │
          ▼                     │
  同一Pacthold.agents ──装配──► 原生Agent单元
          │
          └─ Harness、Skill、MCP、Prompt等叶子贡献
```

Server仍是宿主和运输入口；客户端不在每条CLI命令中创建新的Environment。Profile、节点和活动的权威在服务端，CLI不保存另一份currentModel/session ledger。原生使用保持原生协议；`run`是受控消费者的任务入口，不是新增核心sendMessage。

## 文档

- [目录与组件架构](architecture.md)：仅本产品相关的目标目录、依赖、Skill职责、调用流程，不包含Desktop和其他产品。
- [命令与交付契约](interfaces.md)：具体命令、机器输出、权限、未知与恢复、MCP映射。
- [阶段与验收](plan.md)：准备/实现/产品验证分开，明确哪些不在本轮。
- [开发环境及状态](../../docs/implementation/agent-tools/status.md)：实际工作树、基线、版本和剩余前置。

核心装配设计不复制为第二权威，引用主树已审阅材料：`/home/maoqh/projects/ordessa/specs/028-profile-harness-native-units/agent-assembly-core/README.md`。本包只设计其客户端产品消费；公开核心契约与029产品契约若冲突，先裁决并同步，不能消费者自行修补旧链。

## 基线限制

本准备树按仓库规则从 `baseline/cp-monorepo-0`：`6a3f24456130b5caad82682d692d2d198721f0a8` 创建。它显著早于当前主树和026迁移。分支不是合格的最新产品实现基线；暂只写设计/准备记录，不从活跃026摘代码，不复活旧API。实现前固定已获认可的026整合提交，并按授权更新本树基线与规则。

这是独立产品，不是Ordessa插件。CLI、Skill、测试与分发资产统一放在`products/agent-tools`，具有自己的入口、版本和安装包，不需要插件注册或激活。同仓、独立worktree，不fork整个产品；未来若拆仓，只拆依赖公开协议的薄客户端。
