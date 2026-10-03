# 教训记录 — sed 排除过滤误伤历史证据（2026-10-04，批次3）

现象：批量替换路径引用时，grep 排除过滤写 `/docs/|/specs/`（带前导斜杠），而仓库内路径为
相对形式（`specs/...`），过滤失效 → sed 改写了 001 冻结清单（source-manifest-a/b）、R6
compat-inventory、011/012 manifest 与 002 台账的历史路径文本。

处置：按"旧结果/原来源快照不改"铁律全部 `git checkout` 回滚，只保留 .github/workflows/ci.yml
的生效引用更新。001 清单复核回到 head=ebe712c796、3347 文件原状。

防复发规则（后续所有批量替换）：
1. 过滤必须同时匹配带/不带 `./` 前缀（grep -rln 的输出两种都可能）：用 `grep -v -e '^specs/' -e '^docs/' -e '^./specs/' -e '^./docs/'` 或干脆 `--exclude-dir=specs --exclude-dir=docs --exclude-dir=evidence`（grep 自带目录排除最稳）。2026-10-04 复发记录：`^./specs/` 过滤对无前缀输出失效，9 个证据文件被 sed 改写后 git checkout 回滚，清单生成后必须先抽查含不含 specs/。
2. 批量 sed 前先 `grep -l | tee` 清单人审；evidence/**、specs/**（除 026 自身台账按工单更新）
   永不进批量替换输入。
3. 替换后立即 `git status specs/ evidence/` 应为空，否则回滚重来。
