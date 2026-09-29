# 017 · server-compat 退役总纲 实施规格

状态：**设计稿待用户审（2026-09-29）**。目标：`plugins/server-compat` 整目录消失，
其承载物按"死亡 / 毕业 / 迁移"三途分流，全程无双写窗口。

## 背景一句（实测底）

server-compat 不是薄过渡件——它是**老服务端兼容城**：19 个模块；`core_wire.py`
2181 行、`composition.py` 1364 行；`accounts/sessions/approvals/assets/execution/
usage_aggregate/hooks/http/persistence` 等业务域本体住在这里（apps/server 是薄
宿主，零业务域模块）；products/server 装配直接 boot `ServerCompatPlugin`；
92 个测试文件消费它。退役=三波分流，不是一次删除。

## 三波结构

| 波 | 内容 | 写入面 | 前置 |
| --- | --- | --- | --- |
| W-1 写入链死亡 | S-08①③ 落地：`model_configs` writer（W1-W15 清单）+ `server_profiles` writer（R10）；同批边界断言更新 | 本插件目录（apps/server 断言侧=AR 转 core） | consolidation 后集成窗，先于 core 的 S-03 装配 |
| W-2 组装与冻结面迁移 | `wire_validators`+core_wire 冻结清单→apps/server/wire（core 侧）；`composition`（native/sidecar 组装）→归宿裁定后迁移 | 迁入侧为主（core seam），本侧只删 | W-1 后；pi 排期 |
| W-3 业务域毕业 | accounts/sessions/approvals/assets/execution/usage/hooks/http/persistence/facade 逐域：死件删除 / 活件迁正主（**域归宿总方向待用户裁**，逐域映射表见 plan） | 逐域各归其主 | W-2 后；每域一_wave |

## 成功条件

- 目录删除后：products/server 装配线不 import `ordessa_server_compat`、
  pyproject 依赖摘除；92 个测试逐一定向（跟域走/compat 回归退役/重写），
  无整批跳过；known-issues 登记每域去向与残余风险。
- 全程无兼容双写窗口（W-1 与 S-03 的锁序沿用 seams S-08 已钉约束）。

## 红线

写入面波内自持；跨侧（apps/server/products）一律 AR/IR 不代写；每波独立可验，
波间失败不谎称完成。
