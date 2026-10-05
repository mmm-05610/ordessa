# 组织结构与职责

## 一个模块、六个职责单元
建议一个独立 Python 发行包，目录放在 `packages/backend/decision/`，发行名 `ordessa-decision`，导入名 `ordessa_decision`。backend 是包集合，不表示该库只能依赖 Ordessa。
第一版不把六个职责各建一个发行包；目录隔离和导入守卫足够，存在独立版本/分发需求时再拆。
业务流程通过该库公开运行入口执行；实际产品由组合根注入服务。

```text
packages/backend/decision/
├── pyproject.toml                 独立安装与可选依赖
├── README.md
├── lockfiles/                     经过验证的依赖闭包/平台标识
├── src/ordessa_decision/
│   ├── public.py                  唯一推荐公开入口
│   ├── contracts/                 M01：DTO、端口、编码与校验
│   ├── runtime/                   M02：原版图的薄运行封装
│   ├── providers/
│   │   └── jev/                   M03：官方 SDK 接入
│   ├── flows/
│   │   └── agent_assignment/
│   │       ├── task_gate.py       M04：任务边界与颗粒度判断
│   │       ├── selection.py       M05：是否委派及工作单元选择
│   │       ├── proposals.py       M05：动态配置提案与校验回环
│   │       ├── composition.py     M05：可替换的确定性参考组合器
│   │       └── build.py           业务流程定义；不在运行器里
│   ├── integrations/
│   │   └── ordessa/               M06：现有公开服务的只读适配
│   └── evidence/                  M06：安全运行记录接口与离线记录实现
├── examples/
│   ├── offline_assignment.py      假提供者、无安装/模型副作用
│   └── alternate_flow.py          证明流程顺序由外部决定
└── tests/
    ├── contracts/
    ├── runtime/
    ├── providers/
    ├── flows/
    ├── integration/
    └── acceptance/
```

上述是目标目录，不代表文件已实现。业务 flows 在运行器之外，调用方也可定义自己的可信 Python 图。示例不额外构建通用工作流语言。
`contracts` 只使用标准库；`runtime` 依赖 pydantic-graph；`providers/jev` 依赖官方 SDK；`integrations/ordessa` 是可选导入。Pacthold、Harness、Server 都不反向依赖 decision；产品组合根可以同时依赖它们。

## 依赖与调用关系
```text
主 Agent / CLI / 其他消费者
    └─ 调用决策入口（输入、可信流程、预算、服务）
        └─ runtime 执行业务 flows
            ├─ 调用 providers/jev（仅判断）
            ├─ 调用只读事实/描述与提案校验端口
            └─ 写安全 evidence
消费者收到提案
    └─ 在另一个授权边界重新检查
        └─ 现有 Pacthold Agent 服务 / 提供者完成实际操作
```
这里的箭头是调用关系，不是所有权转移。决策模块没有实例生命周期写接口，也没有执行 lease。

## 状态所有者
| 数据 | 唯一权威 | 本模块可以保存什么 |
| --- | --- | --- |
| Profile 内容和版本 | 现有核心 ProfileCatalog | 精确引用、授权快照、提案 |
| 实际配置与原生上下文 | Harness/实例提供者 | 带来源和时效的观测 |
| 节点身份和绑定 | 核心 Agent 模块 | 节点引用 |
| 权限/占用/操作结果 | 现有治理机制 | 检查结果和版本前置，不生成权利 |
| 本次判断进度 | 单个运行上下文 | 轮数、候选、反馈、终态 |
| Jev 是否收到超时请求 | 模型提供者可证明范围 | accepted/unknown 证据，不伪造“没调用” |

## 信任与生命周期
可信图是应用代码，不是安全沙箱。第一版主判断串行；并行只允许只读查询，各分支返回不可变结果，在汇合处统一归并，不同时修改共享 state。
运行时服务在组合根创建/释放；每个 run 有独立状态和预算。模型网关可以共享网络客户端，但不能共享候选、草稿、授权快照和额度。未能确认清理完成时保留清理未知，不覆盖原始失败。
