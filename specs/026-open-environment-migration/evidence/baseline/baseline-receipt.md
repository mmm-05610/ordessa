# 001 基线回执（T001-06）— codeReady 材料

2026-10-03。实施树 `/home/maoqh/projects/ordessa/worktree/026-open-environment-migration`，
分支 `codex/open-environment-migration`。

## 合成与授权

- 用户启动词（zcode-handoff.md §目录与启动词，2026-10-03 粘贴）授权本树 001–012 编码与本地
  检查点提交；起点 `ebe712c796`（= 本基线 HEAD，git rev-parse 复核）。
- 来源链：产品 HEAD `7951bf06a2`（本树祖先）← main `b4bf7cd90951`（祖先，无 main 独有提交）；
  准备基线 `4ec124a2fc`（113+1 文件导入，preparation-receipt.md）。M12 准备范围继续有效；
  真实数据/安装/服务/模型/合 main/push 仍未授权（M09）。
- 本树工作脏文件：本 evidence/ 目录新增（001 写权内）；未触碰他人脏改。

## 源 digest

- `source-manifest-a.json`/`-b.json`：3347 tracked 文件全量 sha256（两算一致，head=ebe712c796）。
  类别与违规扫描见 T001-01-03-report.md §T001-02。
- 秘密/运行数据/凭据 tracked 命中：0。symlink：0。

## 继承红（基线时点快照，详见 test-baseline.md）

- apps/server 78 ID（钉面漂移 10 已归机制、其余继承类别；逐 ID 清单 server-red-ids.txt）。
- plugins/harness 3 ID（台账继承集，ID 一致）。server-compat 2 ID（kwarg 漂移，69c0ea2818）。
- acp_orchestration 28 ID（裁决保留）。JS：products/desktop 1（pi 钉名）、rig 1（发送钮 a11y 文本）。
- 环境前置缺失非产品红：electron 6 腿（/opt/ordessa 无 python/bin）。

## 未验证（不冒称）

- GUI/IME/真机窗口行为：未跑（electron 6 腿环境缺）。真实模型三品牌链：0 调用（未授权）。
- Round-H 11/11 桥验收对 `714044a5…` 未重跑（known-issues 已登记的证据溯源行）。
- deb 构建/安装/发布链：未跑（安装/系统资产未授权）。
- 021 历史验收（历史回忆、同 Profile 重选、输入闪烁用户确认）为引用证据，本树未重证。

## 恢复点

- 检查点提交：本文件同批提交（001 完成提交，SHA 见 git log；后续单以该 SHA 为前序证据）。
- 恢复方法：`git checkout <001-checkpoint>`；`.venv`/`node_modules`/两处 rig 闭包按
  suite-discovery.md §环境前置 重建；manifest 重算命令同文件。

## 001 判定

- T001-01…T001-07 全部完成（本目录 5 份证据 + manifest 双算）。
- 四门：G001-1 来源完整获批（manifest+授权链）✓；G001-2 启动核对无循环依赖 ✓；
  G001-3 发现与基线逐 ID/原因记录，新增红全部归因（钉面漂移 10+2、kwarg 2、钉名 1、文本 1），
  继承红单列 ✓；G001-4 无凭据/用户数据/binary 提交、无未授权操作 ✓。
- **001 = DONE（codeReady）**；electron 6 腿为环境缺口（U/P 类），不阻塞 002+ 的 S/I 解锁，
  但相应 GUI 验收在 011/012 前不能报 DONE。
