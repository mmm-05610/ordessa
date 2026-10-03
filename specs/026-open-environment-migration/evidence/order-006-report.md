# 006 证据 — Server 变薄、入口统一与 compat 业务清空（收口稿）

日期：2026-10-03。前序：005@5baa714cec。委派账：切片 A–J（A/B/D/E/F/G=实现，H/J=测试，C=盘点），
主代理独占：物理归组、裁决（产品翻转推迟 010、通道发现语义确认）、Git/status。

## 任务对照

- **T006-01** ✅ 两半：E（sidecar_backend 实例库注入，第三平行根拆除，S1c 升级）+ F（LegacyCoreBinding
  退役，宿主全程全局 core_db 零触碰，spy==0 门）。apps/server 76F→68F。
- **T006-02** ✅（第一步全量）：I 切片 started 门（dispatch+两流入口；存在性拒绝在前、server.hello 白名单、ROUND_NOT_STARTED 内部码走既有 INVALID_REQUEST 族；红集 diff 为空）；host 全量转发（methods/http/stream 按同
  committed revision 映射）**随 006 收口后按需评估**——C 盘点表明现 registry 即唯一分发表，
  "变薄"的剩余工作在 007/010 领域能力发布后自然完成，本单不强行半转发。
- **T006-03** ✅ 物理迁移 packages/backend/server-plugin-api（T006-07 同批）；提纯断言：
  apps/server 对 server_plugin_api 的使用限于传输契约（边界测试既有零依赖门保持）。
- **T006-04** ✅ C 盘点（三平行根/14 接缝/native Profile 必选路径/入口清单）存档
  evidence/order-006-seam-survey.md。
- **T006-05** ✅ H 测试（双入口一致性/身份/dispatch 计数/跨根拒/未启动与停止 typed 拒）+
  H 发现的 pre-start 缺口转 I。
- **T006-06** ✅（受控半）：J 场景 1（数据根双 writer 拒、锁释放不毒化）+ 场景 3（unknown 只查
  不重发，idempotency claim 计数=0）。生产切换演练=freeze 准入已钉；"route 失败回退"留 011 真链。
- **T006-07** ✅ 物理归组（66c7e23bd3）：pacthold、server-plugin-api → packages/backend/，发行/
  import/数据标识不变，353 绿新路径；docs/baseline.md 路径清点登记延至 012。
- **T006-08** ✅（受控半）：J 场景 2（六类效果方法 stop 后 typed 拒+发现面撤）+ 场景 4（未注册
  方法钉面）。效果 fence 的完整 kill 窗已由 005 端口级覆盖，产品链 011。
- **T006-09** ✅ 封存迁移显式装配（D：products/server 251 绿含 6 注册测试，import 零副作用）+
  native Profile 必选性接缝（G）；**裁决记录**：产品层 bootstrap=False 推迟 010（显式绑定路径
  未建，翻转即断通道发现/打开）；`acpChannelHarnesses` 身份过滤=有意语义保持。

## 门对照

- G006-1 依赖/贡献一 revision、drain/closure、owned-borrowed 一致：004 台账+006 注入门 ✓；
  未映射入口 typed unavailable：I（started 门）补 pre-start 半，stopped 半 J 钉 ✓（I 合入后复核）。
- G006-2 前序 SHA 链完整（5188→8155→ceca→7c94→5baa）✓。G006-3 红集逐 ID 对照纪律全程执行
  （每切片 stash 对照）✓。G006-4 无凭据/真实数据/未授权操作 ✓。

## 命令与结果（最终态）

| suite | 结果 |
| --- | --- |
| apps/server | **68F+2E/1206P/9S**（红集与基线逐 ID 一致，I 切片 diff 为空；+14=本轮新测试） |
| products/server | 251 passed |
| plugins/server-compat | 13 passed |
| packages/backend（pacthold+server-plugin-api） | 353 passed |
| plugins/harness | 3F（登记继承集） |
| plugins/runtime-compat | 163 passed |
| electron 6 腿（本地 staging） | 4/6 绿；2 腿独立成因登记 |

## 遗留与移交

1. T006-02 host 全量转发（评估后归 007/010 领域发布自然完成，或 012 复核）。
2. 产品 bootstrap=False 翻转：010（显式选择/首次发送绑定落地时）。
3. agent-shell 腿（ordessa.agent-server 发行装配）与 ui-foundations 腿（padding）：012 裁决/008。
4. docs/baseline.md 路径清点：012-07。
5. work_core/db.py 模块与 CoreRepository 无注入默认面：012 退役。
