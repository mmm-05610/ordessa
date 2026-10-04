# Agent Tools 准备状态

## 已完成（仅准备）

- 托管worktree：`/home/maoqh/.codex/worktrees/agent-tools-product/ordessa`。
- 分支：`codex/agent-tools-product`。
- 固定准备基线：`baseline/cp-monorepo-0`，`6a3f24456130b5caad82682d692d2d198721f0a8`。
- 主树只读观察HEAD：`b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`；主树已有dirty文件未动。
- 026只读观察HEAD：`b12296ad4444c1cf0c1cdb891be2ca55cc850536`；活跃、可变化，不是获准消费基线。
- 独立venv：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312`，在源码树外，不共享旧树site-packages。
- Python 3.12.14；pip 25.0.1；`pip check`退出0，无broken requirements。venv只含基础bootstrap，不代表产品依赖已安装。
- 标准库检查：sqlite3 3.53.1、SSL OpenSSL 3.5.8可加载；sys.prefix与base_prefix不同。
- Node v22.22.1、npm9.2.0实测；本工具CLI拟用Python，没有运行npm ci。
- Codex/Pi命令路径可发现；没有执行模型、启动Harness或读凭据，不据此宣称支持完整原生入口。
- 029目录、架构、接口和阶段设计已保存。
- 材料检查：6份文档标题与本地链接检查通过，退出0；只是设计材料检查，不是产品测试。

## 需要明确的下一步

当前准备基线早于最新主树和026；不在旧树实现新核心，更不复活旧兼容链。正式实现先固定已验收的消费SHA，按授权更新此树并同步028修订权威。P0完成不等于可以直接跳P4真实调用。

产品Python/npm依赖、wheel构建、真实核心装配、CLI实现、三Skill实际资产、MCP、真实SQLite/原生进程/DOM/模型测试均未完成或未运行。本轮只准备环境与设计。

## 运行权限

未启动任何服务，未打开端口，未改变用户数据、Token、原Harness安装或Codex配置，未安装全局Skill；未创建新仓库、提交、合并或push。没有实施执行者在此树运行。

## 查看设计

[029产品目录与架构](../../../specs/029-agent-tools-product/architecture.md)。核心装配规则沿用主树028审阅材料，只读引用；变更需同步正式权威而非子树自建一套。

## 2026-10-04 实施启动核查（尚未切换基线）

已完整读取本树AGENTS/baseline、029四文档、章程/状态及028核心设计/契约/迁移/验收/审阅/材料校验源码。已开3个只读子代理并由主会话复核；用户已明确要求多个子代理高效执行。

建议固定adce734db21945181bf93da9720158d05e957654，理由与精确切换提案见[基线核查](baseline-review.md)。待用户确认该SHA和本树归档/摘要核验后fast-forward方式；当前HEAD仍6a3f244，未实现产品源码。已有设计材料不覆盖；原章程“仅准备”由本轮实施请求更新，基线批准门仍有效。

第一批001–005准备工单已保存，依赖/写权/反例/缺席行为/并行单元明确，尚未派执行。公开核心缺口与未决wire均登记。后续原生任务、三Skill/分发、隔离安装验收按029顺序，MCP不阻第一版。

本次命令与原文件/设计摘要见evidence/baseline-inspection.json。产品单测0、契约测试0、真实隔离服务测试0、真实模型调用0；引用026已有验收不记本次通过。没有服务启动/重启、用户DB/凭据/全局配置修改、Git提交/切换/推送/主树合并。

### Spend

子代理请求3；费用无法精确取得，标unknown；真实外部Agent/模型测试调用0。

### 本轮准备校验

工单结构首跑退出1（5单缺depends_on order id），补正后严格校验5/5、退出0；git diff --check退出0，HEAD复核仍6a3f244。四份原029文档SHA256逐项未变。记录见evidence/preparation-validation.json。均为准备校验，产品门未运行。

## 2026-10-04 固定基线后的实施（当前权威状态）

前文“仅准备/未切换”是历史记录。用户go批准固定adce734db21945181bf93da9720158d05e957654及先归档、摘要核验、ff-only切换，本树已执行完成；归档15份设计文件逐项hash未变。证据pre-switch/receipt.json与baseline-review.md。未cherry-pick移动分支，其他树只读。用户另明确批准现有RequestKey身份与核心公开薄绑定，见rulings.md R-0002/R-0003。

修改：同Environment/同SQLite Store增加原子domain-records/1，Profile不可变manifest与独立catalog版本、双CAS、授权、请求键重放/冲突、SecretRef限制；Pacthold新增agents.public（不改既有pacthold.public导出），无业务插件/第二数据库。Server唯一registry新增核心方法factory生命周期与owner保留，公开Profile wire薄绑定。CLI独立stdlib transport、发现和Profile命令，schema由核心生成；节点与输入未装配。三子代理按存储/Server生命周期、CLI/分发、核心反例/部署切片并行，主会话独占合同、Git和本账本。

已验证：持久化新定向12项通过（执行者）；CLI早期发现20项通过（主会话，6.15s）；核心真实隔离SQLite31项通过（执行者）；Server生命周期15项通过（执行者，0.11s，owner/DB double，非真实service）；薄wire契约6项通过（主会话，0.11s，实际临时SQLite，非HTTP服务）。CLI新增命令、部署及安装包仍待主会话整体验证，不能相加称产品验收。

基线全量327P/3F，退出1，继承方向扫描失败已登记docs/known-issues.md，不删断言。生命周期首跑11P/1F为新fixture遗漏display_name，补正后15P。Server依赖安装两次退出1（本地闭包未全提供：server-compat/harness），解析所有本地pyproject依赖闭包后安装退出0，沿用server-linux-py312 lock；专属venv内，无全局安装。

本轮真实模型调用0。当前无Git提交/推送/主树合并；临时服务验收尚未完成。P1仅Profile数据基础完成，不能称非Chat真实节点prepare门通过。P3/P4仍需公开贡献者、目录授权、唯一Harness owner和原生session/input证据；P5分发/Skill在并行准备。

### Profile切片真实服务与分发检查点

主会话定向核心/存储/生命周期/薄wire联跑64P退出0(0.35s)；后续完整性修复增加重放identity/revision/digest/extra篡改拒绝、损坏JSONtyped不可用、registry并发RLock（执行者16P，确定性反例能抓去锁实现）。真实临时uvicorn＋独立CLI两场景，连同部署边界9P退出0（执行者，5.08s）：CRUD/CAS/历史、权限、重启同namespace、预置unknown独立标fixture；实际TCP回执丢失另场景提交create恰1次，CLI unknown6，恢复仅entry/show/list，未重发。测试服务与proxy均主动退出，无用户服务动作。

CLI/客户端合同/隔离wheel安装42P退出0（20.60s，执行者），bundle6P退出0（1.93s）。3个Skill格式校验退出0（只材料，不计Agent任务完成）。build-time生成schema，不是客户端依赖；实物products/agent-tools/dist/bundle-0.1.0a1（ignored）包含wheel/3Skills/schema/README/SHA256SUMS，7文件hash核验退出0。Skill明确nodes/input缺席。

受影响Server/Plugin API回归11F/162P退出1（2.86s），同固定adce源隔离比较也是完全相同11个失败ID、162P（2.67s）；日志server-seams-regression.txt/server-seams-fixed-baseline.txt，无新失败ID，不把总回归报绿。新core全量首次4F/338P退出1，其中新增一项是旧scanner probe路径退休后随机选首module，对合法environment-api导入误判；只把probe固定到真实core/dtos.py，原断言全部保留。方向定向3F/3P，三个继承失败保持，见direction-regression.txt。

用户已批准R0004 Workspace＋显式DirectoryAuthorityPort；新增006目录授权与007同journal具名step工单，签发/存储基础并行，公开合同主会话冻结。现有Workspace local host=None不能证明realm，缺可信host授权映射拒绝，不能靠目录访问权限冒充execute。生产接纳、Harness RuntimeProvider/唯一owner、native session reservation/input、transport fence、真实模型仍未验收。

主会话全products/agent-tools联跑116P，退出0，27.17s；按类别精确分账见evidence/profile-slice-validation.json（42客户端/安装、6bundle、31核心SQLite、16生命周期double、12wire契约SQLite、9部署/真实service）。这是Profile-only快照。随后resolver改为只返本轮捕获Environment并与撤销共享锁，防止旧handler lazy-open下一轮；新增反例后生命周期17＋wire12=29P退出0(0.29s)。

006/007新工单结构首跑退出1（重叠写权serialization和缺fenced command），补正后7/7退出0；没有改产品断言来通过结构校验。归档tar.gz与临时固定源码副本明确ignore，文本receipt可审阅；bundle ignored，不存二进制入Git。

### Directory授权切片与后续独立复查

006执行者20P退出0(0.25s)，主会话联跑Directory20+薄wire16=36P退出0(0.29s)。同原WorkspaceRecords/DB读取项目，不另建项目库；绑定写同Environment StorePort、实际临时目录stat，OS事实不代替AuthorityPort。绑定只授固定requested purposes；原始grant超集不扩权；重放核project/purposes/realm、原三元request和protected digest，拒另一合法binding调包。原fixture大写RequestKey首跑失败已修为合法小写，不改断言。严格env_host=None缺证据拒绝；未生产接纳/原生使用。

独立复查后：部署core.sqlite-wal/-shm链接写前拒，四反例目标/main DB字节不变，部署＋HTTP13P退出0(5.14s)。薄wire分开参数阶段和调用阶段，已提交后ValueError/TypeError/KeyError/RuntimeError全部unknown而不是INVALID_REQUEST，16P退出0；UTF-8/非有限JSON输入发前拒。CLI ProfileRef形状/类型/namespace/关联identity从生成schema核验；初跑clone fixture错误地返回源id reviewer，而新请求id copy，新检测报unknown6（1F/34P），修正fixture真实clone结果，原成功断言保留；定向25P后新增两个UTF-8数值反例。主会话全产品目录最新快照152P退出0(29.73s)，日志profile-directory-validation.txt，随后新增core owner冒领反例等待下轮完整复跑。

具名operation-records/1合同已冻结供007实现：沿env_requests完整三元主记录，env_request_steps子步骤，现env_usages增量持久holder/target CAS；不采用第二CoreRuntime/Agent journal。读写始终完整RequestKey，opRef同env唯一；Usage holder为完整scoped mapping而非裸id。old rows保持旧知识枚举与花费事实，阶段status独立，不扩oe-contract/1 Outcome。暂无provider调用或node能力发布，基础存储通过也不计native成功。

### Profile＋目录＋操作存储基础最终复跑

主会话全products目录187P、0F、exit0、29.30s，见evidence/product-final-foundations.{txt,json}。分账：49客户端/隔离wheel安装，6bundle资产；16薄wire合同（实际临时SQLite、非HTTP服务）；17生命周期/registry double；32核心Profile SQLite、20Workspace授权/目录事实、34operation SQLite；11部署边界；2真实隔离Server＋独立CLI场景。两HTTP场景覆盖真实提交回执丢失与零重发、重启身份、权限和CAS；不代表原生任务成功。产品整体仍PARTIAL。

007独立复查发现同digest不同intent、Usage rights扩张、published/step证据与冻结配方篡改，均已修并加反例。intent/result/evidence独立canonical摘要用于损坏检测，不是授权签名；旧bare-id写口拒覆盖scoped记录。沿现Environment语义released Usage终结，不能复活/转holder，重取须新id；unknown→active仅concluded证据。独立临时SQLite反例最终exit0、未发现新增确定阻断。操作专测34P，含原SQLite测试71P（执行者exit0，主会话复跑日志operation-and-storage-final.txt）。SIGKILL仅自建临时测试进程。

核心回归339P/3F、exit1、7.50s，仍同三个方向扫描继承失败，日志core-operation-regression.txt；受影响Server此前11F/162P与固定基线同ID保持登记，不称全量绿。资料工单12/12 exit0、diff check exit0只算结构。原始Profile-only bundle是历史快照；新build输出dist/bundle-0.1.0a1-profile-directory，exit0，全部7 payload hash校验exit0，CLI仍独立、不带后台或秘密。

用户已批准R-0005显式InvocationAuthorityPort。008当前冻结具体签名/不可伪造可信Context验证边界；现Policy bool与owner_application不能冒充新的授权。失去进程内Context证明时拒effect，不能据memory空证明notDispatched。下一生产缺口仍包括Unit/Session目标及同配置owner journal迁移、共同配置scope排他、可信贡献接纳、原生correlation/query、实际transport fence与单session/input reservation。未实现nodes/tasks/results；Skill格式/安装不计Agent任务验收。真实模型调用仍0；没有push/main merge、用户服务重启或全局Agent配置修改。

### R-0005 Invocation基础主会话验收快照

AT-008A仅新增core agents/invocation.py与products隔离测试；显式authority/current-state且冻结invocationBindings，从同SQLite Store claim首次才签发。Context精确issuer对象身份、immutable快照、受限verifier、锁内一次consume、重入保护、有界ticket与claim前容量预留。grant/epoch/provider/目录/取得关系重核；Cleanup限已取得目标，独立当前read grant可查询旧epoch未知事实。失去进程身份不重签已花费claim，verify失败也不恢复effect ticket，不写假native结果。有限UTC clock拒NaN/Inf/bool/负数；future annotations只修已知3.9类型定义兼容，未实测3.9。

执行者authority53P、连operation87P exit0；主会话此前47P快照早于6项clock反例，最终全products **240P、0F、exit0、29.13s**，分账evidence/product-invocation-validation.json。新增53项是真实SQLite claim＋受控authority/state合同，不能算真实Provider或模型。核心复跑339P/3F exit1、7.74s，同三个继承方向失败不隐藏。资料12/12与diff check退出0只结构。

AT-008B两个只读审阅完成，共同scope与target/journal迁移准备见harness-target-migration.md。现session/channel排他未证明跨channel/Unit共享物理资源；普通scope字符串无权威。生产缺口是第一家真实unit reservation、owner统一scope映射与跨journal共享资源authority、所有入口admission cut及native receipt/query/fence。这些实现事实缺席时保持unsupported，不能用fixture取得关系替代。当前仍未实现节点/任务/结果查询，整体不是完成版。

分发新增ACCEPTANCE.md，说明安装/使用/分类验收与未完成门；bundle now包含该文档。相关bundle6P exit0、1.92s，build新鲜输出dist/bundle-0.1.0a1-foundations exit0，8项payload checksum全通过；不覆盖历史bundle。240P快照后只有分发文档/复制清单修改，定向6P覆盖；未再重复无关测试。原029四份设计hash仍与切换前归档一致，见design-preservation-final.json。

AT-008A最终独立代码复查53P exit0(0.52s)；额外撤销probe exit0：grant撤销拒、恢复也不恢复effect ticket，持久claim仍possibly-dispatched。独立连接writer探针第二Store被WriterLockHeldError拒绝，exit1（owner安全门符合预期，未绕过）；不能宣称独立writer并发claim已实测。8issuer/8线程是共享同可信Store的竞争。未发现基础范围内新确定阻断。跨进程授权、生产接线、跨端口原子性、真实Harness作用与运输fence仍未验收。所有临时过程只本树隔离资源，模型0。

下一原生切片只读核查推荐Pi installed profile bridge：entry.mjs导入前固定私有配置/session目录；creation.mjs refresh allowNetwork:false；server.mjs session.new与prompt分离；AccessEntryTransport已有启动/释放证据。这里只读源码，SDK实际零模型/零网络session创建未实测，不报绿。旧AcpChannelRegistry仍launch先于run持久化且spent scope内存，依赖profiles/session/turn；native creation attempted/query无冷恢复ledger，history仅prompt后写。下一008B/009必须在Harness同owner补真实unit reservation、统一scope、创建前持久core correlation、响应后立即NativeSessionBinding、epoch与晚到效果fence。不能直接接旧ExecutionProvider或runtime_compat。详见harness-target-migration.md，整个产品保持PARTIAL。

### 独立安装后实际使用（用户要求自试）

直接执行本地bundle wheel，不复用pytest辅助类、不以源码模块代替已安装entrypoint。新建ignored临时目录及fresh client venv，pip --no-index --no-deps安装实际wheel；pacthold/ordessa_server/ordessa_harness均不在客户端环境。配套服务使用既有Server、自己持有的临时root/随机端口/随机fingerprint key与临时Bearer，不读或修改用户凭据；正常停止两轮，临时venv/DB/Token/日志均清除。模型调用0。

运行命令：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python products/agent-tools/acceptance/install_use.py`。脚本首次执行位置在evidence，完成后归产品acceptance目录并更新相对路径（满足测试/分发资产在products），逻辑未改变。实际运行exit0、26项安装/命令/停止记录，原始安全输出见evidence/install-use-exercise.json。不是新增26项pytest。

安装/独立性/help、doctor、capabilities、Profile create/read/edit/history/clone/archive/restore、确认后同请求重放、服务正常重启后历史读取与原edit结果重放均退出0。无效临时Token退出3；陈旧CAS退出5；缺真实provider的preview退出4、ready=false；停服doctor退出4。nodes list与run hello解析退出2，明确命令尚不存在，不是可运行任务。doctor supports=profileCatalog:true/nodes:false/managedInput:false。

Profile manifest显式标记catalog-only，引用deliberately-absent-catalog-check；只能证明目录数据真实服务读写，不能算真实Harness配置或Agent成功。三Skill拷到临时项目目录并核对configure Skill步骤，没有全局安装，也没有独立模型Agent行为评测。用户要求的自试结论：wheel可独立安装、目录功能可用，Agent运行能力仍未交付。diff check退出0。

迁到products/agent-tools/acceptance后已按上述精确命令再执行，exit0、26记录、runtime_cleaned=true、模型0，覆盖相对路径变更；安全记录更新为该轮，不累加成52场景。未改CLI实现或隐藏缺失命令。


### AT-013 本机初始化发现与 0.1.0a2 安装验收

用户要求的初始化已完成Linux切片：`ordessa-agent init --json` 不需要service配置/Token；`--path`可显式选择扫描PATH，`--output`只写调用者选择的新文件（600、排他创建、拒覆盖）。扫描常规可执行文件、链接目标、全部shadow路径，保留不可扫描诊断；空/相对PATH不会隐式搜索当前目录。没有候选退出4，参数/报告错误退出2；发现候选仅表示本机文件观察，artifact/provider未核、runtimeReady=unknown，不发布节点能力。

候选目录由Harness公开纯metadata API `ordessa_harness_api.command_discovery`发布；8个family的名称取自现有Harness声明，构建期生成客户端JSON镜像并验证digest。CLI不导入Harness/Server，扫描不执行候选程序、不查询版本、不安装/登录、不联网、不启动服务、不写全局Agent配置。三份Skill均增加init步骤与本机/远端、文件/运行就绪边界。

修改覆盖products下CLI、初始化模块、候选镜像、生成器、打包清单、测试、三Skill、README/ACCEPTANCE及真实安装使用脚本；Harness只新增公开metadata模块。版本升为0.1.0a2，使已有alpha用户可以正常升级。安装包为ignored `products/agent-tools/dist/bundle-0.1.0a2-init`；build exit0，9个payload的`sha256sum --check SHA256SUMS`全部通过、exit0。

验证命令使用本树专属`.venv-ordessa-py312/bin/python`：`-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q` **260P/0F、exit0、29.68s**（日志init-product-validation.txt）；其中新增初始化真实临时文件反例20项。release版本修改后`test_bundle.py test_distribution.py -q` **8P/0F、exit0、5.87s**（init-release-validation.txt），验证wheel内镜像、独立安装入口与资源。此前26项初始化/安装定向快照是修复前历史记录，不与260累加。三个Skill格式检查各exit0，只证明材料结构；不算独立Agent行为验收。

独立只读审阅发现两处边缘缺陷：已找到文件时仍须保留其他PATH访问失败，及FileNotFound后的链接检查也可能权限失败。已修复并增加两个反例；最终独立初始化复跑20P/0F、exit0、0.07s，无本单范围内新确定阻断。工单结构首跑缺三个必需段落退出1，补齐后13/13、exit0（init-work-order-validation.txt），只算资料结构。

再执行 `python products/agent-tools/acceptance/install_use.py`：fresh client venv安装实际0.1.0a2 wheel，确认无后台包，实际已安装entrypoint在服务启动前执行init，然后完成既有Profile真实隔离服务用例。总脚本exit0、27条安装/命令/停止记录（含预期拒绝的非零CLI结果），临时runtime清除、真实模型调用0，见init-installed-use.txt及install-use-exercise.json。本机实测发现codex `/usr/lib/chatgpt/resources/codex` 与pi `/home/maoqh/.local/bin/pi`；它们均未执行，runtimeReady仍unknown。27条记录不是新增27个pytest，也不能算Agent任务成功。

AT_013_DONE仅指Linux本机初始化门完成。Windows真实宿主/PATHEXT未验证；没有验证候选版本、认证、原生session或模型。整个Agent Tools仍PARTIAL：节点/任务/结果命令和生产Harness接纳/授权/共享scope/journal/fence缺口保持。此切片不改核心运行实现，未重复无关核心/Server全量；既有3个核心继承失败和11个Server固定基线同ID失败仍保留。无推送、主树合并、用户服务重启或全局配置修改。
