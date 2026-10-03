# 实施树准备回执

2026-10-03。用户明确授权新树及批准范围的基线提交；本会话未启动迁移编码、用户服务、真实模型或数据操作。

- 实施目录：/home/maoqh/projects/ordessa/worktree/026-open-environment-migration
- 分支：codex/open-environment-migration
- 固定源码/方案基线：4ec124a2fce10878d55808963ac7e471dc4f7354
- 原产品HEAD：7951bf06a258d2dc41402556eb61319b8bab5cbe
- main HEAD：b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0，是原产品祖先，无main独有提交需另合。
- 导入113文件：23产品源码/测试/清单/说明，90设计文件；另加prepared-source.json共114提交文件。逐文件原/目标摘要一致，无末尾换行归一化，源树未写。
- 外部资料只是模型配置建议，没有改用户zcode、读Key、查询额度、调用模型或启用超额扣费。

## 已验证与未验证

结构：node specs/026-open-environment-migration/checks/validate-package.mjs退出0，12/114/95，23破坏样本PASS。导入JSON可解析；9产品Python文件ast.parse通过。所有检查均非产品运行验收。

git diff --cached --check对产品源码/清单/历史说明通过；全量返回1，有393项继承格式告警：025的evidence/source-excerpts.txt行号摘录尾空白，以及026 charter/lifecycle-evidence/evidence README/queue/research文件末尾空行。保持历史证据字节，不偷偷改摘录或报告全量通过。这不是新增产品测试失败；后续文档清理若改证据须保原摘要和说明。

未执行：npm安装/typecheck/build/test、Python产品测试、Go/native回归、Electron/IME、deb构建/安装、模型调用、用户数据库迁移、服务重启、main合并/push。原GUI验收只作历史引用，不代替新源码实测。

## 001精确剩余

T001-04准备范围已获批，新树和固定源完成。T001-01根/源HEAD与祖先已查，但全部子目录指令及当前服务状态需牵头者检查。T001-02/T001-07批准导入文件有类型/摘要/前后核对，但全树发现及suite表未完成。T001-03需重核历史验收引用。T001-05测试发现/隔离基线尚未跑。T001-06有固定源码与回执，但缺测试基线和完整codeReady材料。

因此001仅PARTIAL/source-prepared，不颁codeReady；002–012尚未开始。启动Agent先完成剩余001，不等待重新询问已批准的新树/导入范围，不把基线提交当全单验收。

## 授权及指令冲突

用户本轮批准范围记录为M12：仅本树源码/方案准备和本地基线提交。覆盖旧来源说明中排除Profile/Provider的过时前提，仅迁移分支纳入真实源码，不改main也不新增占位；固定基线以本回执获批快照为准。其余安全/import/持久身份约束不变，AGENTS本身未改。

编码以用户向zcode粘贴zcode-handoff启动词为许可；具体用户服务/数据/安装/真实模型/合main/push仍需独立批准。旧M09历史记录不能被解释为本树准备未授权，也不能因M12推断所有运行操作已授权。
