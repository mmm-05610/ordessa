# runtime-compat 盘点报告（只读侦察，2026-09-29）

## 一句话定性

**名字叫 compat，实际是还在承重的平台水电层。** 真正可"死亡"的部分很小
（两个死码模块 + 两条旧时代迁移）；大头（storage 71 处消费、
resource_contracts 49 处、runtime_composition 27 处）是被全仓踩着的承重件，
其清理不是"删旧码"而是**平台层归位的架构搬家**。总计 5481 行 + 9 条 SQL。

## 模块分类账

| 类别 | 模块 | 外部消费 | 处置 |
| --- | --- | ---: | --- |
| **死亡候选（死码）** | sandbox/ | **0** | 直接删（唯一零消费模块） |
| | cli/ | 0（仅 pacthold docstring 提及） | 删前核 pacthold CLI 是否引用其入口 |
| **真遗留（裁窗口即死）** | legacy_migrations 中 001/002（agent-box v2 schema、claude_md_ref 改名） | apps/server 启动注册 5 处 | 随"迁移窗口截止"裁定死亡；启动注册段同批摘 |
| **承重件（搬家 epic）** | storage/（database.py 792 行） | **71**（server 31/assets 22/server-compat 12/products 2） | 全仓共享数据库层——归宿裁定：pacthold 内核持久层 vs apps/server 自有（pi 裁） |
| | resource_contracts/（≈1053 行） | **49**（harness 23/assets 8/server 7/server-compat 6） | 运行时资源契约机制——归宿：平台契约包（harness-api 同族）或 kernel |
| | runtime_composition/（protocol/sandbox_port/coordinator ≈1089 行） | **27**（harness 16 为主） | harness 主消费——归宿：harness 域或平台契约包 |
| | capability/ ≈969 行 | 3 | 随 resource_contracts 同裁 |
| | credentials / profile_envelope / api | 各 1-4 | 逐个随宿主域走 |
| **种子注入（架构裁定）** | bootstrap/ + catalog/ | kernel docstring 明文期待它注入 | 二选一：kernel 内置基础契约，或 products/server 装配时注入（pi 裁） |

## 迁移链定性（重要修正）

9 条 SQL 里只有 **001/002 是 agent-box 时代遗留**；**003-009 是现行 schema 自己的
演进史**（Work Core v0.1 → 资源契约输入 → 观测账本 → 证据元数据 → 执行收据
原子化）。`legacy_migrations` 是历史误称——它是**产品 schema 版本链**，搬家
正主是 kernel 或 apps/server 的迁移面，不能随"遗留窗口"一起死。

## 波次建议

- **波 1（小刀，随时）**：sandbox/、cli/ 死码删除；001/002 + 启动注册段
  随窗口裁定死。半天量级。
- **波 2（搬家 epic，量级 ≥ 017）**：storage / resource_contracts /
  runtime_composition 正名归位——依赖 pi 的两顶架构裁定（storage 归宿、
  种子注入归宿）。与 017 W-2/W-3 可并行推进。

## 需要裁定的两件

1. **迁移窗口截止口径**（你）：只影响 001/002 与启动注册——"从某版本起不再
   支持从旧 agent-box 数据目录直接迁移"。
2. **承重件归宿**（你 + pi）：storage 归内核还是 apps/server；种子注入归内核
   还是装配侧。这决定波 2 的形状。

## 结论：什么时候能"清干净"

名字消失的最早现实时点 = **波 1（随时）+ 波 2（pi 裁定后一个波次）**，
与 017 收尾可同期。但波 2 本质是"平台层归位"的 epic，不是删码——
建议把它当作 017 的姊妹篇立项，而不是退休尾巴。
