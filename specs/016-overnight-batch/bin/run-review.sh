#!/usr/bin/env bash
# 夜批受控审阅器（pi + mimo-v2.6-pro，物理只读）。用法: run-review.sh <son-worktree-相对路径>
set -u
REPO=/home/maoqh/projects/ordessa
LOGDIR=$REPO/specs/016-overnight-batch/reports
SON=${1:?用法: run-review.sh <son相对路径>}
case "$SON" in
  worktrees/overnight-*/son-*) ;; *) echo "REFUSED: 儿子路径必须在 worktrees/overnight-*/son-* 下" >&2; exit 64;;
esac
WT=$REPO/$SON; BR=$(git -C "$WT" branch --show-current)
TS=$(date +%Y%m%d-%H%M%S)
DIFF=$(git -C "$WT" diff main...HEAD)
[ -z "$DIFF" ] && { echo "空 diff，无事可审"; exit 0; }
printf '%s' "$DIFF" | head -c 180000 > /tmp/review-$TS.diff
timeout 600 pi -p --no-session --no-tools --model mimo-v2.6-pro \
  --append-system-prompt "你是代码审阅者。只输出：1) 三条以内最重要的具体问题（文件:行号+一句理由）；2) 有无 fake green 迹象（删断言/空测试/谎报）；3) 一句结论：通过/有保留/不通过。不做修改建议长篇大论。" \
  "审阅分支 $BR 相对 main 的完整 diff（见附后文本）。重点：写入面是否越界、任务与代码是否一致、测试真实性。DIFF 开始>>>$(cat /tmp/review-$TS.diff)<<<DIFF 结束" \
  > "$LOGDIR/$(basename "$SON")-review-$TS.md" 2>&1
RC=$?
if [ $RC -eq 0 ]; then cat "$LOGDIR/$(basename "$SON")-review-$TS.md"; else echo "审阅失败 exit=$RC，按未审阅处理"; fi
rm -f /tmp/review-$TS.diff; exit $RC
