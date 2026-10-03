# Third-party notices — Ordessa memory 域

## 记忆引擎：mem0

- 记忆引擎 mem0（Apache-2.0）· 本地自托管（Docker）· 遥测已关闭。
- 上游：`mem0ai/mem0`（https://github.com/mem0ai/mem0），Apache License 2.0
  （上游 `LICENSE`）。本包 pin：commit `94c3fe9f238f3dbf29c9ce98643bd71eb13077cd`
  （main，2026-09-28 核实；对应 Python SDK 2.2.1 发布提交）。
- **本仓不含上游代码**。置备器把 pin 的上游 checkout 克隆到产品 data-root 的
  vendor 目录（仓外），docker compose 从该 checkout 构建官方 `server/Dockerfile`
  镜像；运行时的全部记忆数据留在产品 data-root。
- 遥测：上游默认开匿名 onboarding 事件（PostHog）；本包生成的部署配置强制
  `MEM0_TELEMETRY=false`，并在设置页、诊断、记忆查看界面与本文四处标注。

## Postgres / pgvector 镜像

- compose 子栈使用镜像 `pgvector/pgvector:pg17`（上游官方部署同一镜像）：
  PostgreSQL 数据库 License 下的官方 postgres 镜像 + pgvector（PostgreSQL
  License）。镜像拉取与运行均发生在用户环境的 Docker 内，不在本仓分发。

## 本包自身

- Ordessa memory 域代码：MIT（随 Ordessa 产品仓库声明）。
