# 006 执行计划与并行切片账（主代理维护）

并行纪律：同时最多 2 个子代理，槽位满转（A 完成即补 C）。Git/契约/manifest/lock/status/测试槽
唯一归主代理。已派：

- **切片A**（✅已交付验收）：apps/server 两钉面 86→88（新常量带 owner 断言，注释 17=6+7+4 更正）；
  10红→143绿，主代理复核通过。
- **切片B**（✅已交付验收）：server-compat opt-in kwarg 修复 9 绿（主代理复跑确认）；verify-clean.sh
  三新包安装（API 先于后端）+import 冒烟+三 suite 钉（33/20/7，.venv 测得，标注首跑需 clean-clone 复核）；
  ci.yml 安装行加 -e 三包（关键：pacthold 依赖 environment-api 不在锁定文件，缺 -e 会解析 PyPI 失败）
  +三个后端 pytest 步骤；bash -n/YAML 解析复核通过。
- **切片D**（进行中）：封存迁移注册显式装配（runtime-compat 无副作用+products/server 显式调用）。
- **本地打包**（主代理后台进行中）：/tmp 一次性密钥对（仓库外，私钥构建后删）+ build-deb.mjs 产出
  packaging/.staging 本地运行时，供 electron 6 腿 ORDESSA_BUNDLED_ROOT 用。
- **排队C**（repo-scout，A 或 B 完成后立即派）：T006-04 只读盘点——bootstrap global core_db
  使用图（configure_database/get_conn 调用点）、旧 sidecar/work_core/NeutralRunTracker 新请求
  路径清单、ServerCompatPlugin 跨领域服务创建点（native Profile 必选性、独立 CoreBinding），
  输出逐文件:行号，供 T006-01/02 设计。
- **主代理保留**（不可委派）：T006-07 物理归组（pacthold、server-plugin-api → packages/backend/*
  的 git mv + workspace/CI/脚本/文档同步——含 manifest/lock 写权）；T006-01/02 bootstrap 注入与
  host 转发的合同决定；T006-08 C2 效果 fence 切换演练；检查点提交。

## electron 6 腿安装路径决策（001 遗留环境缺口）

结论：**先用本地 staging，不写 /opt**。`resolveBundledRuntime` 读 `ORDESSA_BUNDLED_ROOT`
（packaging/lib/layout.mjs），smoke 各腿继承进程环境——本地 stage 即可满足
python/bin+bin/acp+harnesses 完整性检查，零系统写入。构建方式：`node packaging/build-deb.mjs`
产出 packaging/.staging（需要：PyPI 拉取闭合=本地安装非系统资产；ORDESSA_UPDATE_PUBKEY 用
packaging/update/keygen.mjs 生成一次性测试对，公半内嵌私半即删——021 验收同法）。
若个别路径硬编码 /opt/ordessa 导致本地 stage 不生效，再向用户申请最小 sudo 安装授权（范围仅
/opt/ordessa 运行时目录，不碰 harnesses 现有 root 资产）。此段动作在 006 完成后、008/009
electron 验收前执行。
