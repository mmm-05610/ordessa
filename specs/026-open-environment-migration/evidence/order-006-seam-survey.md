# 006 T006-04 旧入口盘点（repo-scout 交付，主代理存档验收）

来源：只读子代理 2026-10-03（行号为当前树实测）。要点浓缩，全文见子代理报告入 status 引用。

## 三个平行根（006 要消除的对象）
1. `CoreBinding`（apps/server/core_binding.py:86，宿主 C1 实例库 state/core.sqlite）——**保留**（宿主自己的 seam）。
2. `LegacyCoreBinding`（bootstrap/runtime.py:119-155）——模块级 `configure_database/get_conn` 单例，start():347 最后连接、stop():386 释放——**拆除对象**（T006-01）。
3. `sidecar_backend.py:201-211` 私有 `CoreRepository()`（无 store 注入→绑全局单例）+私有 `ExtensionRegistry`——**拆除对象**（T006-01/02）。

## 全局 core_db 生产触点（全量）
- work_core/db.py 模块单例（_conn/_database_override/write_lock/register_migration_source）。
- 生产调用：repository.py:141-142（默认绑定）、legacy_migrations.py:44（唯一生产直接 import，D 切片正迁显式装配）、bootstrap/runtime.py:110/150-151/155、sidecar_backend.py:201（间接）。
- 启动序：activate_all → start_hooks → legacy_core.connect()（**激活期全局未绑**——注入改造窗口）。

## 「旧执行新请求转 Environment」接缝清单（14 点，T006-02/04）
core_wire.py:1861 execution.accept 注入点；plugin.py:236-253 isinstance 判定→seam；plugin.py:491-509 _core_filer；sidecar_backend.py:201-211 私有 repo/registry；:292/:541/:579/:612/:651/:696-702 dispatch/finalize/链式 accept；sessions/repository.py:910-937 队列链；sessions/service.py:90-110 与 :229-273 双入口；composition.py:540-572/:1091-1456 双 port_factory；plugin.py:304-307 执行门；:374-413 start/stop hook；runtime.py:347/386 legacy_core 生命周期；http.py:109 REST 分支。

## native Profile 必选性（006 移除目标）
plugin.py:411-412 `_bootstrap_native_profile()`（native_harness_id 非空即建）→ :424 create_wire → :443-447 bind → :448 `_assert_profile_executable`；外溢：composition.py:574-597/650-658/684-687、sessions/service.py:54-63/77-86/156-191、core_wire.py:1536。**seal_interrupted_turns 实际写 state='unknown'（repository.py:663-668）——与 C2 一致，保持**。

## 入口清单
`ordessa-server`/`__main__` → entry point `ordessa.server_product` ✔；build_runtime 默认 ✔/显式列表半平行；native_runtime/sidecar_runtime 经产品但插件选择平行（compat composition 自拼，绕 default_plugins）；第二波激活 products/server composition.py:332-337。

## UNKNOWN（转 006 实施时验证）
显式 server_plugins+历史根+无 database_factory 的 preflight 顺序；runtime_compat.cli 动态入口；build_product_environment 无生产调用方（006 目标候选载体）；ACP 通道是否绕 sidecar backend；desktop spawn 点（008）。
