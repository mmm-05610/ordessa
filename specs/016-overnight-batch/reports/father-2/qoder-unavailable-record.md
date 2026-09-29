# qoder 不可用裁定记录(overnight-2 父会话)

时间:2026-09-29 00:05 前后。结论:**qoder 全线不可用,本父会话四包全部转 zcode 代打**,
各包报告标注「qoder 失败、zcode 代打」。证据链:

1. **封装运行受阻(EXT 包,2 次)**:
   - 首跑 `run-qoder.sh`(23:23:34)被会话中断外部杀死,无退出码,树内零改动。
   - 重试(23:41:37,满足"原样重试一次")退出码 0 但 goal 自报 **blocked**:
     `-p` 非交互 + `--permission-mode default` 下 Write/Edit 与一切命令执行
     (python3/pytest/pip/mkdir+redirect)被**自动拒绝**,会话严格只读,无法动工。
     日志:`specs/016-overnight-batch/reports/logs/son-ext-extensions-qoder-20260928-234137.log`
   - 旁证:overnight-1(PE1)与 overnight-3(LSP)独立运行同款脚本,**同样自报
     只读受阻**——系统性问题,非单包特有。
2. **降级条款裸调探针(条款原样命令)**:`timeout 300 qoder -p -w <儿子> --permission-mode
   default -m qwen-3.8-flash "<写文件探针>"`:
   - 模型白名单名 `qwen-3.8-flash` **不可用**(CLI 列表为 `Qwen3.8-Flash`,自动回落
     `qmodel_38max`);
   - 随后报 **credit usage limit reached**——账户额度耗尽,任何任务都无法执行。
   - 日志:`specs/016-overnight-batch/reports/logs/son-ext-extensions-qoder-fallback-probe-*.log`
3. **设置面核查**:`~/.qoder/settings.json` 仅 `permissions.trustDirectories`(已含
   /home/maoqh),无能在 `-p`+default 下放行写的开关;不改封装脚本、不换 permission
   mode(纪律硬编码),故无合规修复路径。

**处理**:按 spec.md 红线 5「qoder 不可用 → 父会话自己代打并标注」。审阅仍按纪律
走 run-review.sh(pi+mimo-v2.6-pro),失败则如实记「未审阅」。

**git 纪律遵守声明**:father.md 对父会话的 git 纪律为「只允许 git -C <儿子路径>
只读命令」。qoder 缺位时其"儿子树内提交"职责无人承担;父会话代打**只落工作树改动、
不执行任何 git 写操作**(不 commit),留待用户明早验收后自行提交。此点在各包报告
与总汇报中逐包登记。
