#!/usr/bin/env bash
# 夜批受控 qoder 执行器。用法: run-qoder.sh <son-worktree-相对路径> <dispatch文档绝对路径> [超时秒,默认5400]
set -u
REPO=/home/maoqh/projects/ordessa
LOGDIR=$REPO/specs/016-overnight-batch/reports/logs
SON=${1:?用法: run-qoder.sh <son相对路径> <dispatch绝对路径> [超时秒]}
DOC=${2:?缺 dispatch 文档绝对路径}
TMO=${3:-5400}
case "$SON" in
  worktrees/overnight-*/son-*) ;; *) echo "REFUSED: 儿子路径必须在 worktrees/overnight-*/son-* 下，收到: $SON" >&2; exit 64;;
esac
[ -f "$DOC" ] || { echo "REFUSED: dispatch 文档不存在: $DOC" >&2; exit 64; }
WT=$REPO/$SON
[ -d "$WT/.git" ] || git -C "$WT" rev-parse --git-dir >/dev/null 2>&1 || { echo "REFUSED: 不是工作树: $WT" >&2; exit 64; }
TS=$(date +%Y%m%d-%H%M%S); LOG=$LOGDIR/$(basename "$SON")-qoder-$TS.log
{
  echo "== run-qoder $(date -Is) son=$SON doc=$DOC timeout=$TMO"
  echo "== 分支: $(git -C "$WT" branch --show-current) @ $(git -C "$WT" rev-parse --short HEAD)"
  echo "== 动手前 status:"; git -C "$WT" status --short | head -20
} | tee "$LOG"
timeout "$TMO" qoder -p -w "$WT" --permission-mode default \
  "/goal 完成 $DOC 文档的所有要求。硬性纪律：只写入本工作树内本插件目录与该文档允许的 reports 路径；禁真实模型调用与外网实测（受控假端点除外）；不 merge/rebase/切换分支；不 fake green；完成后在该文档要求的 report 位置写报告。" 2>&1 | tee -a "$LOG"
RC=${PIPESTATUS[0]}
echo "== qoder 退出码=$RC 结束 $(date -Is)" | tee -a "$LOG"
exit $RC
