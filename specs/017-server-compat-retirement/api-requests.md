# 017 · api-requests

| AR | 所有者 → 调用方 | 消费面 | 可用性 |
| --- | --- | --- | --- |
| AR-1 | core → W-1 | apps/server 边界断言更新（W/R 清单已列文件） | 清单在案，行号漂移复测后用 |
| AR-2 | core → W-2 | apps/server/wire 接收冻结清单+validators | 待 core 排期 |
| AR-3 | core → W-2 | composition 归宿接收（裁定 A=apps/server / B=products/server） | 待裁定 |
| AR-4 | core → W-2 | products/server：`composition.py:127/183/197` 切换 + `pyproject.toml:21` 依赖摘除（与装配切换同批） | 待 core 排期 |
| AR-5 | permissions/agent-sessions/work_core 各主 → W-3 | 毕业域的接收面 | 逐域波次前核 |

失败反例：AR-4 若先删依赖后切装配（或反序）→ 悬空 import 或双写，锁序
"同批切换"为硬约束；AR-1 行号以退役时现行树实测为准，禁用清单旧行号盲改。
