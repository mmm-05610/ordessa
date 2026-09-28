# Q2 集成请求（交 C0）

本线不写 `products/**`、根 `package.json`/`package-lock.json`、`tooling/**`、`packages/**`、`apps/**`、
`plugins/server-compat/**`、`docs/**`（共同 plan 的 C0 独占面）。以下是需要 C0 处理或裁决的具体项，
每条含现状证据与期望结果。

## IR-Q2-01 `docs/baseline.md` 后端安装命令不完整（阻断无人值守验证）

证据：本树按文档命令执行得到

```text
ERROR: Could not find a version that satisfies the requirement ordessa-server-plugin-api<1,>=0.1.0 (from ordessa-server)
SETUP_EXIT=1  →  ModuleNotFoundError: No module named 'pacthold'
```

补 `-e packages/server-plugin-api`、`-e plugins/server-compat -e plugins/workspace` 与
`-e products/server` 后 `IMPORT_OK`（exit 0）。不装 `ordessa-server-compat` 时
`python -m pytest apps/server` 直接 `Interrupted: 78 errors during collection`，原因
`ModuleNotFoundError: No module named 'ordessa_server_compat'`；不装 `ordessa-server-product` 时
多了 **180 条**红，主因 `SERVER_PRODUCT_MISSING: no installed product provides the
'ordessa.server_product' composition'`。装齐后同一环境得到
`43 failed, 850 passed, 10 skipped, 25 errors`（用时 119.77s，exit 1），与 `docs/baseline.md`
的继承红账 `…/43F/10S/25E` 同类计数吻合。

期望：在 `docs/baseline.md` 的 Backend 段补这些可编辑安装（或说明其归属），使干净检出可按文档一次装成；
否则每个新会话都会先花一轮把环境缺口误读成业务回归。

## IR-Q2-02 `products/desktop/extensions.lock.json` 与已提交 workbench 源码不同步

证据：`npm run build`（exit 0）稳定产生

```text
"extensions/ordessa.workbench/entry.js": 324d734792… → 5eab6515fa…
```

连续两次构建结果逐字节相同（构建确定），期间无源码改动。故 main 中该锁条目相对 `plugins/workbench`
的已提交源码是旧的；任何人跑构建门都会脏化一个受版本控制的 C0 文件。

期望：由 C0 在集成树重算并提交该锁（根锁/产品锁仅 C0 生成）；本线已在运行构建后
`git checkout -- products/desktop/extensions.lock.json` 还原，不提交越界改动。

## IR-Q2-03 两域产品启用（原表 prompts T13 / templates T14 的装配部分）

需要：把 `ordessa.assets.prompts` 与 `ordessa.assets.command-templates` 两个 Server 插件与对应前端贡献
纳入产品装配，并由正常构建生成锁（不手改哈希）。

本线交付：两个域发行包（含 `plugin.py` 的服务/方法注册 descriptor）、Server 侧注册反例、前端贡献模块、
以及在装配后一条命令可复跑的验证脚本与预期退出码。待 C0 装配后由本线按固定 SHA 复跑并回填报告。

## IR-Q2-04 `plugins/workspace` 无测试可收集

`python -m pytest plugins/workspace` → exit 5（no tests collected）。登记为环境事实；若属预期请标注，
否则需补最小套件以免被误读成绿色。

## 待补

两域实现代理交回后追加：旧 `server-compat` 提示/命令相关 writer/路由的退出账（列文件、所有者、调用方、
迁移与目标），以及 foundation / harness-api / profile-api / chat-api 发布后本线消费的精确 SHA。
