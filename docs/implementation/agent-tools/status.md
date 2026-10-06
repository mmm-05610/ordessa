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


### 2026-10-05 三家优先目标恢复 · 源码核查

当前HEAD3086825a6177438c042431cdb94812ded576ee6c，开工git status clean；已包含029收口0f786dfc34及030十家CODE_READY检查点，不把旧adce当现有实现快照。前一初始化轮为progress（CLI/Skill/source/evidence已落盘）；030终账并未证明节点/输入运行。当前核实核心AgentServices仍仅ProfileCatalog，AT008/009/010/011未完成。新增客户端存在，但真实协议关联/完成有缺陷：Codex嵌套turn形状未读、Pi0.86.1成功prompt无disposition，Claude控制stdio尚未消费。三个代理按家族不重叠消费者文件修复，主会话负责核心接纳/契约/整合。

本次用户目标改为Pi、Codex、Claude Code优先，其余七家保留。继续原工单并采用incremental-work-order纪律；单元合同见runtime-admission-contract.md。未经另行授权不安装更新第三方、不读用户认证/运行DB、不执行真实模型或用户服务重启。所有测试分L1合同、SQLite、L2真实进程和L3/L4产品任务记录；当前未新增运行可用声明。

### 2026-10-05 初始化入口复核与使用边界

用户再次要求CLI/Skill初始化探查。当前源码已具备`ordessa-agent init --json`，三Skill均包含步骤。本次实际源码入口exit0，发现Codex `/usr/lib/chatgpt/resources/codex`、Pi `/home/maoqh/.local/bin/pi`（链接目标`/home/maoqh/.pi/agent/bin/pi`），Claude Code未找到。命令未执行候选、未探版本、未使用认证，runtimeReady仍unknown。

定向命令：专属Python `-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_initialization.py -q`，20P/0F，exit0，0.06s。另fresh临时venv通过`pip install --no-index --no-deps`安装已有历史0.1.0a2-init wheel，实际已安装entrypoint `init --json` exit0；扫描完整，找到同两家。证据`evidence/init-recheck-20261005.json`，临时venv已自动清除。这不是当前未提交原生协议修改的新分发验收，也不代表Agent任务可运行。

独立只读复查指出目录限8家、仅PATH、命中不证明引擎身份、部分扫描需看诊断、Windows未验收。README补充8家范围/部分扫描/远端使用边界；三Skill明确本机初始化可选，缺本机二进制不阻止远端Profile操作。未扩展其余七家、未自动安装二进制或修改全局配置。

核心最新复跑：`-m pytest packages/backend/pacthold -q` 269P/3F，exit1，7.10s；三个同ID继承方向扫描失败仍指向测试目录旧SQLite import。原C1三字段及public facade新增失败已修复，未删断言。新RuntimeProvider接纳21P与原public合同34P定向55P已通过；节点发布20P、UnitRecords18P+原journal9P和managed运输31P是执行者定向证据，主会话整合复跑尚待完成。InputReservations当前正在审阅和加反例，尚不算已验收；CLI nodes/managedInput能力继续false。

### 三家核心/消费者基础整合复跑（未接产品运行）

主会话全products复跑570P/0F、exit0、68.36s，日志evidence/three-family-product-validation.txt。这是发布资源完整性修复前的源码快照；其后独立复查实际复现遗漏Usage仍可published，已在同publish transaction要求交接所有未released Usage、拒unknown，并在NodePublication要求真实unit use关系，保留失败反例。之后operation＋node＋input定向94P/0F exit0、1.98s（39＋25＋35，共享用例不能与570累计）。其后把028已定义connect(unitRef,authorizedLease)补入RuntimeProvider SPI，接纳＋node＋input再次复跑81项；整体仍不声明nodes可用。

协议复跑：Codex＋Claude消费者52P exit0、8.00s；Pi三文件69P exit0、2.76s（固定0.86.1真实无disposition receipt、unknown便利prompt拒新id、UI confirm等native shape一次响应；通知不授回应资格）；Claude纯planner43P exit0、0.14s。Pi原14P历史fixture中的虚构approval/action/text更新为官方confirm/method/confirmed响应，same-id和native回应断言仍保留。N003“无官方SDK”错误已撤回并引用固定SHA官方SDK文档，仍选择单一原生RPC通道，无fallback。

Harness共享scope/UnitRecords＋原OperationJournal32P exit0、0.36s；真实stdin managed transport31P exit0、0.42s。旧reserve_new同BEGIN IMMEDIATE接唯一owner scope guard；重启缺authority但有持久Unit拒，原request重放不作用；同scope旧跨channel互斥、scope_key损坏拒。此门不覆盖旧ProviderRestoration/Registration的owners.begin_restoration执行链，本产品不接该链。UnitRecords的scope释放、冷重启受限reconcile记录授权及生产原生证据端口仍未实现。

当前新增基础只复用唯一registry/SQLite operation/Usage、既有Harness journal及实际运输。生产prepare层须读取并核验真实immutable Profile manifest；publication primitive只核ref/步骤/owner投影，测试故意使用受控owner不能代替完整装配。InputReservations只持久reservation与一次Invocation claim；生产writer必须消费同context固定captureDigest/正文/native correlation，不允许另给正文/id。真实capture store、生产RuntimeOwner、public node管理入口、CLI附着、配置apply/结果/恢复链尚未闭合。真实模型0、安装第三方0、用户服务重启0，整体仍PARTIAL。

最终修复后主会话全products再次复跑 **575P/0F、exit0、68.53s**，日志evidence/three-family-product-final.txt；替代前570项源码快照，不累计成1145。最新节点25P、输入35P、runtime接纳21P定向组合81P/0F、exit0、1.60s。13份工单结构检查及git diff check均exit0，仅资料/格式证据。

生成新鲜分发`products/agent-tools/dist/bundle-0.1.0a2-three-family-foundations`，build exit0；9项payload SHA256校验exit0，未覆盖历史包。三Skill包含本机发现可选/远端操作边界。后续Pi生产接线责任及资源缺席行为写pi-owner-integration.md。全量绿仅覆盖当前测试定义，未补的production RuntimeOwner、CLI nodes/tasks、授权生产部署及真实模型L3/L4保持未完成。

新鲜wheel实际独立安装复验：fresh临时venv，pip --no-index --no-deps install exit0；实际entrypoint init --json exit0，发现同Codex/Pi、scanComplete=true、runtimeReady=unknown。证据evidence/init-current-wheel-20261005.json；临时venv清除，未执行候选或访问用户认证/服务。

### AU-1增量包接纳 · 2026-10-05

用户已确认AU001–AU005，按docs/implementation/work-orders/agent-unit-model的五份合同及五工单串行推进。本次HEAD仍3086825a6177438c042431cdb94812ded576ee6c；上一轮575P和三家/核心源码为实际progress，但未提交。现无运行子代理/共享写者，三位均completed。逐文件读取本包11个新增文件并记录SHA256到evidence/agent-unit-model/adoption.json，显式纳入接纳检查点，未改本包语义正文。

保留全部已暂存三家修复及CoreRegistry/Node/Input/journal/transport基础；品牌实现仍在products属于待AU003/AU004迁移，575P不满足AU A15发行边界，不将旧绿等同新目标完成。AU001主会话唯一共享作者，不派家族执行；AU003接口冻结后才允许各家独立包写权。继承raw pytest日志仅去行尾空白以通过diff格式检查，失败诊断及计数保留。当前只接纳/冻结准备，不标任何AU_DONE。真实模型0、安装更新第三方0、用户服务操作0。

### AU001 配置/Unit公开契约冻结切片

接纳检查点30c4ef5ac0，无其他活跃写者。已有C1 resource describe/acquire/release/reconcile与supported_contracts、Harness配置adapter claims/intents已核查；实施映射和CAS范围表见evidence/agent-unit-model/interface-map.md。不新增kind/provider注册中心。新增pacthold.agents.configuration，复用Profile声明校验/SecretRef与现有scoped refs；不可变ChangeRequest/Policy/Description/Snapshot/ItemResult/ChangeResult，仅合同无副作用/状态库。

RuntimeProvider增加describe_configuration/apply_configuration/query_change，显式升级agent-runtime/2；旧/1不作新管理接纳，历史引用不篡改。descriptor新增supportedMethods默认空，方法存在不代表能力。wire_contract保留默认Profile agent-assembly/1及digest，显式version=agent-assembly/2获得providers/nodes/配置/lifecycle冻结方法；当前Server/CLI尚不启用这些方法，AU004负责镜像/接线。

C层结构测试先33P exit0(0.08s)，增加wire版本反例后与runtime/node/input115P exit0(1.10s)；增加supportedMethods反例后configuration35P＋runtime21P=56P exit0(0.17s)。发行/旧Profile镜像8P exit0(6.35s)。这些只证明不可变编码、默认不restart/defer、ACK缺依据不能applied、partial逐项保留、secret/未知实际字段/跨scope/旧Runtime版本拒绝，未验证生产配置应用。

本包--strict结构5份通过。首次误提前加--batch完成门exit1，五单每单四stage未勾选；这是未完成门真实红，未删门/改合同或伪勾选。接纳commit前格式检查exit0，仅说明格式。AU001尚待核心回归与公开验证收口；下一AU002仍按串行依赖进入，不派三家执行。三家生产scope及CAS能力未核，M预算0，整体PARTIAL。

AU001补强：UnitInspection为当前owner只读来源，DirectoryBinding/epoch/ownership不由core猜测；版本未知snapshot允许sourceRevision=null且comparisonGuarantee=unavailable，未知kind允许scope=null/actions空，不制造支持。配置结构最终38P，连runtime/node/input119P/0F、exit0、1.15s；核心全回归269P/3F、exit1、7.38s，仍同三个已登记方向扫描ID，日志au001-core-regression.txt。未改继承红断言，未恢复legacy。AU001契约切片CODE_READY、整体门PARTIAL，后续AU002按已冻结契约推进；AU003之前不派三家包写者。

### 初始化入口再次实测 · 2026-10-05 02:10 UTC

用户再次要求初始化探查系统Harness二进制。现有CLI与三Skill已覆盖，无需重复新增入口；独立子代理只读复查确认。系统`python3 -m pytest` exit1（缺pytest），改用本树既有专属venv，未安装或修改全局依赖。

执行`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_initialization.py products/agent-tools/tests/test_distribution.py -q`：22P/0F、exit0、3.93s。含当前源码wheel构建、fresh隔离venv安装及实际entrypoint初始化受控目录；候选执行标记未创建。不是真实Harness任务验收。

执行`PYTHONPATH=products/agent-tools/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m ordessa_agent_tools init --json`：exit0，扫描完整，找到Codex `/usr/lib/chatgpt/resources/codex` 和Pi `/home/maoqh/.local/bin/pi`；Claude Code未找到。候选未执行，runtimeReady=unknown。范围仍为八家已审阅命令名及绝对PATH；版本、登录、真实运行、Windows实机及远端安装未验证。AU003拆包时必须同步迁移目录生成器的旧Harness汇总来源。AU002未提交工作保留，整体仍PARTIAL。

### AU002 核心配置协调阶段检查点

基线2ce8a151286760b427c58c8111fcf341060ce95f，旧三个执行者及初始化只读审阅者均已结束，主会话唯一共享写者。新增AgentConfiguration复用Environment的同一个OperationStore/DomainStore、受保护fingerprint及InvocationIssuer；规范target scope在同SQLite事务预留，固定Node/Unit/provider activation/目录/epoch/expected native revision。required未知配置或未取得材料发前拒绝；optional不送owner并逐项rejected；全optional不适用则无claim/无native dispatch、记录refused。

owner必须实际通过同Issuer的verify_and_consume；仅收到ACK、错误digest/scope、吞掉失败验证均unknown。同key重放只读原操作，unknown/deferred占用scope，查询只核实原attempt。确认后发布中断可从concluded step完成数据发布，不重新调owner。并发查询捕获step revision，迟到结果不替换后来的已记录结果；步骤内保留独立历史观察而非“最新配置”。inspect每次向当前owner查询，实例修改不保存Profile。Issuer成功验证标志复用原_live issued_条目，无新授权字典/持久权限源。

Server的agent_core_methods新增显式contract_version参数，默认agent-assembly/1及原Profile镜像不变。显式v2接四个配置公开方法，配置结果只投影operationRef/revision/status/configurationResult，不暴露内部授权/请求事实。版本冲突为CONFLICT_VERSION、同key异内容CONFLICT_REQUEST、授权不足FORBIDDEN、未实现节点操作CAPABILITY_UNSUPPORTED；supportedMethods不包含尚未实现的节点方法，nodes/managedInput仍false。生产部署未切v2，不宣称节点产品可用。

验证（Python均为本树专属venv）：初始management10P/0F exit0、0.87s；补optional/deferred/ACK/并发及中断反例22P/0F exit0、1.82s；补Server绑定、退役、真实SQLite冷开/原子回滚后management31项。`-m pytest evidence/agent-unit-model/test_management.py`与Profile wire、Invocation组合100P/0F exit0、2.46s。随后management/configuration合同/Profile wire/Invocation/runtime接纳/Node/input七文件组合219P/0F exit0、4.36s（真实路径均为docs/implementation/agent-tools/evidence/agent-unit-model或products/agent-tools/tests）。发行test_distribution.py＋test_bundle.py 8P/0F exit0、6.30s，含fresh wheel安装；不累计历史快照。核心全回归269P/3F exit1、7.12s，仍同三个继承方向扫描ID，原始日志au002-core-regression.txt；只去行尾空白，保留诊断。五单--strict结构检查exit0，不代表完成门。

C：同SQLite真实事务＋受控owner/authority，无真实Harness；P：本阶段未启动真实Harness（发行测试为独立客户端安装证据）；M：0/未授权。AU002_PARTIAL：C1材料acquire与SecretRef受权解析仍缺生产接线；不能把resourceRefs直接传成已取得材料。生产prepare/applyProfile/lifecycle/access、三家实际Unit/native确认与owner版本比较、完整迟到原生证据的provider持久保存待后续补齐。没有新DB版本或用户数据迁移，没有安装更新第三方/读用户认证/改登录/服务重启/模型调用。共享接口及管理反例已具阶段提交条件，依AU003前置进入三家接线；所有未完成门保留，整体PARTIAL，不勾伪Stages。

### 2026-10-05 初始化入口再次实测

用户要求CLI或Skill补初始化探查。本树现有 `ordessa-agent init --json` 及三份Skill步骤已核实；执行 `PYTHONPATH=products/agent-tools/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m ordessa_agent_tools init --json` exit0，扫描完整，发现Codex `/usr/lib/chatgpt/resources/codex`、Pi `/home/maoqh/.local/bin/pi`（实际链接目标 `/home/maoqh/.pi/agent/bin/pi`），Claude Code未找到。未执行候选、探版本、读登录凭据或启动服务；runtimeReady=unknown。

执行专属Python `-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_initialization.py -q`：20P/0F，exit0，0.06s。只验证初始化发现切片；实际Harness启动、认证、模型调用及远端资源仍未验证。没有新增依赖或全局配置修改，整体产品保持PARTIAL。

### 2026-10-05 AU003 独立包与公共运输检查点（PARTIAL）

真实前置HEAD 77a1d8a92c95f607db1671e8c700d96e4ccabe3f。三家执行者均已完成切片并明确释放写权；主会话独占共享运输、原journal、装配、Git及账本。保留所有已核对成果，不回退、不整树stash。新包与复用比较逐项核对后显式纳入；原UnitRecords导入改为延迟旧品牌入口，未移除旧三家注册，A15迁移仍未完成。

三家主会话最终串行执行（专属Python，分别以各包pyproject为-c）：Pi tests 86P/0F exit0、2.92s；Codex tests 48P/0F exit0、1.50s；Claude Code tests 112P/0F exit0、6.75s。早期Pi 81P/2F为迁移后旧异常类型导入，已改为公共运输异常，断言保留；Claude96P及Codex41P是较早快照，不与最终计数累加。新公共运输完整目录55P/0F exit0、6.37s（包含最终UTF-8跨LF反例），复用说明au003-transport-reuse.md。

独立Registry与导入隔离8P/0F exit0、0.85s：staged隐藏、同唯一Environment接纳、单家退役不影响其他家、只导入选定家及故意导入另一家使guard失败。原UnitRecords＋OperationJournal＋隔离guard组合36P/0F exit0、1.00s。曾误用不存在的tests/application/test_operation_journal.py，exit4、0 tests；改为实际tests/test_operation_journal.py后执行上述36项，未隐藏失败。

执行 packages/backend/harness-transport/tests/acceptance_install.py：六个本树包构建、fresh venv离线安装、pip check及三家fresh独立Registry，共12条命令全exit0，临时环境已清除；证据au003-fresh-provider-install.json。无Server/旧Harness/CLI/Claude SDK安装，未导入其他家。工单结构五单exit0、git diff --check exit0，只证明材料/格式。

C为受控契约及真实Python peer/SQLite；P为三家真实上游进程0（未验证），M为0（未授权）。Pi实际配置读写与原操作确认消费显式owner端口；Codex接prepare/start原UnitRecords但生产端口未接，配置写入待补；Claude选官方SDK显式适配，但SDK实物/真实Unit未装配。公共运输lease仅是stdin屏障，不授予执行权。生产原生回执持久保存、授权持续重核、scope释放/恢复、三家生命周期、核心prepare/Node纵向接线及产品品牌客户端迁出仍缺，AU003_PARTIAL，不勾完成门。没有第三方安装更新、用户认证/全局配置修改、服务重启、模型调用、push或主树合并。

### 2026-10-05 AU003 原配置attempt与原生RPC关联

独立包阶段检查点996463b39a后继续；主会话仅改原UnitRecords同OperationJournal，增加原配置attempt/ticket及native RPC pre-send绑定，不增加操作系统/配置缓存/数据库。完整接缝configuration-journal-port.md：prepare原Unit必须已confirmed；原applyConfiguration Context消费、规范scope/Node epoch重核；opening/unknown拒绝替代key，原correlation不给新ticket；配置实际native版本仍由提供者串行观察比较。只持久身份/版本/摘要/证据引用，ACK或当前相同值不能确认。

专属Python `-m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_unit_records.py -q` 首跑29P/15F exit1、0.63s，safe_json只接受映射而直接传了整数RPC id。改为requestId字段映射后44P/0F exit0、0.34s。追加并发/损坏/下一操作反例，并加原tests/test_operation_journal.py：最终56P/0F exit0、0.45s（配置24＋UnitRecords23＋journal9）。C为真实临时SQLite＋受控owner/verifier，尚未接Codex真实RPC，因此P/M未验证。未删断言或隐藏失败。

Codex执行者恢复写权仅plugins/harness/codex/**，接expectedVersion＋白名单defaults/readback＋实际pre-send id与原receipt；不写共享、不运行pytest。主会话独占原journal、装配与账本。Pi/Claude尚无生产确认端口，三家生命周期/core prepare/Node及CLI迁出缺口保持；AU003整体PARTIAL。

本接缝追加真实InvocationIssuer＋SqliteStorePort贯通5项：首跑56P/5F exit1、0.71s，受控流程漏掉prepare/start原步骤结论，核心正确拒绝后续claim。补真实owner结果后的原step concluded记录，保持全部门和断言；最终同三文件61P/0F exit0、0.66s（配置29＋UnitRecords23＋journal9）。issue之后撤销authority/activation/Directory/epoch均无新配置attempt，原possibly-dispatched claim保留；原配置query不重发。C层贯通，不升级为三家P/M。

### 2026-10-05 现有Codex隔离版本探测

独立于init文件扫描，在新临时HOME/CODEX_HOME/XDG与显式清空环境下，仅运行绝对路径 `/usr/lib/chatgpt/resources/codex --version`：子命令exit0，stdout `codex-cli 0.159.0`，二进制SHA256 d2752c52353401f7f6efbfcea68796f4f7a3d3e4769f5d1da53fa49d4856b72f。stderr提示临时CODEX_HOME子目录不存在、未创建PATH aliases。临时环境清除；未继承用户登录环境、未安装更新或启动服务、模型0。未对进程任意文件读取实施OS sandbox，因此证据不声称沙箱级用户文件隔离。

当前Codex实现依据固定0.157.1协议源码；观察到0.159.0不证明兼容，不自动更改pin或选该二进制运行Agent。证据codex-local-version-probe.json仅版本探测成功，compatibilityVerified=false/runtimeReady=unknown。此前init“不执行候选”仍指init自身，不能与此次独立版本探测混淆。原历史截断npm artifact仍是另一来源的已知缺口。

### 2026-10-05 AU003 Pi Unit与Codex配置增量冻结

HEAD9ef1dc2023上保持共享唯一作者。Codex与Pi执行者均完成切片并释放全部家族写权；Claude只读核对完成。Pi按原UnitRecords接prepare/start/query/access/connect，开进程前固定opening，实际原生两次get_state身份相符才确认；缺端口保持不支持。Codex默认配置batchWrite接expectedVersion、pre-send真实id、原receipt/readback；thread实际与defaults严格分离。仍缺生产端口、授权原生入口完整owner写cut、生命周期及核心纵向装配。

串行专属Python复跑：首个Codex命令未显式设置源PYTHONPATH，collection 3 errors、exit2、0 executed；补 `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src` 后 `-m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q` 65P/0F exit0、1.63s。审阅发现okOverridden条目unknown但attempt误confirmed导致scope释放，主会话修为unknown保留原waiter/排他，并加强原反例查询不重发；同命令最终65P/0F exit0、1.64s。`PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src` 同Pi包命令104P/0F exit0、2.93s。计数均为最终快照，不累计历史。git diff --check exit0。

Claude发现记录claude-unit-session-findings.md：SDK无prompt connect可有控制握手但不保证session，core允许Unit存在且nativeSessionRefs为空。原record_session不放宽；需明确Unit确认接缝及同pipe真实process/initialize证据。只读来源核对不是P/M。三家此次测试为C（含Python peer），真实家族P未验证、M0；没有安装更新/登录配置/用户服务操作或push。AU003_PARTIAL检查点后串行返回AU002补原许可逐write重核，再回AU003实现生产投影/Unit接线。

### 2026-10-05 AU002 核心持续重核补强

AU003增量e08916abae冻结/提交后三家写权全部释放，主会话串行返回AU002。新增公开Verifier/Issuer.verify_continuation复用原Context/claim/grant，不第二claim/新Context；原步骤结束、unknown、版本/epoch/目录/activation/authority变动即拒。缺continuation绑定不以初次verify代替。活跃effect证明保留到实际结论/失败/过期，容量满发前拒新claim；可信状态检查时释放Issuer锁，避免与部署admission锁互等，状态观察之后重核grant、最后核claim。详见invocation-continuation-port.md。

原authority测试两个反例加强：缓存容量必须保留active effect（先拒新read且证明仍存，真实concluded后才回收）；当前状态之前/之后两次authority回调都拒重入。没有删除原安全断言。作为核心接口影响的验收联动，唯一主会话同步这一现有产品integration测试（无第二写者），其余测试集中在本单允许的evidence目录。

执行专属Python `-m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py products/agent-tools/tests/integration/test_invocation_authority.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py products/agent-tools/tests/integration/test_runtime_admission.py products/agent-tools/tests/integration/test_node_publication.py products/agent-tools/tests/integration/test_managed_input_reservations.py -q`：最终189P/0F exit0、4.59s。初次小组合100P/2F exit1、2.83s；并发版186P exit0、4.49s；状态后grant重核版188P/1F exit1、3.65s，修回调次数断言后189P。曾误用input反例单数路径exit4、0 tests，后改为真实复数路径。历史快照不累计。新continuation24项，均C层；不证明native writer屏障或三家真实任务。

核心全回归中间快照 `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q`：269P/3F exit1、7.38s，仍同test_kernel_tree_has_no_import_of_server_harness_or_product、test_tripwire_planted_server_import_turns_the_guard_red、test_tripwire_from_import_form_is_detected_too；日志au002-continuation-core-regression.txt。最终共享改动后复跑日志au002-continuation-core-final.txt另记。AU002仍PARTIAL，准备/材料/Node/使用/生命周期生产协调未完成；本补强不等于核心收尾。P未启动，M0，无安装/登录/服务/用户数据库操作。

最终核心全回归269P/3F exit1、7.02s，同三个继承ID，au002-continuation-core-final.txt。两份raw日志只去行尾空白，计数及诊断保留。未恢复legacy或删除失败断言。

共享Issuer最后补强后，原配置journal贯通回归 `-m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_operation_journal.py -q`：61P/0F exit0、0.67s。确认原core claim消费/原query及owner journal不受持续重核改动破坏。
### 2026-10-05 AU002 准备前占用原子接缝

开工HEAD5790b5374b24bbf754f1e8a5cc60b32b1ac9beb3，工作树clean；实时代理清单三家均completed，无活跃家族写者。共享工作仍由主会话串行执行。NodePublication.reserve新增显式usages参数，复用原Store.reserve_operation同事务写Node身份、原操作和准备前资源占用；重放只读原预留，不追加占用。没有新数据库、注册中心或原生状态副本。协调方必须将固定资源配方包含在原输入digest，本接缝不替代生产Provider接纳或材料取得。

命令：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py products/agent-tools/tests/integration/test_node_publication.py -q`。首跑29P/1F exit1、0.49s，冷启动fixture未关闭原writer，正确触发WriterLockHeldError；第二次30P/1 teardown error exit1、0.50s，fixture重复close；修正资源清理后30P/0F exit0、0.46s。新增5项真实SQLite验证：dispatch前持有、错误holder和跨环境target导致身份/操作/Usage整体回滚、重放不追加占用、unknown及冷启动保留原占用且不重复claim。既有Node25项同跑；未删除断言、放宽writer锁或用takeover绕过。

C为真实SQLite受控协调证据；P/M均未运行，本次无第三方安装/更新、用户数据或配置操作、服务重启。生产prepare→Unit→Node、材料/SecretRef、完整使用与生命周期仍未完成，AU002_PARTIAL。此前核心全回归3个已登记失败仍保持，未用本次窄测宣称修复。下一步接固定Profile与当前Registry Provider的准备协调及实际owner证据。

### 2026-10-05 AU002 唯一 Registry 公开发现

开工HEAD84b980f619c6351daacc219fa3694d39799966c5，clean；上一轮是已提交占用接缝进展，本轮继续可行核心工作。新增Environment.agent_runtime_contributions与AgentServices.providers只观察唯一CoreRegistry当前active贡献；公开descriptor/host providerRef不泄漏实例对象，不调用品牌生命周期/安装探测。staged/draining排除，active接纳后篡改拒绝，空Registry仍检查读权限。显式v2 wire绑定既定agents.providers.list/describe并如实加入supportedMethods；默认v1不变，nodes.prepare仍未组成。详见provider-discovery-port.md。

命令 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py products/agent-tools/tests/integration/test_runtime_admission.py -q`：首跑64P/1F exit1、1.85s，新增测试误用WireError.code，修为既定family；最终65P exit0、2.32s（新发现13、管理31、接纳21）。涵盖公开wire、权限/引用反例、篡改、generation更新及副本隔离；没有修改既有断言。

Environment共享修改后核心全回归同命令 `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q`：269P/3F exit1、7.37s，仍已登记test_n4r1_kernel_direction的三个ID，触发源仍是既有核心test_closeout_environment_dispatch导入具体SQLite；没有把全量报绿或移除失败。P/M0，无第三方安装更新、用户服务/登录/数据操作。AU002仍PARTIAL：生产prepare/材料/SecretRef/Unit→Node装配与使用生命周期待接通；发现可用不等于产品可用。

### 2026-10-05 AU002 固定 Profile→Unit→Node 协调检查点（PARTIAL）

开工HEAD740012eeffa17d9e0d70416b51f55c01c13ef3f6，clean；主会话独占共享写权，三家completed成果保留，本轮没有另派家族写者。新增AgentAssembly及两个显式部署观察端口；复用原ProfileCatalog/唯一Registry/同SQLite OperationStore、原Issuer/NodePublication。固定Profile、当前Provider generation、安装/目录来源、epoch与受保护plan摘要后，原prepare/start各claim一次；外部Provider调用在admission锁外。原计划/私有根不写操作日志。准备结论和Unit Usage同事务写，发布时全部原持有Usage转Node。

公开AgentServices.assembly及显式v2 agents.nodes.prepare调用真实协调器；仅所需端口组成时supportedMethods才列prepare，缺席typed拒绝。默认v1不扩展，不谎称默认部署具备Harness。query只核实已claim原步骤，不派发缺失步骤；显式prepare可沿原结论继续未派发步骤或数据发布。旧/失败观察不能覆盖较新revision；并发重放不派发同claim。caller host路径与不符的DirectoryBinding拒绝。未组成C1材料/SecretRef时在claim前拒绝，不将raw resourceRef当材料。详见preparation-coordination-port.md。

验证命令统一解释器 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。初次 `-m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -q` 13P exit0、0.69s。增加公开服务/wire、材料和原查询反例后，与preparation_holds/provider_discovery/management/Node/runtime六文件112P exit0、3.44s。全products/agent-tools/tests/integration + 五份新增证据（test_assembly、test_provider_discovery、test_preparation_holds、test_management、test_invocation_continuation）初次340P exit0、11.04s；新增并发反例342P exit0、11.28s；读授权343P exit0、11.78s；最终 caller路径/目录反例后同命令346P exit0、11.75s。其中assembly23项，C层真实Profile/Registry/SQLite/Issuer和受控Provider/owner；不是三家实际进程。完整命令：`-m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py -q`。

核心回归 `-m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q` 269P/3F exit1、7.51s，仍同已登记test_kernel_tree_has_no_import_of_server_harness_or_product、test_tripwire_planted_server_import_turns_the_guard_red、test_tripwire_from_import_form_is_detected_too，既有测试导入具体SQLite触发方向扫描；没有删断言/skip/移动测试隐藏红。后续末端改动由346项覆盖，不把窄绿宣称核心全绿。diff-check exit0。P未运行，M0；没有第三方安装更新、用户数据库/凭据/全局配置写入、服务重启、push或主树合并。

剩余：三家prepare返回raw两字段UnitRef，Node公共绑定要求同owner/sourceRevision的完整来源引用，AU003需所属owner统一身份与投影，不能在CLI里补造；生产Context/receipt ports、安装版本与目录/作用权限、原生writer fence、C1材料/SecretRef、三家真实进程/冷恢复和stop/release/access尚未贯通。新协调器是C_READY切片，不是生产接线完成，也不等于AU002_DONE；核心与CLI/Skill/发行边界、AU003–005全部门仍继续。

### 2026-10-05 AU003 原 Unit 公开引用冻结

前置48bf7b159f5eb031bee70a400407e1871ce019a0，clean；实时三家状态completed，原成果已提交保留。AU002共享准备协调检查点后串行进入AU003，主会话仍独占共享接口/journal/Git/账本及验证。UnitReservation.public_ref从原journal immutable来源生成严格owner/source引用，sourceRevision不是native配置/session计数；resolve_unit_reference沿原授权read核实四字段，拒绝raw两字段/伪owner/来源/环境与缺权限。没有新增库或迁移。家族冻结消费说明unit-reference-port.md。

命令 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_operation_journal.py -q`：66P exit0、0.73s（新增引用5、原Unit23、配置29、journal9）。覆盖冷读取来源不变、session观察与引用版本分离、嵌套不可变、原授权及伪引用反例。C真实SQLite＋受控authority；P/M未运行。接下来Pi/Codex/Claude各自包独占接入，主会话串行复跑；本冻结不标AU003_DONE。

### 2026-10-05 AU003 三家完整引用与同配置目标检查点（PARTIAL）

真实HEAD3826f18204507314deaefbd1527475d1f5216fd1，保留19份已有未提交文件。核实Pi/Codex已释放写权；Claude interrupted，恢复其原窄切片补两项bool冒充generation反例，完成后明确释放。主会话独占共享journal、Git、账本与串行pytest，没有另开共享写者。共享配置目标从同原scope投影owner/source，原物理scope/key不变；配置attempt、Unit引用及授权目标保留完整来源。旧缺来源attempt查询拒绝且unknown占用保留，不补写或迁移用户DB。

Pi/Codex消费原Unit.public_ref与configuration_target_ref，不自造摘要；配置/发布/查询比较保留JSON类型。Claude prepare只返回原公开Unit引用，SDK接实际SystemMessage.data init session身份；坏身份保留unknown并拒新输入/配置写，不把init当任务完成或伪造session。阶段审阅保留所有原断言和历史限制。

本轮最终实际串行命令（解释器均 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`）：
- `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q`：120P/0F，exit0，1.81s。
- `<python> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_operation_journal.py -q`：68P/0F，exit0，0.80s；其中配置31、Unit28、journal9。新增完整目标及旧raw unknown不释放两项。
- `PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q`：130P/0F，exit0，6.80s；128为较早快照，不累加。
- `PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/pi/pyproject.toml plugins/harness/pi/tests -q`：172P/0F，exit0，2.96s；中断前同版本172P/2.99s不累加。
- `python3 /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py docs/implementation/work-orders/agent-unit-model/orders --strict`：五单结构exit0；`git diff --check` exit0。初次读取误用AU003.md不存在，exit1，已读取实际AU003-three-providers.md；不影响实现或测试。

C为受控owner/SDK以及真实临时SQLite/Python peer；三家真实上游进程P未验证，真实模型M0。核心继承3项方向扫描失败未在本窄测修复，不报全量绿。无安装更新/登录配置/用户服务/用户DB操作、push或主树合并。AU003仍PARTIAL：生产授权投影/原生writer fence与receipt端口、真实family→核心装配、Claude无session Unit确认、C1材料/SecretRef、生命周期与冷恢复、旧注册迁出、CLI/Skill薄化及发行验收继续。此检查点只冻结引用一致性，不能认定AU002或AU003收尾。

检查点23643bb9c7后继续共享入口复查：UnitRecords._authorize仍用Python == 比较provider/target，使受控verifier返回generation=True可以冒充固定整数1。先加providerRef/targetRef两项真实临时SQLite反例，`<python> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_unit_records.py -k verified_bool_generation -q`：0P/2F、28 deselected，exit1、0.17s，证明此前没有拒绝。改原入口为完整safe_json类型比较并检查Mapping，不另造权限链。最终同上三文件组合70P/0F exit0、0.69s；中间70P/0.60s不累加。拒绝后原reservation表仍空，断言保留。C层补强，不证明生产verifier缺陷或三家真实运行；P/M及其余缺口保持。

### 2026-10-05 AU003 Codex 原 journal 与核心装配纵向 C 验证

开工e157765da846b41720fe288df9837eda1058c625，clean；三家completed且已释放写权。主会话新建 test_codex_assembly.py/codex-assembly-evidence.md，使用真实独立CodexRuntimeProvider、原UnitRecords/OperationJournal及核心Profile/Registry/Issuer/Assembly/Node；原生客户端、authority与观察端口仍受控，不作为生产实现。Codex子代理仅只读复查，无共享写权。

首跑新增文件2P/1F exit1、0.53s：fixture错误地把Core recoveryCorrelation当原UnitRecords的request/operation/step JSON correlation，实际确认拒绝并保持unknown。按原关联格式修fixture后2P/1F exit1、0.62s：正常路径已published，但断言误用Node的bindings字段，改为原公开binding。原确认门与断言均保留。与原assembly组合26P exit0、1.66s；补四类撤权后29P exit0、1.80s；再补request冲突/native readback不符后最终31P exit0、2.21s（新增8＋原23）。历史快照不累加。

命令前缀为 `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml`；窄测尾部为 `docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py -q`。最终集成尾部为 `products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py -q`：354P/0F exit0、12.90s。此前新增6项时352P/12.26s不累加。diff-check exit0。

验证同原Unit/配置目标发布、原unknown占用及原query不重发，initialize之后authority/activation/directory/epoch变动均无thread/start。epoch旧ticket不能再写观察，保持opening，不释放fence。C真实SQLite＋真实家族Python实现，native/client仍fixture；P未验证，M0。没有运行实际Codex/SDK、安装更新/登录配置/用户服务/用户DB操作或push。生产writer授权与receipt冷恢复、Pi/Claude纵向接线、材料/SecretRef、生命周期/旧注册/薄客户端仍缺，不报AU003_DONE；已登记核心3个回归红仍未修复，集成绿不覆盖它们。

只读Codex审阅指出两个真实覆盖缺口：fixture只查询start correlation，无法证明prepare持久预留后丢reply恢复；同key重放在核心短路，无法证明第二合法key被原scope拒。已补原prepare query确认同Unit且不start（显式prepare才继续）及同realm第二request实际进入reserve_unit、捕获configuration scope already reserved并保留旧unknown/no新Unit/no新launch。fixture query_creation按原facts.stepId选关联，不将旧创建者元数据当授权。最终新增10项＋原assembly23为33P/0F exit0、2.40s；最终同集成命令356P/0F exit0、13.23s。早期31/354为此前快照，不累加、不冒充最终。C/P/M边界不变。

只读终审确认两项补强成立，未发现当前十项权限或unknown绕过；审阅无修改/pytest/Git。特别保留限制：fixture authenticated-request闭包不作通用生产查询owner；access surface为受控source且未装lease_port，connect不支持，published不能宣称完整可连接产品。显式纳入三个新/改文件形成阶段检查点，继续生产接缝与其余家族，不勾完成门。

### 2026-10-05 AU003 三家旧自动发现注册发行退役（PARTIAL）

真实前置421c1e17f101962c79287c217b109ece1fd74021、clean。Pi/Claude completed；Codex只读审阅结束明确无写权，不另开共享写者。核查发现原ordessa-harness发行元数据仍自动发现codex/claude/pi。仅撤下这三项agent_box.plugins条目，保留其他条目、组名、七家原声明与所有原源码/持久ID；不偷偷装独立提供者或新增fallback。边界和退出条件见legacy-discovery-retirement.md。显式旧factory/bundle与Server旧配置/运输装配尚在，不能报运行时旁路已消除。

命令 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_retired_family_discovery.py -q`：首版2P exit0、1.02s只检查wheel；追加fresh venv离线安装本树wheel并读实际installed entry_points后最终2P/0F exit0、3.30s。两项为改名factory/换group反例与真实发行metadata；build/create-venv/install-own-wheel/isolated-metadata-probe四个子命令全部exit0（断言由测试逐项检查）。无index/第三方安装/依赖解析/旧插件激活/原生进程/模型；此fresh安装仅本树包metadata，不证明依赖闭包或P层。

原源兼容/身份窄回归 `<python> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_core_identity.py plugins/harness/tests/test_codex_plugin.py plugins/harness/tests/test_codex_wiring.py -q`：32P/0F exit0、0.63s。保留全部断言；这些旧factory正例绿恰说明显式旧入口仍在，不把它当AU003_DONE。diff-check exit0。初盘点误读不存在entrypoint.py/server_plugin.py/registration.py/bootstrap.py路径，rg exit2，随后核实实际entrypoints.py、generic/factory.py和Server composition；无实现/测试结论依赖缺文件。

未更新现有用户安装，所以已安装旧包仍可带旧metadata；仅新构建发行已退役三项自动发现。C/本地发行证据新增，三家真实进程P未验证、模型M0，未改登录/用户数据/服务，未push或主树合并。生产owner/writer/receipt、显式旧注册消费者迁移、材料/SecretRef、完整生命周期、薄CLI/Skill与全发行验收继续；已登记核心3红未由本窄测修复。

### 2026-10-05 AU003 无 Session 原 Unit 确认接缝（PARTIAL）

前置a80f8602882cf25fcafbeb68c0499efe47a1ec73。上轮中断保留UnitRecords及两份测试改动，本轮核对三家completed/无写权、进程清单无pytest（rg exit1无匹配），未凭中断重启旧句柄；已知上轮11011组合测试已terminal356P/13.30s，随后共享99P/0.90s亦terminal。主会话继续唯一共享作者。

按Claude已有Unit/Session分离发现，在原OperationJournal加入harness_unit_confirmations，同原UnitId/scope/store/Issuer；NativeUnitBinding与NativeSessionBinding分开，版本harness-unit-confirmation/1是内部owner证据投影，不扩wire协议。新增显式可选NativeUnitEvidencePort，缺端口begin_unit发前拒；原start一次claim/ticket，opening/unknown保留占用。确认依赖原process/transport/initialize来源与同Unit owner，固定安装/根及当前存活由原owner实际核实。结构校验不能代替真实证据，未装生产端口不报ready。record_session仍严格原session，不造default或sessionId。

冷reconcile只授query原request/op/step/input摘要、CAS原revision，不补ticket/launch。实际Issuer+SQLite反例核实原claim消费、cold查询不改Core unknown（核心须另消费观察）、撤权拒读。Unit/Session两条start同事务互斥。只读Claude审阅指出notCreated高revision损坏可重置与后续session关联缺口；前者已补严格state/revision及孤立digest拒绝，又补八项两表/两创建路径交叉反例。后者明确未实现：需原InputAttempt关联真实session的record-only入口，不再次start。完整冻结native-unit-confirmation-port.md。

命令解释器为 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`。共享尾部 `-m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_native_unit_confirmation.py plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_operation_journal.py -q`：初85P/0.92s，补冷确认90P/0.87s，原摘要91P/0.84s，损坏拒绝96P/0.78s，真实Issuer97P/0.93s，历史缺行与来源变动99P/0.90s；最终两路交叉107P/0F exit0、0.93s（新37＋原70）。均exit0，历史快照不累加。既有configuration helper仅新增start_native_session默认True，可用False核Unit单独start，原断言及默认行为保留。

最终集成命令：`PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py -q`：356P/0F exit0、13.40s。diff-check exit0。核心既有3项方向扫描红未在此修复，不报核心全绿。

只修改本树源码/临时测试journal，未读或迁移用户DB，历史Unit无确认行typed拒绝，不补造来源；已有session合同仍可读。C真实SQLite/Issuer＋受控owner，P未验证、M0。无实际SDK/Claude/模型启动、第三方安装更新、登录/服务操作、push或主树合并。继续Claude owner接线、首次Session association、三家生产writer/receipt/生命周期、材料/SecretRef与旧消费者/薄客户端迁出；本接缝不标AU003_DONE。

9e1a6db19b检查点后继续：Claude恢复仅其家族目录写权，实现显式owner effect/query协调，主会话仍独占共享。Pi只读盘点确认首输入当前强制Session：inputs.NativeInputState/reserve/claim_dispatch均依赖sessionRef。原InvocationContext已固定原输入身份，但Unit目标首次输入权限、跨draft首关联占用和Session关联尚未定义；不能用default或UnitRef冒充Session。提案现存evidence/agent-unit-model/sessionless-first-input-proposal.md，已向用户请求采用显式Unit full-native输入权限＋原占用＋原InputAttempt只读association；确认前不改核心输入协议，不以等待阻塞Claude start/query。提问时路径写成docs/implementation/agent-tools/sessionless-first-input-proposal.md，随后按本单写路径收归证据目录，本文给出实际位置。尚无用户答复，不假定授权。

用户随后明确选择“采用提案，沿原机制扩展”。首输入Unit权限/跨draft占用/原InputAttempt只读Session关联口径已授权，提案已标确认，未宣称实现。继续先纳入现Claude AU003切片，再由主会话串行回AU002共享输入并补AU003 journal association，保持工单串行及共享唯一作者。原Session路径与已持久请求语义保留，无用户数据迁移或模型授权。

### 2026-10-05 AU003 Claude 原 Unit start/query 检查点（PARTIAL）

前置577014c450，Claude仅家族目录作者已明确释放，Pi/Codex只读。新增ClaudeUnitCoordinator，复用原UnitRecords/Issuer/Unit确认：begin_unit先持久opening并消费原start，opaque Context传给显式部署effect owner，逐作用continuation＋dispatch_guard；unknown保留原handle，不close/kill/重启/补ticket。冷query仅沿原start correlation/input/CAS核owner，不开启SDK/新loop/daemon。缺生产ports不advertise能力；prepare correlation公开lookup仍缺，不能用start替代。

主会话串行实际命令 `PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q` 首144P exit0、7.85s。只读终审发现既有generic unit_port只声明方法而不核同records/verifier，补typed拒及三项反例；另补confirmed owner失效和prepare context不能查询start两项。最终149P/0F exit0、8.07s（新增19＋原130）。没有删断言或skip。

共享集成沿上一段完整356项命令，修改generic owner门前356P/0F exit0、12.70s；该测试不导入Claude，末端Claude改动由149项覆盖，不把集成绿当生产全绿。子代理compile/collect exit0；其初plain python exit127和fixture路径收集exit2已修；主会话两次只读猜测不存在test_claude_provider.py、docs/owner-ports.md exit2/1，随后按实际路径读取，不形成实现依据。diff-check exit0。

C真实SQLite/Issuer＋受控effect/native owner；SDK实际执行桥、FencedSdkTransport生产装配、真实Claude证据owner、prepare查询、首输入association仍缺。P未验证、M0；核心继承3项方向扫描红未修。无第三方安装更新/真实模型/用户服务及数据操作、push或主树合并。AU003不报DONE，收妥此切片后串行回AU002已批准首输入接缝。

### 2026-10-05 AU002 Sessionless 首输入预留/claim 检查点（PARTIAL）

前置d637a65946，clean；家族作者已释放，主会话唯一共享写者，Pi只读终审。按577014c450用户批准口径增加SessionlessNativeInputState：原完整UnitRef、原Unit确认与Session缺席来源，不填default/假Session。原Session DTO及context解释保留；首次原submitInput目标为完整Unit，原Issuer明确授权这一目标后claim一次。原DomainStore中Node＋Unit首次占用与draft及operation同事务预留，跨draft/key、terminal、仅观察到Session均保留占用；claim重读原holder。核心不发送输入、不建新ledger。冻结见sessionless-input-reservation-port.md。

当前只完成预留/claim，所有首次占用held；尚无record-only association、原输入作用已知与Session关联双证据确认、原publish/Usage转移，不能宣称多输入可用或AU002_DONE。Session观察也不能绕到原Session路径。下一切片沿原record_operation_step/publish_operation补来源与CAS；owner journal/core库不是跨库原子事务，崩溃窗须保留占用并只读恢复。

新增真实Issuer bool反例先跑 `<python> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py -k retain_json_types -q`：0P/2F、19 deselected，exit1、0.28s，证明原provider/grant target普通dict比较接受True==1。改safe_json后首组合73P/60F exit1、3.70s，原因是主会话误将可空delegation/acquisition直接传入只接受mapping的safe_json；修为mapping包装，原断言保留，133P exit0、2.68s。Pi审阅再补before-config嵌套bool来源与safe_json比较。独立连接测试初135P/1F exit1、2.79s，原writer锁正确拒绝不同owner；改为显式同测试writer owner（无takeover），并保留不同writer拒绝反例，最终137P/0F exit0、2.84s。新25项＋原managed-input/authority/continuation112，不累加快照。

定向完整命令：`/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py products/agent-tools/tests/integration/test_managed_input_reservations.py products/agent-tools/tests/integration/test_invocation_authority.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py -q`。初新增19项＋原managed35为54P exit0、1.73s；最终137为授权及并发补强后的组合。独立Environment/连接同步读absent竞争原Domain CAS，只有一个操作/draft/first占用，输家事务回滚；不是第二生产writer许可。

最终集成完整命令：`PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py -q`：381P/0F exit0、13.93s。共享原四文件107P exit0、0.71s；Claude全家族149P exit0、7.98s，均在授权比较末端修改后串行完成。

核心全回归 `<python> -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F exit1、6.37s，仍已登记三个test_n4r1_kernel_direction ID、既有test_closeout_environment_dispatch导入ordessa_persistence_sqlite触发扫描。未删断言/skip或移动失败，缺实际Claude/worker等资源记录ABSENT，不算绿。只读探测不存在products/agent-tools/tests/conftest.py exit2已改为按已有evidence测试显式插入integration路径，不依赖缺文件。全部实际测试句柄terminal。

C临时SQLite/真实Issuer＋受控capture/native/authority；无owner journal关联或native输入writer，P未验证、M0。未安装更新第三方、修改用户DB/凭据/全局配置或重启服务，未push/主树合并。CLI/Skill/发行、三家生产owner/权限/writer/receipt、完整生命周期及原首次关联/出版仍继续。

Pi只读终审确认before-config/Issuer类型比较及独立连接CAS反例补齐；未新增修改/测试/Git。保持reserve＋claim切片与association/publish缺口分账。工单结构五项exit0、diff-check exit0；显式纳入本轮两个核心文件、测试、冻结说明及status形成检查点，继续原InputAttempt association与发布，不标完成门。

### 2026-10-05 AU002 原 InputAttempt Session 只读关联检查点（PARTIAL）

上轮为progress：e4714eba00改变核心与真实测试证据；本轮实际HEAD同提交、clean、三家completed无写权，保留所有既有成果。主会话唯一共享作者，Pi仅只读设计/终审；无共享并发写者。原query可读取未claim步骤，不能据此声称输入已发生。新增原InvocationVerifier.verify_claimed_query只读核验：成功query continuation、同Store原step/intent/opIntentDigest/digest/kind/provider/原epoch，前后重核，不claim/发ticket。普通query含义不变。

原UnitRecords新增显式可选NativeInputAssociationEvidencePort、query_input_session/reconcile_input_session，固定原request/op/step/inputDigest/provider/完整Unit/Node/epoch/nativeCorrelation/Unit确认/历史Session absence/CapturedInputRef。原step还须完整Unit submitInput、非cleanup、无额外delegation；prepare/stop claim不能冒充首输入。实际native字节、receipt、owner进程/运输/固定根和原absence由显式owner独立核实，core参数摘要/claim/ACK都不是实际输入证明。缺owner默认拒绝，未装控制fixture为生产port。

关联直接写同harness_unit_sessions.native_json/digest，显式harness-input-session-association/1，不建新表/ledger/Session真值。原notCreated1 CAS到新confirmed2；只有明确新codec完整证明/owner重核允许2，旧三字段confirmed2仍红，旧start>=3仍沿原native_evidence合同。native_facts投影原三字段，association_facts提供原版本证明。旧数据不迁移、不补造来源；方法不start/input/ticket，不改Core input unknown/首次Domain held/Usage。双证据确认与publication/转移尚未实现，不能宣称后续输入已可接纳。

定向命令 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py -q --tb=short`：初34P exit0、3.35s；补原action/kind/claim/query身份及旧codec反例后47P exit0、4.61s；冷owner失效/两journal并发CAS/SQL回滚/过期51P exit0、5.07s；commit后观察52P exit0、4.92s；最终原prepare action不能作input53P/0F exit0、4.52s。此前快照不累加。新关联测试未出现pytest失败，原断言保留，未新增skip。

Pi审阅要求区分commit前失败与commit后观察失效，已补实际反例：初证明成功、写Session行commit、返回前owner第二次核验失败，调用抛错但confirmed2已经持久；不能报整次回滚。原Core unknown/fence held不变，冷query读取同原来源，旧CAS1不能重写或补输入。另一末端反例确认prepare action在调用native owner前拒绝。只读终审确认补强成立，无修改/复跑/Git。冻结input-session-association-port.md；已更新已批准提案的实施进度，未重写授权裁决。

最终集成完整命令：`PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py -q --tb=short`：434P/0F exit0、19.32s（原381＋新53）。较早433P/19.01s不累加。共享原四文件107P exit0、0.94s；Claude全家族149P exit0、8.08s。核心 `<python> -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F exit1、7.51s，仍已登记三个test_n4r1_kernel_direction ID，既有test_closeout_environment_dispatch导入具体SQLite触发扫描；没有删除/移出断言或skip，缺worker/Claude等资源仍ABSENT，不当绿。全部测试句柄terminal。

C真实临时SQLite/Issuer＋受控capture/native proof，三家生产native owner/真实进程P未验证，M0。生产字节/receipt/transport fence、目录/Invocation权限装配、C1材料/SecretRef、原双证据publication、完整生命周期、CLI/Skill薄化与完整发行验收继续；AU002/AU003不报DONE。只改本树/临时测试DB，无用户DB迁移、第三方安装更新/登录/凭据/全局配置/用户服务操作、真实模型或push/主树合并。

工单结构五项strict exit0、diff-check exit0。显式纳入本轮两个源码文件、53项测试、两份证据文档与status形成检查点；下一切片沿原Core双证据确认和publication转移占用/Usage，不按Session出现或terminal状态自动释放。

### 2026-10-05 AU002 原首输入双证据结论与发布转移（PARTIAL）

前置de29fb04da9b61329079b1ab9f3eb9f20cba71c2、clean；三家completed已释放写权，Pi/Codex仅只读设计和终审，主会话唯一共享作者。用户已批准首输入提案，不另问常规实现权限。依照本包主会话共享契约写权，必要接口改动在现有environment-api的OperationStorePort声明，复用依据是原结论/Usage事务；没有新增共享包、持久表、ledger或wire方法。

增加显式可选FirstInputObservationPort与reconcile_first_input：原opaque query/claimed-query核原request/op/step/digest/provider/完整Unit/Node/epoch/capture/nativeCorrelation与原Unit确认/absence。owner分别核原Session association与原输入作用已知（不冒充任务完成）；缺端口/ACK/一份事实不成立即拒或unknown，不start/claim/补ticket/发输入。原Core policy/registry/Node/Unit及当前Invocation权限在观察后、结论前和发布前重核。数据出处见first-input-publication-port.md，生产owner不以fixture替代。

原record_operation_step结论固定双证据和原Usage recipe，first fence仍held。原publish_operation同事务CAS marker原revision1→resolved2、operation和全部Usages→固定Node active；失败整体回滚，不released资源绕门。原published重放保持CAS1和原Usage/result，不按已转Node集合或最新revision重算。resolved须核原published Operation/concluded step/result，held+published拒为损坏。后续Session输入只接受同原关联引用/revision；sessionless、仅观察Session、仅terminal或换Session不能二次首输。原结果managed-first-input-result/1是内部结果投影，不新增通用翻译层。

Pi首次审阅发现漏报Usage恢复死角：先concluded再由publish检漏，会固定不完整recipe、阻止补齐。已沿原Store补兼容可选require_complete_usages=False（首次输入显式True），同结论事务任何写前核全部retained operation-held Usage包含于active mutations，原holder/target/rights/revision CAS保留。完整选项进入原result digest。漏报unknown或active Usage均保持原step和Usage，补完整原receipt后可只读恢复发布。没有删断言/skip。旧弱口径已经冻结的不完整concluded数据拒绝改写，不做用户数据迁移；本次True新结论不会产生该死角。

实际解释器均 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，测试主会话串行，最终句柄全部terminal：
- `<python> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py -q --tb=short`：首32P/0F exit0、3.34s；补policy/unknown Usage后36P/0F exit0、4.14s。未出现pytest失败。
- `<python> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py -q --tb=short`：5P/0F exit0、1.53s。实际Registry/Node/ManagedInput/Issuer/UnitRecords与两原SQLite文件；native/capture/authority/effect仍受控。
- 两新文件同上述命令组合：修完整Usage事务后43P/0F exit0、6.07s；补迟到CAS/ACK/Session路径/flag反例48P exit0、6.61s；终审新增active遗漏及强结论True幂等/False不能冒认，最终50P/0F exit0、7.23s（45核心＋5纵向）。历史快照不累加。
- 最终完整集成命令：`PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py -q --tb=short`：484P/0F exit0、25.65s（原434＋新50）。较早482P/25.99s为新增48项时快照，不累加。
- `<python> -m pytest -c packages/backend/environment-api/pyproject.toml packages/backend/environment-api/tests packages/backend/persistence-sqlite/tests -q --tb=short`：70P/0F exit0、0.91s；原Store默认False与环境合同回归保留。
- `<python> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_native_unit_confirmation.py plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_operation_journal.py -q --tb=short`：107P/0F exit0、0.97s。
- `<python> -m pytest -c packages/backend/pacthold/pyproject.toml packages/backend/pacthold/tests -q --tb=short`：269P/3F exit1、7.71s。仍已登记test_n4r1_kernel_direction三个失败，既有test_closeout_environment_dispatch导入具体SQLite触发扫描；未删除、移动失败或skip。worker/Claude等ABSENT保持未验证，不算绿。

原journal association已commit/Core写失败以及concluded未publish均保持占用，沿原查询/recipe恢复；晚到使用观察前原revision，不刷新覆盖。纵向cold_owner仅重开Harness journal，Core/Environment/Issuer沿用，不能声称完整进程重启恢复。Pi/Codex终审均未发现新窄切片阻断，无测试/写入/Git；其建议两项额外反例已由主会话实际补跑。两次只读猜测不存在AU002-core-assembly.md/test_operation_records.py路径已纠正，无实现/测试结论依赖缺文件。

C真实临时SQLite/实际Core＋受控native owner，P未验证、M0。生产receipt/writer fence、目录/Invocation授权接线、完整冷启动/生命周期、材料/SecretRef、三家公开生产装配、CLI/Skill薄化及发行闭包仍继续，AU002/AU003不报DONE。只改本树及测试临时文件；无第三方安装更新、真实模型、用户DB/凭据/全局配置或用户服务操作，未push/合并主树。核验工单结构和diff后显式纳入检查点，继续后续，不把本接缝绿当产品完成。

本切片末端五工单strict结构exit0、git diff --check exit0，50项新C与最终扩大回归均已terminal。显式stage上述三份原源码/接口、两份新测试及四份证据/账本；不裸add其他dirty。检查点后继续生产接缝与余下工单，goal保持active。

### 2026-10-05 AU003 原生预分配帧与 Core claim 实际写入接缝（PARTIAL）

本轮起点 ffe569dee03c5a5d9d9467824e71f0a8399df89a、clean；保留既有首次双证据与出版。Codex/Pi 家族执行者各持自己的 prefix，交回后释放；主会话唯一共享 transport/合同/整合/测试/Git/账本作者。终审三家仅只读，不跑测试或共享写入。用户确认 sessionless 原机制提案持续有效，不追加常规批准门。

共享 PreparedFramePool 是客户端有界一次性原生帧 handle，固定 UTF-8 JSONL、原生 ID/协议/SHA；不发 IO/claim、不保存操作或 Session真值。家族先分配 req-N、后 capture/reserve/claim，再 dispatch 原字节。before_write(actual_wire_bytes) 在原 transport 实际 stdin 锁及 lease 校验内核 capture、native ID/协议和原 opaque Context/完整Unit/Provider/input digest/权限。失败消费 handle，无换键/重发。Codex/Pi 保留各自原生协议，不给 Claude 造 request-id；品牌能力声明未扩张。冻结说明 prepared-native-input-port.md。

终审补两条实际竞争缺口：guard 在同锁内撤销 writer 后旧 view 已无法 markUnknown，及原 write成功后等待回执期间 revoke 可让新 writer接替。已在 transport 原锁内 latch unknown，并在实际write前登记原 ID类型/ID→原lease 的live IO项；家族验证原RPC receipt才ACK，ACK只删IO项，原stale lease晚到ACK不清unknown/不许新writer。初始stale lease未入guard即拒，不毒化另一合法writer。guard/callback抛CodexRpcError/PiCommandError不冒充原回执。Pi send_prompt全路径串行，unknown先于cached settled，晚到事件原样保存。裸 channel/ACK仍可信owner内部，不作产品公开句柄。此IO项不是持久ledger，也不证明任务完成。

实际失败与修正记录：Codex家族首149P/1F exit1、2.09s，新测试将原events tuple误写list，修为tuple并保留空集合断言；随后150P exit0、2.42s。Pi首201P/3F exit1、3.26s：一项event-hook遗漏已保存agent_end，修期望为完整原事件序列；两项缺实际端口路径触发PreparedFrameRefused漏导入，补源码导入。fake peer补显式ACK端口，缺ACK在消费前拒。Pi旧单例 raw prompt-after-timeout 实际0P/1F exit1、0.11s、37 deselected，按用户unknown不重发要求改为拒第二prompt，保留原get_state响应、sent数量和便利输入拒绝断言；未删除断言/skip隐藏失败。

新Core纵向首次6P/2F exit1、1.15s：撤权后的再次claim先报InvocationAuthorityRefused而非UnknownResultError，测试先明确核撤权拒绝，再恢复测试grant并核原claim不能重发；没有弱化为宽异常。之后8P exit0、1.22s；终审补正确SHA但错ID/类型/协议、bool correlation入门拒、异issuer Context、核验后显式owner fence反例，最终20P exit0。正确核验后单独变更授权bool不被声称为跨域原子IO fence；生产必须协调原writer显式cut，不能倒销已写输入。

本轮实际解释器 `<python>` 均 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`，主会话所有测试串行，最终每个句柄terminal：
- `<python> -m pytest -c packages/backend/harness-transport/pyproject.toml packages/backend/harness-transport/tests -q --tb=short`：100P/0F exit0、6.94s（原55＋新45）。较早96P/6.81s为补末端反例前快照，不累加。
- `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q --tb=short`：154P/0F exit0、2.10s（原120＋新34）。
- `PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/pi/pyproject.toml plugins/harness/pi/tests -q --tb=short`：213P/0F exit0、3.20s（原172＋新41）。
- `PYTHONPATH=plugins/harness/claude-code/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/claude-code/pyproject.toml plugins/harness/claude-code/tests -q --tb=short`：149P/0F exit0、8.18s；共享transport扩大后的原家族回归。
- `PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_prepared_input_claim.py -q --tb=short`：20P/0F exit0、2.62s。实际 Core/SQLite/Issuer、实际临时Python peer独立算收到字节SHA/大小；capture/Unit/native状态/authority受控。原 ACK后 Core step仍possibly-dispatched、首hold held，不能换key/draft再首输。
- 最终完整集成命令：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_prepared_input_claim.py -q --tb=short`：504P/0F exit0、27.83s（原484＋新20）。较早492P/27.04s为新8项时快照，不累加。

本轮未改Core源码；上轮核心269P/3F是历史回归、既有test_n4r1_kernel_direction具体SQLite导入扫描三个红未消除，本轮不补称全Core绿。五工单strict exit0、git diff --check exit0只是结构/格式检查。没有原生Codex/Pi/Claude真实进程P或模型M，M0；Python peers是实际受控pipe C，不偷换分类。本轮新增140项C：45运输＋34Codex＋41Pi＋20纵向；各最终集合分账，原回归快照不累加。

当前缺口：生产capture/native receipt/effect/Session proof/UnitRecords journal与writer/lease装配、Directory/Invocation部署授权、C1材料/SecretRef、完整冷Core重启与生命周期、品牌旧bundle/factory/Server迁移、CLI节点/任务/结果、三Skill和完整发行闭包。Claude native user input缺Core要求request-id继续不支持，不自创协议。AU002/AU003及总产品均PARTIAL，不报DONE；缺资源ABSENT保持未验证。无第三方安装更新/模型/登录/用户DB/凭据/全局配置/用户服务修改，无push/主树合并。费用无法精确取得，unknown。显式纳入本轮实际路径检查点后继续余下工单。

### 2026-10-05 AU003 Codex 原配置 journal hook 实际写入屏障（PARTIAL）

前置8da9c5dad0d87767d6018cf49c47fd5242b03846、clean；上一goal轮源码/测试/提交是真实progress。三家终审completed无写权，主会话唯一共享/整合/Git/测试/账本作者，Codex仅只读盘点及终审。完整重核AU包design/contracts/migration/acceptance与AU002/003工单；不移工作树、不回退、未改合同替代裁决。

发现现有command_once在transport锁外执行原配置持久bind/revalidate后再send_raw的窗口。本次原RPC冻结，hook移入send_frame实际stdin锁和原lease校验；provider原revalidate→bind→revalidate、实际ID、canonical request digest、native expectedVersion、原Unit/scope/ticket和journal都不变。hook成功后登记pending/ACK等待/admitted；已知nativeerror仅原admitted且ACK与pending由原receipt清除，guard同类异常但pending尚空不冒认。缺必要三端口或无效turn目标在ID/hook前拒绝，迟到receipt不开放unknown。无新增core/ledger/wire。说明codex-configuration-write-barrier.md。

原command_once 5项观察点改send_frame实际写入，仍保bind→send、相同原payload/ID、hook失败无IO与pending空、hook修改不能改nativebytes、timeout保原ID且回查无重发。新增12项barrier/异常/目标/实际pipe反例。原真实 UnitRecords＋SQLite和实际Python pipe新增3C：ACK-only、receipt-lost、bind-then-fence，guard内独立journal读确认实际write前原ID/digest已commit；ACK无effect证明仍unknown，不保存actual、不开放第二scope请求。其authority/native evidence/Session owner是受控fixture，不冒充真实CoreIssuer或生产native proof。

真实命令、结果与失败修正，测试主会话串行且最终句柄全部terminal；`<python>`为 `/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python`：
- `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q --tb=short`：源码修改后原154P exit0、2.09s；补8项后162P exit0、2.15s；补late-receipt原断言162P exit0、2.13s；终审补4无效turn目标，最终166P/0F exit0、2.15s（原154＋新12）。快照不累加；客户端测试未出现pytest失败。
- `PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_configuration_barrier.py -q --tb=short`：首0P/3F exit1、0.51s，主会话误用轻fixture的evidence属性，真实NativeConfigurationAttempt没有该属性；改为真实confirmation=None，保留无证明断言，最终3P/0F exit0、0.46s。没有删除/skip/扩大异常隐藏失败。
- `<python> -m pytest -c plugins/harness/pyproject.toml plugins/harness/tests/test_native_unit_confirmation.py plugins/harness/tests/test_unit_records.py plugins/harness/tests/test_unit_configuration_records.py plugins/harness/tests/test_operation_journal.py -q --tb=short`：107P/0F exit0、1.03s，原journal回归。
- 完整集成：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:packages/backend/harness-transport/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/integration docs/implementation/agent-tools/evidence/agent-unit-model/test_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_assembly.py docs/implementation/agent-tools/evidence/agent-unit-model/test_provider_discovery.py docs/implementation/agent-tools/evidence/agent-unit-model/test_preparation_holds.py docs/implementation/agent-tools/evidence/agent-unit-model/test_management.py docs/implementation/agent-tools/evidence/agent-unit-model/test_invocation_continuation.py docs/implementation/agent-tools/evidence/agent-unit-model/test_sessionless_input.py docs/implementation/agent-tools/evidence/agent-unit-model/test_input_session_association.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_first_input_journal_publication.py docs/implementation/agent-tools/evidence/agent-unit-model/test_prepared_input_claim.py docs/implementation/agent-tools/evidence/agent-unit-model/test_codex_configuration_barrier.py -q --tb=short`：507P/0F exit0、27.79s（原504＋新3）。

本轮Core/Pi/Claude/shared transport无源码变更，未重复声称其上轮结果为本轮。历史Core269P/3F三个已登记kernel_direction红仍未解决，缺真实资源仍ABSENT。Codex只读审阅无安全阻断，建议无效turn前置拒绝已补实际反例；无执行者测试/Git。工单strict/diff-check只是结构/格式门，不代产品可用。新增15C，不含真实Codex P/M，M0；没构建新fresh wheel，不把旧安装收据当新源码发行验收。

当前生产capture保存与原字节读取、原receipt/effect owner、Directory/Invocation/lease装配、C1材料/SecretRef、冷Core恢复与完整生命周期、旧三家bundle/factory/Server迁移、薄CLI/三Skill/发行仍缺。Codex当前start已创建原thread，可沿普通Session输入继续；只initialize的sessionless Codex原thread创建与原turn帧/correlation映射未冻结，保持不支持，不发明两步协议或复用另一操作证明。其余原核准sessionlessCore机制继续保留。生产owner未装不报enabled，AU002/AU003/整体产品均PARTIAL。

只改本树/测试临时DB/自建Python peers，未改用户DB/凭据/全局配置、安装第三方、执行模型/登录、重启用户服务、push/合并主树。费用unknown。显式纳入本轮七个路径检查点后继续下一生产装配切片，goal保持active。

### 2026-10-05 AU004 Provider CLI / 显式 v2 发现 / fresh wheel（PARTIAL）

前置 c7ca893cbfa1b58eb5c543282788e6028f54384f，现存修改均主会话本轮成果，保留三家既有修复；live agents 核验仅 au003_codex completed，无另一共享写者。上一状态回复仅核查，无新增实现，本轮完成复验、源码说明、证据及检查点，属于 progress。沿既有 incremental-work-order 与 AU 章程继续；合同不重写。

公开 providers list/describe 已实现，完整 DefinitionRef 支持 JSON/@file；双 wire 版本严格 schema/digest/类型和方法校验，v1 Profile 保留，Provider 不 fallback。Provider 方法闭集从 public Protocol/DTO 构建时生成，无客户端私有 imports 或新 wire。输出 registryObserved/runtimeVerified=false。可选部署显式 v2 仅精确 local registry read，无 native providers/execute/Directory/Invocation 授权；默认 v1 和 mismatch 拒绝。实际 wheel 从临时洁净源码构建，拒 native_clients，三镜像与checksum一致；源码旧品牌副本仍未迁完，Skill 本轮未改，不把打包排除算 AU003_DONE。

详情、完整命令与失败账：[provider-cli-v2-evidence.md](provider-cli-v2-evidence.md)。实际 PY 为本树外既有 .venv-ordessa-py312/bin/python，所有测试主会话串行且 terminal：CLI/契约/发行组合90P exit0、34.26s；部署/真实独立Server组合17P exit0、6.38s；完整Core/SQLite/Python-pipe集成511P exit0、29.84s；末端新增 @file 安装describe 与严格缺席授权断言复验3P exit0、5.76s。本轮新增23项，原发行2项加强，不累加组合快照。两次初失败分别包数据夹带旧客户端1P/1F和缺席ref误猜NOT_FOUND导致15P/1F，已保留断言并修实现或严格按现有核心错误映射校准。未删断言/skip/兼容链复活。公开schema生成和五工单strict exit0、diff-check exit0仅资料门。

真实隔离Server属于服务进程证据，不代表真实 Harness P 或任务 M。三家 production owner/capture/receipt/effect/Session/writer、部署授权、材料/SecretRef、冷恢复/完整生命周期、旧装配迁移、Node/config/tasks/results CLI、三Skill与发行闭包仍缺。历史Core269P/3F未本轮修复，缺资源ABSENT，M0。未安装更新第三方、改登录/用户DB/凭据/全局配置、重启用户服务、push/主树合并；费用 unknown。Codex只读终审确认闭方法集/洁净bundle/精确read权限无新增阻断，无执行者写入/测试/Git。整体PARTIAL；显式纳入本轮路径后继续下一公开接缝和生产装配。

### 2026-10-05 AU004 owner 配置描述薄 CLI（PARTIAL）

前置04013950a5，clean；主会话仍唯一共享写者，Codex只读盘点与审阅，无子代理测试/Git。检查点后继续源码推进：新增 `ordessa-agent nodes configuration describe @node-ref.json --config service.json --service local --json`。只调用既有公开 agents.nodes.configuration.describe，完整三字段NodeRef环境/正整数generation（拒bool）先核验；描述DTO严格字段/类型/actions/scope/modes/confirmation/supportStatus及重复种类/版本校验，禁止已知Token回显。没有原生代码、写入、第二配置真值或新wire。输出configurationDescriptionObserved，runtimeVerified=false、configurationValuesObserved=false；描述supported不代表真实运行ready。

公开接缝盘点发现schema有nodes.list/read但Server尚未实绑/宣告，输出wrapper及缺席行为需要补核心公开合同；没有nodes.get/nodes.query wire，不自造。configuration.describe/inspect已有owner读绑定，configurationManagement仅reflect同storeissuer写能力，不能拿false挡纯读；本轮只落describe，inspect下一切片。configuration.query会_record/_finish_recorded/publish，是原操作核实协调，不冒充无作用读取。

主会话串行命令，PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python：
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py -q --tb=short`：11P/0F exit0、5.97s。实际原Sqlite发布Node＋真实Core handlers＋临时HTTP和受控owner，没有production native。正例同Environment无issuer也能按read权限describe，不创建配置操作、dispatch/queryCalls均0；反例缺方法、拒权限、bool/外环境/额外principal、重复描述、未知actions/status、缺scope和Token回显。没有pytest失败或删除/skip断言。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_provider_cli.py products/agent-tools/tests/test_profile_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/contracts/test_profile_wire.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`：101P/0F exit0、38.69s（原90＋新11，快照不累加）。fresh wheel新nodes/describe help可用，运行时Core/Server/Harness/品牌clients缺席；已安装describe正向原生服务全链路未验证。实际bundle仍green。源码Core/server/三家未改，不声称本轮跑了其全回归；真实Harness P缺席、M0；历史Core3红仍登记。全部测试句柄terminal，diff-check exit0。

README同步命令/证据边界。本轮新增configuration.py与11项测试，修改cli、发行help断言和README，账本显式纳入检查点。nodes绑定/inspect/apply/query/access/lifecycle/tasks/results、三Skill、production owner/权限/冷恢复/迁移与AU005仍继续，不标AU004_DONE。未改用户数据/凭据/全局配置、更新第三方、登录、模型、用户服务、push/主树合并，费用unknown。

Codex只读终审确认describe DTO类型/枚举/身份与无issuer读路径，无安全阻断；建议畸形类型反例，主会话新增8项真实HTTP响应：descriptions对象/元素bool、actions对象或bool、modes嵌套list、scope对象、confirmation list、inputSchema list。另补2项缺发布Node和已retired owner，分别严格4/3拒绝、calls3且effect/query0。末端同定向命令最终21P/0F exit0、11.28s（原11＋新10），未出现pytest失败。源码行为未变，仅测试补强；101组合是新10加入前结果，不声称111完整组合已跑。工单strict/diff-check前述通过；本次diff-check再exit0。全部句柄terminal，审阅者无写入/测试/Git。检查点继续配置观察、节点公开接缝与生产装配。

### 2026-10-05 AU004 owner 实际配置快照 CLI（PARTIAL）

前置56f595495b，clean；上一轮两个源码/测试检查点是真实progress。本轮开工核验仅au003_codex completed无写者，主会话独占共享源码/Git/测试/账本；Codex继续只读终审。保留三家修复与原公开合同。实现 `nodes configuration inspect`，与describe相同完整NodeRef JSON/@file、supportedMethods和read授权路径，不以configurationManagement=false挡纯读，不调用apply/query，不另存配置事实。

snapshot DTO沿public ConfigurationSnapshot：unit/scope/confirmation引用保持opaque且同环境、带时区observedAt、sourceRevision（可None）、声明的comparisonGuarantee、unknownItems唯一且不得混actual，desired/pending不混actual。嵌套凭据仅允许既有完整SecretRef或None，拒明文与伪SecretRef，32层上限；不发明leaf协议或自行把Profile填成actual。正确Node/Unit/scope owner一致仍由原Core manager和原Node binding核验，客户端不复制私有owner。输出configurationSnapshotObserved/valuesObserved=true仅表此次服务观察，runtimeVerified=false保留，无native/task READY。

主会话串行：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py -q --tb=short`：41P/0F exit0、21.90s（原21＋新增20）。新正例保实际model/native版本，unknown-fields保None/unavailable/未知tools，SecretRef完整保留；反例跨环境unit/scope/proof、缺proof、None版本却承诺comparison、bool版本/时间、无时区、未知与actual重叠/重复/对象、desired、明文/伪SecretRef/Token回显、缺方法/拒权限。全部effect/queryCalls0，原配置Operation不存在。实际Core/Sqlite已发布Node＋临时HTTP＋受控owner，C而非原生P。

`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_distribution.py -q --tb=short`：2P/0F exit0、5.32s。原发行测试加强：从fresh source build自己wheel、fresh venv no-index/no-deps安装、独立CLI进程以@NodeRef对同原Core/受控owner HTTP实际describe和inspect，原model/version/证据不变、六次HTTP调用、dispatch/query0。没有安装第三方或改全局配置。受控HTTP fixture不是Uvicorn真实Server；生产服务/原生Harness/模型全链路仍未验证，不借fresh安装结果改写分级。

PY解释器为/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python。本轮所有上述测试无pytest失败。Codex只读终审确认SecretRef/类型/unknown/version/时间与原DTO一致，无新增阻断，无写入/测试/Git。README同步命令/证据/未验范围；五工单strict exit0、diff-check exit0，仅格式资料门。未改core/server/三家源码，历史Core269P/3F仍登记，不称新全Core通过。production权限/capture/receipt/effect/Session/writer、材料/SecretRef解析、冷恢复、nodes binding、配置apply/query/access/lifecycle/tasks/results、三Skill/旧装配迁移/全纵向验收仍缺；AU002–005与总产品PARTIAL。模型M0，原生P缺席。无push/合并主树/更新第三方/登录/用户服务/用户DB/凭据/全局配置改动。费用unknown。显式检查点后继续。

本轮最终组合：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_provider_cli.py products/agent-tools/tests/test_profile_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/contracts/test_profile_wire.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`：131P/0F exit0、56.16s（原90＋本配置41）。组合完成后另补实际TCP关闭与服务OUTCOME_UNKNOWN两项，定向 `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py -k disconnect_or_unknown -q --tb=short`：2P/0F、41 deselected，exit0、1.23s。分别严格SERVICE_UNAVAILABLE4/refused与OUTCOME_UNKNOWN6/unknown、retryable=false、只发一次inspect、无快照/证据冒认且effect/query0。源码未再变，未声称133完整组合已跑。新增本轮22项，snapshot本切片总43（含原21），不累加结果。全部测试句柄terminal。末端diff-check exit0；显式stage本轮六路径，下一切片继续，不关闭goal。

### 2026-10-05 AU004 配置修改与原操作核实 CLI（PARTIAL）

前置f592a7f230031363fd1178afe28286da59dd1ed6，clean，上一轮源码/测试检查点是真实progress；live agents核验仅Codex completed无共享写者。主会话唯一源码/测试/Git/账本作者，Codex只读审阅。新增nodes configuration apply --file（完整固定change，不另生业务requestId）与query（原NodeRef＋operationRef，不带change）；沿既有v2公开wire/Core管理入口及原请求键、fingerprint、operation ledger，无新协议/客户端记录/品牌实现。RequestId来自change文件且成为wire ID；expectedRevision与declarations/policy不可省，SecretRef安全树/decl IDs/资源同env/显式bool及参数shape发前核验。query是原操作核实，可能记录证据/完成原发布，不称纯日志读。

严格核operation projection、revision类型、item enum/IDs完整覆盖、overall一致、applied确认完整且同op/scope/unit/环境、可缺snapshot；引用比较使用canonical JSON，不以True==1或1.0==1冒認。published含unknown/deferred拒，回执坏/断连apply返回unknown且不自动重发。既有Core的deferred保持unknown；restartRequired pending不重启；partial exit6并保留逐项结果，不自动回滚；版本/同键异内容冲突5。allDeclarationsApplied仅published且整体applied，不把部分作用false误写成零作用，实际项留原itemResults。envelope原operationRef来自有效Core结果，未知回执不推导身份。

真实命令与失败分账：PY=/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python，主会话串行，所有句柄terminal。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py -k 'apply or unknown_same' -q --tb=short`：8P、43 deselected，exit0、4.72s；一次作用＋同键原结果重放、版本/异内容冲突、unknown原query核实恢复、不重发、缺权限/issuer与参数/foreign材料拒。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py -k 'known_owner or partial_applied or invalid_apply or committed_apply' -q --tb=short`：首14P/1F、51 deselected，exit1、8.37s。测试误把deferred猜成pending0；实际Core保留unknown6，修为严格unknown6，不改核心合同或放宽错误。补JSON类型身份与published/deferred反例后最终18P/0F、51 deselected，exit0、9.91s。原断言保持，无skip/删除。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_distribution.py -q --tb=short`：2P exit0、5.62s。fresh wheel/fresh venv本产品no-index/no-deps安装，独立CLI进程actual Core＋Sqlite发布Node＋受控owner HTTP完成describe/inspect/apply/query，唯一作用1、query nativeCalls0、十二个HTTP请求、无token回显。受控HTTP不是完整Uvicorn/原生Harness。
- `PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_provider_cli.py products/agent-tools/tests/test_profile_cli.py products/agent-tools/tests/test_discovery.py products/agent-tools/tests/contracts/test_profile_wire.py products/agent-tools/tests/test_distribution.py products/agent-tools/tests/test_bundle.py -q --tb=short`：159P/0F exit0、71.74s。
- 末端证据字段改allDeclarationsApplied并直读published/overall，同步partial/fresh断言及README后：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_distribution.py -q --tb=short`：71P/0F exit0、42.82s。原43配置＋新增26＝69，另发行2加强，快照不累加。五工单strict/diff-check exit0仅格式门。

新增反例保留wrongop/boolrevision/无proof/unknown冒published/错overall/缺item/foreignproof/明文/Token/引用bool或float、receipt-lost。丢回执测试从原Core记录取得operationRef再query，仅验证原记录查询不重发；调用者尚未取得operationRef时的公开按请求键查找入口仍缺，不把测试直接读库包装为产品恢复方案。README明确此限制。

Codex两轮只读审阅发现Python引用等价漏洞与deferred组合，CLI已补。既有Core DTO/manager有同类==比较，尚需下一AU002接缝做真实反例与类型敏感核验，不把客户端拒绝替代核心防线。当前未改Core/server/三家源码，历史269P/3F仍红；生产权限/capture/receipt/effect/Session/writer、材料SecretRef解析、冷恢复、nodes绑定/生命周期/access/tasks/results、三Skill/旧装配迁移及全纵向P/M仍缺，总产品/AU002–005 PARTIAL。M0、原生P缺席；无第三方更新/登录/用户DB/凭据/全局配置/用户服务重启/push/主树合并，费用unknown。显式纳入本轮六路径检查点后继续核心类型身份防线。

### 2026-10-05 AU002 配置 DTO/manager 精确 JSON 身份（PARTIAL）

前置03dfe83233，clean，上一CLI检查点真实progress。主会话唯一共享写者，Codex仅只读终审，不修改/测试/Git。发现既有Core把Bool/Int/Float opaque引用用Python相等，新增4 DTO＋4原SQLite管理反例修复前全部红（0P/8F exit1、0.60s，69 deselected）；真实错confirmation原先被published。改DTO及manager引用/原fence/query/观察比较为原safe_json类型敏感比较，包value安全处理None，不增加引用schema/表/registry/配置真值。受控effect已发生时只保unknown，不能声称无作用；当前owner类型错则发前拒。证据与完整命令：[configuration-json-identity-evidence.md](configuration-json-identity-evidence.md)。

两文件组合修复后77P exit0、2.69s；补当前Unit/provider/target bool/float6项后83P exit0、2.93s。终审建议补实际apply，而非仅inspect推断，已加apply＋无Operation/Step断言，定向6P exit0、0.36s、35 deselected。新增14项，不累加组合快照。完整集成563P exit0、29.72s（原511＋首次纳入configuration_contract42＋manager新10）。核心全回归269P/3F exit1、7.89s，三个已登记kernel_direction失败仍既有closeout测试导入具体SQLite，无新来源；未删/skip/移走失败，worker/claude等ABSENT仍未验证。DTO/SQLite/Core＋受控owner C，不生产nativeP/M。

Codex只读终审确认_none/类型身份/原操作未知与重放未旁路，apply发前补实际反例已完成。本轮未改CLI/server/三家源码；生产权限/capture/receipt/effect/Session/writer、材料/SecretRef、冷恢复、节点wire/请求键恢复/完整生命周期、三Skill/旧装配迁移与全P/M仍缺，不报DONE。M0，无用户DB/凭据/全局配置/服务/登录/第三方更新/push/主树合并，费用unknown。检查点后继续。

核心修改后的调用方实际回归：`PY -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests/test_configuration_cli.py products/agent-tools/tests/test_distribution.py -q --tb=short`：71P/0F exit0、42.66s。fresh CLI安装/四管理命令回归保持原结果；仅受控owner而非真实Harness。五工单strict/diff-check exit0，所有测试terminal。显式纳入两核心文件、两真实反例文件、新证据与status形成检查点；不隐藏已登记三红，不终结总goal。

### 2026-10-05 AU003 三家产品协议源去重（PARTIAL）

前置471cf57ec1e6d6b1f2e9938fcc6bfcb3f9a8eb84、clean；上一源码/测试检查点真实progress，保留三家修复。主会话唯一共享作者/Git/测试/账本。并行Codex/Pi/Claude只读审阅无写权/测试/Git；本轮新开2个readonly审阅者，费用unknown，未开共享写者/外树。按migration核所有消费方与独有能力，产品生产源码无旧三客户端消费者；独立包保留并增强旧功能，旧大包生产/配置/附件资源不等同于协议副本，不整目录删除。

删除产品codex/pi/claude_code三源码及五重复测试，不留shim；82旧测试函数81 AST原样承接，唯一Pi旧raw prompt-after-unknown已在此前独立guard加强为拒raw input而保get_state/sent数，未为绿删断言。修独立Codex测试Message仍导入product的残留；余七家+运输的19文件SHA全部不变，init说明只暂存未启用，wheel仍全排除。源码/test映射与SHA见evidence/agent-unit-model/native-client-ownership-migration.json；详情：[native-client-source-ownership.md](native-client-source-ownership.md)。新增7项源码所有权门含planted imports反例，先验证源/provider/剩余资源存在，缺席不算绿。

主会话串行，PY=.venv-ordessa-py312/bin/python完整路径/命令见上述证据：Codex166P exit0、2.14s；Pi213P exit0、3.19s；Claude149P exit0、7.84s；ownership7P exit0、0.13s；其余七家+运输113P exit0、25.92s；发行/fresh wheel/fresh venv CLI9P exit0、7.87s。均C，实际Python peers/HTTP不冒原生P/M。无pytest失败，全部句柄terminal。五工单strict/diff-check/hash exit0仅结构；本轮无Core/server/三家协议实现变动，历史Core269P/3F仍红，不声称新全Core绿。

审阅揭示旧entrypoints/genericfactory/plugin facade仍有三家直接runtime路线，model bridge/plugin/live_service与Server聚合也仍需迁移，自动entrypoint去掉不足以证明旧三家无法启用。下一串行切片封住直接旧factory，另保品牌纯配置/附件/部署能力再迁。生产owner/授权/材料/冷恢复/生命周期、节点wire/按request查找unknown操作、三Skill/全发行/真实P与M仍缺。整体AU002–005 PARTIAL，M0，缺资源ABSENT。未第三方安装更新/登录/用户数据/凭据/全局配置/服务操作/push/合并主树，费用unknown。显式纳入本轮源码删除、独立测试修正、两证据、README、边界门及status检查点后继续，不缩小goal。

### 2026-10-05 AU003 旧直接工厂退役（PARTIAL）

前置7f7332b288，保留主会话上一切片factory/plugin/新反例未提交成果；本轮live agents均completed，没有另一共享写者。前一状态问答为no progress，仅核查记录；本轮继续实际修改、复验和记账。主会话独占源码/Git/测试/账本，Codex只读审阅。旧genericfactory三家在registry/context/storage前typed拒，旧named/default entry同拒，HarnessesPlugin不再注册旧runtime/credential。metadata/continuation与持久ID不变，未迁四个genericfamily及ProfileStore构造正控保留，不混同暂存七家clients。

完整命令、旧测试迁移依据、失败修正和证据边界：[retired-direct-factories.md](retired-direct-factories.md)。guard前新8门0P/8F exit1、0.20s；guard后旧注册期待38P/2F exit1、0.61s；迁移旧测试且补正控，误用definition.provider_id导致41P/4F exit1、0.76s，修为原稳定ID，源码不放宽。最终factory/identity/metadata/continuation/ProfileStore47P/0F exit0、0.70s；独立Codex原Core/SQLite/UnitRecords正反例＋wheel自动发现门＋runtime admission33P/0F exit0、5.09s。新增13项，不累加快照；所有句柄terminal。无skip/恢复compat；正提供者经新核心接入实际复跑。

本切片只完成直接factory退役，旧modelplugin/bridge/live_service、Server/native_runtime及server_acp仍需迁，独有品牌能力未删。无三家协议/Core/CLI源码变更，不冒本轮全回归。历史Core3红仍登记。生产权限/材料/证据owner/冷恢复/全生命周期、节点wire/unknown按request恢复、tasks/results/三Skill/全纵向发行仍PARTIAL；C不是原生P或模型M，M0，资源ABSENT。未第三方安装更新/登录/用户数据/凭据/全局配置/服务操作/push/主树合并，费用unknown。核对并显式stage本轮文件形成检查点后继续。

Codex只读复核无宽拒/metadata丢失/测试绿化，但发现GenericExecutionProvider构造仍可绕factory传三家definition。主会话加同型构造拒绝＋3个builtin definition反例，未碰adapter/source协议；全树直接消费仅generic.factory。第一个定向组合末端再跑50P/0F exit0、0.67s，新增门16项。33项结果在此构造器补强前，不声称已重跑；model/Server旧路继续登记待迁。五工单strict与diff-check exit0仅资料门，所有句柄terminal。显式纳入切片检查点后继续。

### 2026-10-05 AU004 Node发布记录 list/inspect（PARTIAL）

前置b61d4dd8ce，clean；主会话唯一共享源码/Core/Server/CLI/Git/测试/账本作者，Codex只读终审，无另一写者。旧model/Server迁移仍需生产owner/独有能力承接，本轮推进不依赖它们的已有Node只读公开接缝。Server绑定并宣告原agents.nodes.list/read，原同Environment/Store/读权限，list逐Node核验。Core新增唯一wrapper/record required投影，read缺席None原样映射null；不是新状态机/registry/查询provider调用或operation写入。v2镜像生成，v1/provider镜像未变。

CLI `nodes list`/`nodes inspect @NodeRef`，仅公开方法，精确完整身份/原lineage/owner/source/Usage/surface投影，拒bool/float/foreign/duplicate/私有/token/额外ready。missing inspect4，缺storage/权限拒，不把其当空列表；nodePreparation=false不挡只读。provider退役或冷无registry的历史发布可读，不声称native ready。evidence=nodePublicationObserved/runtimeVerified=false，无第二配置/会话事实。

完整命令、映射、失败修正与发行证据：[node-observation-evidence.md](node-observation-evidence.md)。新wire14＋原publication25组合39P exit0、0.68s；新CLI25＋加强原发行2组合27P exit0、19.21s；CLI/契约/发行全组合184P exit0、85.32s。实现前wire3P/6F0.27s、safe_json根误用7P/2F0.28s、CLI错误码误猜24P/1F13.38s皆exit1已保留修正，未skip/删断言或复活compat。新增39项，不累加快照。实际fresh CLI安装对受控HTTP/Core/SQLite6命令18请求，唯一配置作用1，不把C当Uvicorn/nativeP/M。

Codex只读终审未发现新安全阻断，确认只读权/缺席/冷观察/类型身份/私有拒，未测试/写入/Git。生产权限/材料/证据owner/冷恢复与全生命周期、tasks/results/三Skill/全纵向发行及旧model/Server迁移仍缺。整体PARTIAL，M0、资源ABSENT；历史Core3红仍须单列。无用户数据/凭据/全局配置/登录/用户服务操作/第三方更新安装/模型/push/主树合并，成本unknown。检查点后继续未完成工单，不标AU004_DONE。

本轮全现存16个AU证据模块＋产品integration实际首586P/1F exit1、34.95s，旧uncomposed门仍期待list拒；保留同门，改为未实现stop并加无query/无原operation/不宣告stop断言。最终587P/0F exit0、34.32s，不skip/删门/恢复旧行为。全Core实际269P/3F exit1、7.62s、0skip，仍原kernel_direction三红，具体SQLite测试导入未移走；worker/sidecar/acpclosure/claude等ABSENT继续。末端新增真实隔离Uvicorn/Server Node权限负例：公开方法＋Bearer不授读，当前v2部署只有Profile/registry权，nodes list/inspect均拒3，不冒空成功；v2定向2P/2deselected exit0、2.20s。Server进程P不是nativeHarnessP，无生产Node正向/M。新1加入在587之后，不声称588全组合已跑；本切片新增40项，原发行2加强。五工单strict/schema/diff-check exit0仅资料门，测试句柄全部terminal。显式纳入13路径检查点后继续，整体仍PARTIAL。

### 2026-10-05 AU004 三Skill同步／AU005 显式bundle安装使用（PARTIAL）

前置88375b109d clean；主会话唯一源码/测试/Git/账本作者，开一只读Skill指令演练代理，不授权共享写入、测试或Git。采用skill-creator现有更新/结构校验与独立演练规则，三Skill同步Node/配置公开方法、完整身份/owner版本、unknown无operationRef恢复缺口、task/lifecycle未实现与init非运行保证。ACCEPTANCE清除过期Profile-only/当前240测说法，保留未验证与继承红事实。

演练发现capabilities因Profile fingerprint缺席误挡其他领域发现，实际Core新3反例先2P/1F exit1、0.74s；改为仅doctor/profiles需要Profile保障。初Node/discovery/bundle55P exit0、23.02s。另三独立包stdlib-only wheel禁入新3反例旧gate0P/3F exit1、0.05s；加client-only Python门，最终相同组合58P/0F exit0、23.04s。新增6项，不skip/删断言，三次Skill quick_validate各exit0仅结构。完整命令/分层与只读演练见[skills-current-cli-evidence.md](skills-current-cli-evidence.md)。

自有fresh bundle生成exit0；实际安装exercise改显式--bundle/--evidence、复用完整checksum/wheel门，不自动用旧包或覆盖记录。实际新bundle安装＋隔离既有Server＋独立CLI27条命令记录exit0/M0/runtimecleaned，正回执evidence/install-use-node-skills-88375b.json；真实临时client/server/skills workspace已不存在。相同证据再次调用预期exit1，原SHA不变/records空证明未安装或启服务；failed JSON是这项负例。wheel SHA19b8359bbaedfdf6f784e8b3f8232c6077922845870442fdd5cd76831f9fea1e，ignored dist不入Git；加强门末端复核实际bundle通过。

是Server进程安装/目录/CAS/鉴权/离线/自有重启证据，不是生产Node/config/nativeHarnessP或M；三Skill打包/局部复制/只读解释不称真实Agent任务使用。Core/Server/三家源码未改，未冒本轮全回归；前轮Core3红与ABSENT继续。production权限/材料/证据owner/冷恢复/full lifecycle、旧model/Server迁移、prepare/tasks/results及全纵向仍PARTIAL。无用户DB/凭据/全局配置/登录/用户服务/第三方安装更新/模型/push/主树合并，成本unknown。测试句柄terminal，工单strict/diff-check仅结构；显式纳入本轮文件检查点后继续。

只读终审无命令/覆盖/C-P-M阻断，建议observed supports不能硬写false及helper别误选非client wheel，已修README/use Skill/ACCEPTANCE与精确wheel glob；末端Skill结构exit0。随后全新final bundle生成exit0＋新回执install-use-node-skills-final-88375b.json实际完整安装27命令exit0/M0/cleaned；新wheel SHA6a8c08b9c9a6ed174b162f7d22a2792d4040051e45530e65492ec27a931dcc9e。末端真实JSON/已删除workspace/3Skill源字节/严格bundle门核验exit0，新旧27快照不累加，不覆盖旧资产；最终bundle路径dist/bundle-0.1.0a2-node-skills-final-88375b。上述全15路径显式纳入检查点后继续核心公开接缝/生命周期/旧装配，整体goal active。

### 2026-10-05 AU002 Node发布引用精确JSON身份（PARTIAL）

前置962e290e36f34a487e5a621d5ca11f37c4eb8d14、clean；上一状态问答仅核查，无实现progress。本轮重新核对live agents全completed，主会话仍唯一共享源码/测试/Git/账本写者，Codex只读审阅。保留三家修复与现有新路径，未另开共享写者。

18项真实SQLite反例先0P/18F exit1、0.45s，证实NodePublication Python mapping equality混认true/1/1.0，错owner/lineage可发布且reservation/source来源篡改可冷读。复用原safe_json精确比较固定引用，含当前admitted provider、owner、step receipt、Usage holder/target、原发布result与冷来源；没有新协议/核心/存储/原生状态。owner leaf仍opaque，整数身份正例保留。发前拒绝保持operation running/Usage revision1；冷拒保持published/Usage2，不重发或改结论。

完整命令、失败与范围：[node-json-identity.md](evidence/agent-unit-model/node-json-identity.md)。初publication＋wire57P exit0、0.93s；补receipt/Unit target/holder/admitted bool/float与opaque正例后66P exit0、1.07s（新增27，不累加快照）。产品integration296P exit0、10.72s；Node/config CLI＋fresh发行99P exit0、57.48s；全Core269P/3F exit1、7.83s、0skip，仍既有kernel_direction三红/SQLite具体测试导入来源，未删断言/skip/移走失败。worker/sidecar/ACP closure/Claude资源ABSENT继续，不假绿。五工单strict/diff-check exit0仅结构。所有测试句柄terminal。

Codex只读审阅未发现阻断，建议step receipt与Unit Usage target反例已经实补。此切片是Core/SQLite/受控owner C，真实native P与M缺席，M0。production授权/材料/capture/receipt/effect/Session owner、完整生命周期/冷恢复、旧Model/Server装配、prepare/tasks/results CLI及全纵向验收仍PARTIAL。没有第三方安装更新/登录/模型/用户DB/凭据/全局配置/用户服务操作/push/主树合并；费用unknown。显式纳入本轮两源码/测试、证据与账本检查点后继续，不终结goal。

只读终审发现admitted_provider反例初稿同时改Node generation导致可能早拒；主会话限制只改provider引用、保Node/lineage并断言currently admitted provider确切拒绝来源。修正后publication＋wire66P exit0、1.12s；末端opaque定向9P/43deselected exit0、0.18s，源码未再变，296/99/Core结果在这次测试定位改进前，不冒新全跑。

### 2026-10-05 AU004 固定请求 Node prepare CLI（PARTIAL）

前置a6d93c926dcfa7549e27bd303eb2421c2d8741f7、clean；上一核心修复提交和实测属于progress。本轮live agents全completed，主会话唯一共享源码/Core schema/Server/CLI/测试/Git/账本写者；Codex只读核验与终审，无另一写者。完整工单目标保留，不把测试切片重新定义为完成。

新增 `ordessa-agent nodes prepare --file preparation.json`，完整固定requestId/profileRef/context/options，原key同时wire ID，沿既有agents.nodes.prepare/AgentAssembly/Profile→Unit→Node/原store/authority/claim/Usage，不生成本地计划或品牌协议。core schema公布既有operation_view四字段与原status枚举，v2镜像生成；v1/provider镜像未变，旧v2digest不匹配拒绝无fallback。Server仅用safe_json投影原操作。CLI发前拒私有命令/路径/凭据、类型/shape/外环境，published复用Node观察且核Profile/原context/options/operation/revision；runtimeVerified=false。reserved/running/unknown或作用后坏/丢回执6不自动重发，不安全回执不推导operationRef。没有公开preparation query/request-key lookup，README/Skill明确缺口，不替换为配置query/DB旁路。

完整命令与范围：[prepare-cli.md](evidence/agent-unit-model/prepare-cli.md)。初新CLI24P exit0、12.70s；补同键变context/options冲突、port缺席与fresh安装实际prepare/replay后组合57P exit0、36.62s；补实际reserved及四状态null DTO后CLI/契约/原assembly71P exit0、17.00s，新prepare32项。真实自有Uvicorn v2目录服务创建真实Profile后因authority ports缺席拒prepare4，Profile不变：v2组3P/2deselected exit0、3.09s，新1项。公共CLI/契约/发行全组合222P exit0、103.58s；全部产品integration297P exit0、11.84s。fresh wheel/venv仅本产品no-index/no-deps安装、独立CLI对原Core/SQLite/issuer受控HTTP发布＋原key重放，6请求、provider唯一prepare/start。受控owner是C，不当真实native Harness P/M。

全Core269P/3F exit1、7.72s、0skip，仍既有kernel_direction三红/具体SQLite测试导入来源，未删断言/skip/移走失败。worker/sidecar/ACP closure/Claude资源ABSENT继续。三Skill结构、五工单strict、mirror、diff-check各exit0仅资料门；无pytest新失败，所有测试terminal。只读审阅无源码阻断，指出use Skill旧禁止prepare句，已限定缺任务输入并指向管理Skill。没有真实Agent指令行为评估。

默认目录部署依然不提供production准备权限；production材料/SecretRef/capture/receipt/effect/Session owner、三家native装配、完整生命周期/冷恢复、旧Model/Server迁移、准备公开恢复、connect/applyProfile/stop/release/tasks/results及全纵向仍PARTIAL；M0，不报AU004_DONE。未第三方安装更新/登录/模型/用户DB/凭据/全局配置/用户服务操作/push/主树合并，成本unknown。显式纳入本轮新增及已核对源码/文档/证据检查点后继续。

### 2026-10-05 AU002 精确装配引用／AU004 原准备请求核实／AU005 新包（PARTIAL）

前置deb39c19751621d2dc705f807a394a6185d56a46、clean；上一源码/验证提交属于progress。本轮live agents全completed，主会话唯一共享Core/schema/Server/CLI/测试/Git/账本写者；Codex只读接口/安全审阅无源码阻断，保留三家成果、无另一写者。

公开 `agents.nodes.queryPreparation(requestId)` 直接绑定原assembly.query，catalog.request_key限当前Environment/认证principal；body不能传realm。核心schema发布精确operation/None wrapper，effectful=true（可记原Step），v2镜像生成；v1/provider不变。CLI `nodes query-preparation ORIGINAL_REQUEST_ID` 原key同时wire ID；丢published回执可找回原operationRef/Node，无再次dispatch。原unknown claim核实可变running/concluded但不start缺step、不publish，不自动prepare；未published仍6。缺席4不证明此前无效果或授换键；配置request-key lookup仍缺，不能误用本入口替代。

开放前SQLite新6反例先0P/6F exit1、0.65s，证实assembly provider observation/Usage target/query原Unit混认bool/float。复用nodes._same_reference/safe_json修所有原引用比较，保持唯一授权/claim/Usage/CAS/生命周期；作用后坏证据保unknown，不声称零效果。修复后assembly＋原prepare61P exit0、17.15s；query定向14P/33deselected exit0、10.61s（名称不含query的丢published回执另在完整组合）。完整定向首81P/1F exit1、36.88s仅错误码预期误猜，保留既有PRECONDITION_CONFLICT并补3realm/schema门后85P exit0、37.44s。新增22CLI/契约＋6assembly，原发行2加强，不累计快照。

完整命令与证据：[preparation-query.md](evidence/agent-unit-model/preparation-query.md)。全产品＋所有AU证据首收集exit2/2errors0.57s，测试closure未含独立Codex源码，不算绿；显式本树三家＋运输PYTHONPATH、无安装/skip，实际999P exit0、177.80s。full Core269P/3F exit1、7.08s、0skip，仍既有kernel_direction三红/SQLite测试导入，未删除断言/移走失败；worker/sidecar/ACP closure/Claude资源ABSENT继续。管理Skill结构/五工单strict/mirror/diff-check仅资料门，测试全部terminal。

README/ACCEPTANCE/管理Skill同步原请求核实及不自动继续；配置未知无operationRef恢复缺口单列。fresh wheel/venv独立CLI真实Core/SQLite/issuer＋受控HTTP prepare/replay/query9请求、provider唯一prepare/start。新ignored bundle生成exit0，实际安装＋隔离既有Server exercise27记录exit0/M0/cleaned，回执evidence/install-use-preparation-query-deb39c.json；wheel SHA505dd96e8ea114961566cca60ab4094acedbe83be58145b1abac4070f5edf057。实际entrypoint缺席/回执hash/27条再核验exit0，不覆盖旧包/旧回执，不纳入binary。安装exercise仍Server/catalog范围，新query正例C来自发行测试，不冒native P/M。

production授权/材料/SecretRef/capture/receipt/effect/Session owner、三家native装配、完整生命周期/原生冷恢复、旧Model/Server迁移、connect/applyProfile/stop/release/tasks/results与全纵向仍PARTIAL。M0，无第三方安装更新/登录/用户DB/凭据/全局配置/用户服务操作/push/主树合并，费用unknown。核对并显式纳入本轮全部改动/新材料检查点后继续，不终结goal。

### 2026-10-05 AU003 Claude ACP附件能力单一所有权迁移（PARTIAL）

前置b228c0774e；保留当前未提交成果，live agents皆completed、主会话唯一写者；Claude只读复审，无测试/Git写权。旧附件utility源码字节不变迁入独立包，原六测试＋独立旧catalogue断言全部保留，旧导出移除无shim，Continuation不动。纯ACP能力不挂SDK provider默认method，不声称生产附件接线。

完整命令、反例及限制见[evidence/agent-unit-model/claude-acp-attachments.md](evidence/agent-unit-model/claude-acp-attachments.md)，字节/AST收据同目录json。新增六拒绝反例＋fresh四自有wheel安装闭包＋三个边界门；初迁移6P0.10s，扩充12P/1F4.65s（安装继承源码env缺包），旧metadata/边界/Coreidentity87P/1F1.47s（新门误纳原核心集成测试），皆exit1如实保留。安装清理env/cwd、门限定源码与迁移附件测试，既有生命周期集成未改/未skip。最终组合101P exit0、6.15s；独立Claude全包162P exit0、12.69s含原集成覆盖，无缺资源冒绿。新增快照不累加。

仅C/自有安装进程，无native P/M，M0。旧model/Server装配、production owner与全生命周期/tasks/results/三家纵向仍PARTIAL，Core继承三红与ABSENT沿前账本、本轮未全回归。未授权操作无；成本unknown。新材料显式纳入检查点后继续，不标DONE。

附件检查点 d7b99ac3c1 后继续只读核对旧Model/Server装配。源码证实products/server仍激活旧三家配置plugin/backend/live_service；Claude旧compiler保留endpoint/credential/restart-resume同Session语义，独立SDK owner未承接。Codex代理独立确认消费者及三家缺口；盘点写入[evidence/agent-unit-model/model-server-migration-inventory.md](evidence/agent-unit-model/model-server-migration-inventory.md)。这项依赖证据限制下一清理范围，不当生产测试/验收，不删除成熟旧语义或复活旧入口。整体goal继续active，所有本轮测试terminal。

### 2026-10-05 AU003 旧native_runtime三家选择早拒（PARTIAL）

前置f08a635c85 clean、agents completed；主会话唯一共享源码/测试/Git/账本写者，Codex只读攻击和终审无阻断。已核对新增文件与迁移合同；保留三家源码/旧模型语义/原测试，未并行共享写入。产品native_runtime对primary/profile/additional/implicitPi和claude别名在旧import/assembly/state/data前复用GuaranteeUnavailableError拒，不复活compat、不自动换原生通道。其他家族原入口可达但不称完整可用。

完整命令与计数见[evidence/agent-unit-model/retired-native-assembly.md](evidence/agent-unit-model/retired-native-assembly.md)。实现前7P/10F exit1 0.35s；初36P exit0 0.38s；增强import门及原模型语义105P exit0 0.44s，新23项/旧82项。旧ServerPi正向原测试实跑0P/1F exit1 0.11s，因旧统一入口被拒，保留断言未skip/删/改绿；后续需独立消费迁移。产品integration297P exit0 12.21s，测试串行terminal。只读终审确认范围与无参数旁路，七家正控仅原assembly reach，不能冒运行成功。

sidecar与旧C2批量注册仍有路径，独立生产模型/凭据/恢复owner、native全生命周期/tasks/results未完成；全Server/Core本轮未跑，继承三红/ABSENT保持。C-only/M0，无任何未授权操作，费用unknown。依本树AGENTS规则10，另在docs/known-issues.md窄幅登记本次明确旧Server预期冲突；这是必需失败登记，不扩张实现范围或修改工单合同。显式检查点后继续goal，不标AU003_DONE。

### 2026-10-05 AU003 独立三家Server装配／AU002公开注册点（PARTIAL）

前置478643a80a clean；agents completed，主会话唯一共享源码/测试/Git/账本写者，Codex只读接缝与终审。新增三家可选Server wrappers＋server extra，原owner/provider IDs不改；从现有core.binding取唯一EnvironmentId，固定AgentContributionSet经宿主stage/commit，不另Registry/存储/授权/nativeIO。AgentToolsDeployment默认零plugins，显式tuple/v2可选；公共点原exclusive阻第二家，主会话将Server pacthold.contributions设multi-owner、冲突留原CoreRegistry。未并行共享写，必要公共宿主接缝属于AU002串行补齐，不改工单语义。

完整命令/资源/边界见[evidence/agent-unit-model/independent-server-providers.md](evidence/agent-unit-model/independent-server-providers.md)。初3P/4F exit1 0.34s，修point/负例调用位置后6P/1F exit1 0.25s，补隔离/回滚12P/1F exit1 5.04s。真实冷重开generation复用1，保留失败，不改断言假绿。当前暂时在既有root store takeover前typed拒非空provider选择，不冒成功重开；corebinding/源码门26P/1F exit1 0.53s；全产品integration＋fresh无ServerAPI Claude wheel311P/1F exit1 16.87s、0skip，新14原297发行1不累计快照。原fullcold目标断言保留，known-issues登记。

冷持久allocation/fresh seed无既有合同，已写activation-generation-proposal.md并向用户请求初始化边界裁定，未自创counter或修改用户DB。此临时guard只约束本部署，不修其他composition冷代问题。只读终审无新增源码阻断，首轮三家Registry发布是C原型而非可重启生产服务；native P/M、完整owner/lifecycle/旧model/sidecar/tasks仍PARTIAL，M0、资源ABSENT继续。无未授权操作、费用unknown；所有测试terminal，显式纳入新材料和改动检查点，goal继续，不标DONE。

### 2026-10-05 AU003 六包隔离发行／AU005 已安装CLI真实发现（PARTIAL）

前置36de74fd3277a7762644959173066ded2831f55d，保留已有未提交四文件/两回执；上一状态问答no progress，本轮实际修复、复跑、记账。live agents确认无另一写者，主会话唯一源码/测试/Git/账本写者，Skill reviewer只读终审，Codex只读下一旧Model入口。完整命令、失败修正与层级见[evidence/agent-unit-model/installed-provider-discovery.md](evidence/agent-unit-model/installed-provider-discovery.md)。

新增fresh客户端wheel/venv独立entrypoint→实际自有Uvicorn/Server v2三家发现、describe、身份、坏Bearer、foreign和离线反例；原默认Profile helper保留。新安装调用timeout60，不引入品牌客户端。六自有wheel脚本显式新回执/currentHEAD/dirty/hashes，失败和timeout也写回执，未知exit不报0、已有证据拒绝不覆盖。正常包装复跑曾内嵌probe IndentationError：10命令第10exit1、外层exit1、failed/cleaned回执保留；修dedent后新verified回执12命令全exit0/六hash/cleaned。重复预期exit1，原SHA字节不变。broken fixture原只证坏TOML，现真换行且要求缺backend错误；故障门末端3P exit0 0.44s，HTTP末端6P exit0 12.81s。

初CLI预期错误1F4.36s、组合5P1F12.87s，修后6P12.89s；跨包pytest同名模块collection exit2/3errors0.47s，不skip/删cache，串行独立包166P2.12s/213P3.18s/162P12.70s各exit0。全product integration311P1F exit1 16.98s，仍保留fullcold严格目标；Core/Server全套本轮未跑，继承红不抹去。新增四测试不累计快照。只读终审两个脚本问题修正后无切片阻断，审阅不当测试。

证据是自有发行/controlled Registry C＋实际隔离Server/CLI进程；nativeHarnessP/M无，M0、productReady=false/coldRecoveryVerified=false。冷代次待裁定、production owner/lifecycle/旧Model/sidecar/tasks/results/full纵向及资源ABSENT继续。无第三方安装更新/登录/用户DB/凭据/全局配置/用户服务操作/push/主树合并，费用unknown。所有测试句柄terminal，核对资料门后显式纳入本轮检查点继续goal，不标DONE。

### 2026-10-05 AU003 旧三家C2批量发布入口退役（PARTIAL）

前置b5f17678c9 clean，主会话唯一共享源码/测试/Git/账本写者，Codex只读盘点/终审。旧ModelProviderAdaptersPlugin仅三家batch，现build读取context/发布/IO前既有public GuaranteeUnavailableError拒，descriptor/稳定IDs不改，顶层三brand imports移除；pure bridge/brand compiler及原positive测试保留，不改独立新三家或用户数据。

完整命令与限制见[evidence/agent-unit-model/retired-model-batch.md](evidence/agent-unit-model/retired-model-batch.md)。新直接门guard前1F exit1 0.15s；初测试descriptor误属性2P1F exit1 0.09s，修已有id；组合86P1F exit1 0.85s原pure导入门缺公开environment-api拒绝类型，窄加该契约根且保留AST/IO/纯度全部断言，87P exit0 0.72s；加原native入口末端110P exit0 0.77s。新4项，不累计快照。实际原batch正例＋live_runtime全部exit1/2P1F27E 2.01s，原setup调用退役入口失败，未删除/skip/改绿；本树AGENTS规则10要求窄幅known-issues登记（不扩张实现域）。ModelProvider E2/Server C4/probes可见消费者本轮未跑，不报绿。全部句柄terminal。

只读终审确认未宽拒七家、无IO或注册旁路；这只是旧batch入口封闭，pure adapter/live_service/sidecar仍可达，不称全旧路退役。sidecar原单次部署解析在server-compat域，不在AU003写域；产品重复解析有TOCTOU，记录共享接缝缺口，不复制parser或外部编排。生产权限/材料/凭据/owner/coldgeneration/全生命周期/tasks/results/A18、三家native P/M仍PARTIAL，M0，资源ABSENT与继承Core红继续。无未经授权操作，成本unknown；资料门后显式检查点，goal继续。

### 2026-10-05 AU003 Claude成熟纯模型配置能力迁移（PARTIAL）

前置3c83819e23ce36beda9c34be79d56b8c2e4bef88 clean，live agents无另一写者，主会话唯一共享源码/测试/Git/账本作者；Claude/Codex只读盘点/双审/终审，无测试写权。上一轮两检查点属于progress，本轮迁正向能力，不以封旧入口代替新能力。完整命令/来源/初红和修复见[evidence/agent-unit-model/claude-model-compilation.md](evidence/agent-unit-model/claude-model-compilation.md)，初AST/finalsha分开收据同目录claude-model-migration-source.json。

旧Claude purecompiler→独立acp_model_configuration/facts，旧文件物理删除无shim，bridge/原测试消费独立owner。原全部DTO class AST原样迁已有harness-api.model_compilation，generic parser原体迁入；纯API仅stdlib/no authority/register/Store。shared model/common Claude pins导入独立facts，旧native.py/native_materialization事实迁移仍未完。ACP0.81.2范围不冒SDK0.2.163支持，默认provider methods未扩大。两侧pyproject明确own dependencies，fresh五包发行补API/pipcheck、无ServerAPI/SDK/大Harness/产品，实际正向编译并拒SDK版本轴。

正向model-only、endpoint与model双intent、credential-only引用与同Session restart-resume保留；缺typed flags/ref/endpoint/target拒，缺model/session保持unknown。复用SDK原native_identity（AST相同）拒default/control/非法UTF8。初pure/API76P4F37subtests exit1 .30s门仍认旧owner/禁共享DTO；窄迁门后80P37 exit0 .35s；新13原漏洞11F2P exit1 .18s，修后93P37 exit0 .25s；source/brand/fresh组合20P1F exit1 6.54s仅原batch发布正例。中间Claude175P exit0 13.47s；扩29边界14F15P exit1 .23s，修后SDK/pure/API142P37 exit0 .40s。末端加target三门全Claude194P exit0 13.47s（原162＋新32），最终定向含ownership/故障159P37 exit0 .94s；新增ownership1，快照不累加。全product integration311P1F exit1 16.84s仍strict冷代次目标；Core/全Server/旧C4本轮未跑，继承红/27setup债保持。

七own wheel初与final两次实际安装各13命令全部exit0，七摘要/temporaryEnvironmentRemoved=true/M0/productReady=false，final回执au003-claude-model-install-final-3c8381.json为末端源码，不覆盖先前回执。两审确认无第二核心/旧注册恢复，末端源码SHA/原SDK函数AST实核exit0。C＋自有安装进程，不冒nativeHarnessP/M；verify仅model/sameSession，完整endpoint/credential/restoration确认与production owner未接线，coldgeneration仍待裁定，其他三家/旧Model/sidecar/full lifecycle/tasks/results/Skill实用/A18均PARTIAL，ABSENT不算绿。

无第三方安装更新/登录/用户DB/凭据/全局配置/用户服务操作/push/主树合并，成本unknown；全部句柄terminal。核对新增文件/strict/diff门后显式stage迁移切片继续goal，不标DONE。

### 2026-10-05 AU003 Codex成熟纯模型配置迁移（PARTIAL）

前置6af84df2a426d2bc39d3f91f7db80adfa33ed845，承接上一上下文未提交成果逐项保留并核对；live agents无共享写者。主会话唯一源码/测试/Git/账本写者，Codex/Claude只读双审，无测试写权。上一状态答复no progress，本轮修复、实际复跑、发行与记账progress。完整命令与反例见[evidence/agent-unit-model/codex-model-compilation.md](evidence/agent-unit-model/codex-model-compilation.md)，初AST/finalSHA分开收据codex-model-migration-source.json。

旧compiler物理移出无shim，公共既有DTO复用；common/native/remote/materialization改消费独立facts，旧error表面/golden保留。保正向model/provider/endpoint/ref/effort/restart-resume；修same-provider变更漏项、缺previous观察、typed身份/ref/flags、TOML点/引号/控制字符。初新32为3P29F exit1，missing-before32P2F exit1；加强SecretRef正控消除原conditional skip，组合145P37subtests exit0。全Codex初env缺transport collection2E exit2，补实际source201P exit0。双审发现DEL，新反例34P2F exit1 .18s；修后末端全203P exit0 7.57s，最终旧pure/API/family/ownership147P37subtests exit0 .62s、0skip。新增36model/1发行/1ownership，不累计快照。

七own wheel final安装13命令全exit0、七hash、pipcheck/cleaned/M0/productReady=false，回执au003-codex-model-install-final-6af84d.json不覆盖旧证据。全产品integration311P1F exit1 16.98s，仍strict冷代次目标、断言不改；Core/全Server/旧C2本轮未跑，继承红和旧consumer债继续。两只读终审无切片阻断，但verify仅thread/model/provider，非完整endpoint/credential/effort应用；None/True resume期望是未验证计划，无真实同thread恢复证据。ACP历史1.1.14不冒app-server0.157.1支持，provider methods不扩。

生产授权/材料/凭据/owner/coldgeneration/lifecycle/tasks/results/A18和native P/M仍PARTIAL；资源ABSENT、费用unknown，无第三方安装更新/登录/用户DB/全局配置/用户服务操作/push/主树合并。下一Pi纯迁移只读盘点已识别漏model/retry覆盖问题，先补反例再迁。检查点后继续goal，不标DONE。

Codex迁移检查点8e49d0413e6119e8a05aad59aabbdd5f74f9244a clean后继续Pi前置。Claude只读盘点确认existing公共DTO可复用、原独立Pi生产面仅model/thinking；主会话实跑旧pure受控反例exit1、0P3F（非pytest）：retry-only丢models、restart漏desired model、缺model/session仍match。新JSON保留原输入结果，可复跑probe与迁移盘点显式纳入材料检查点。下一迁compiler/facts并加typed/重复model反例，生产完整owner/applied/native P/M仍PARTIAL；未操作用户服务或模型。见[evidence/agent-unit-model/pi-model-migration-inventory.md](evidence/agent-unit-model/pi-model-migration-inventory.md)。

### 2026-10-05 AU003 Pi成熟纯模型配置迁移（PARTIAL）

前置65e409534505d5701d87a84d58c6138671bdd5d9 clean，主会话独占共享源码/测试/Git/账本，Codex/Claude只读双审无写测试权；上一检查点属progress。旧pure compiler物理迁独立Pi，无shim/旧import；DTO复用现有API，facts归独立owner，shared common/native/materialization/bridge复用，普通renderer原体/异常表面不变。独立Pi补API、旧Harness补ownPi dependency；未扩provider默认methods/schema。

原模型/预算siblings/metadata/SecretRef/retry/settings target/sameSession正向计划保留，修restart漏model、retry/credential-only丢models、None误match。新增typed/change flags/missing observation/direct params/重复modelid/endpoint sample反例；二审实测apiKey/headers复制秘密问题，仅保$ENV_NAME、非空headers拒，拒绝消息无内容，非通用脱敏器。详细命令/范围见[evidence/agent-unit-model/pi-model-compilation.md](evidence/agent-unit-model/pi-model-compilation.md)，初AST/finalSHA receipt分开。

初30为1P29F exit1 .21s；补43为39P4F .15s；扩48为40P8F .16s。全修组合159P1F37subtests exit1 .56s，仅原host-issued缺endpoint抢先拒，补fixture明确endpoint保原断言后160P37subtests exit0 .63s。全Pi初262P exit0 8.67s，增强fresh预算/retry正控后末端262P exit0 8.58s；新增48pure/1发行/1ownership不累计。原materialization/family/ownership57P exit0 .46s；其输出ABSENT不冒资源绿。原三反例probe新ownerexit0，旧JSON不覆盖。

七own wheels final13命令全0、pipcheck/hashes/cleaned/M0/productReady=false，au003-pi-model-install-final-65e409.json；finalSHA实核。产品integration311P1F exit1 16.40s仍strict冷代次目标，未改断言。末端Pi启动前未先收集product终态，现两个句柄皆terminal，后续严格先收集再发下一测试。Core/全Server/旧C2未跑，继承红/consumer债保持。

两审无切片阻断；verify仅model/sameSession，routing/credential/budget/retry真实applied与恢复仍缺owner/capture/receipt/授权/material，native P/M无。生产消费者/冷代次/lifecycle/tasks/results/Skill/A18与baseline全Server安装待整合；M0、费用unknown、ABSENT不算绿，无第三方安装更新/登录/用户DB/全局配置/用户服务/push/主树合并。检查点继续goal，不标DONE。

为消除末端调用未先收集product句柄的串行证据不确定，最终明确先product终态再Pi：311P1F exit1 16.85s，随后262P exit0 8.48s，所有句柄terminal。最终采此串行组，旧运行记录不覆盖、不累计；源代码未再改。strict五工单/diff资料门exit0，仅资料验证。全部新增源码/测试/安装与反例收据已读核，显式stage本切片检查点。

Pi检查点66936bcedf后继续生产接线只读盘点（非停工/非DONE）：主会话核对Server旧C4/sidecar与独立provider ports。关键依赖是实际UnitRecords仍在旧Harness application，要求原OperationJournal及显式scope/native evidence/verifier/epoch，生产deployment尚无构造；独立测试Records不是真实持久owner。下一先核并复用这条owner链，再作显式Codex新Server装配/现defaults管理与读回，不能复制journal或用pure compiler承诺完整applied。详细实核与下一步骤见[evidence/agent-unit-model/server-production-owner-inventory.md](evidence/agent-unit-model/server-production-owner-inventory.md)，其他资源/cold语义仍按原PARTIAL，未触用户数据/服务。

### 2026-10-05 AU003 原journal/UnitRecords可分发owner提取（PARTIAL）

前置b2e4a1ab368de15e25d06cc467612012d7cb29f2 clean；上一Pi/盘点progress。主会话独占共享源码/测试/Git/账本，Codex/Claude只读双审无写测试权。原两实现合计1453行按bytes迁独立records library，无新core/registry/plugin/daemon/DB；原表/codec/事务/ticket/unknown/legacy guard全不改，最终HEAD旧bytes与新SHA再核相等。scope内消费者同class，旧二文件删除无shim；原application根reexport仍同class保七家服务。

依据与完整命令见[evidence/agent-unit-model/records-owner-migration.md](evidence/agent-unit-model/records-owner-migration.md)，原文件receipt记录两SHA。初原组合165P2F exit1 2.56s，窄迁新owner/已有stdlibhashlib门后含source181P exit0 3.05s；发行/输入关联/首publication/Codex/隔离76P exit0 13.88s，Claude全194P exit0 13.50s；新增发行1/ownership1，不累计。fresh records三own wheels净环境验证import无SQLiteIO、无monolith/Server/Pacthold/品牌、原journalunknown/replay/busy/reopen/query及缺authority拒，非native P/M。

八own wheel final14命令全0、hash/pipcheck/cleaned/M0/productReady=false，au003-records-install-final-b2e4a1.json不覆盖旧证据。产品integration311P1F exit1 16.69s仍strict coldgeneration，原断言不动。Profile六原测试outside scope实跑2P4F exit1 .89s，旧import导致effect前失败；新迁移债不是继承，原断言/目标未改。一行公开records consumer patch已准备，因AU003“只处理write_paths”且Profile测试不在任何单写域，异步范围确认pending，不能据等待elapsed授权。缺口known-issues登记，不复活shim。所有测试串行terminal。

生产真实owner factory/原InvocationIssuer/authority-current-state/scope/epoch/native evidence/lease/receipt和独立projection仍待接；独立可分发不等于已装配/ready。旧live_service每次新journal待同owner注入，cold提案待裁定。Core/全Server/旧C2本轮未跑，继承红/consumer债/ABSENT保留；所有AU/lifecycle/tasks/results/Skill/A18继续PARTIAL。M0、费用unknown，无第三方安装更新/登录/用户数据/全局配置/用户服务/push/主树合并。新增文件/回执/依赖/consumer已核，显式stage检查点后继续。

records检查点f6ba4662a5已提交。首次cached资料门发现新增patch中的空白context行（此前working diff未覆盖untracked），HEAD parent复核exit2；原journal源码/测试结果不受影响。现去掉patch空白context并保一行import变更，git apply --check仅校验不触Profile目标；补资料修正检查点，实际diff门以修正后为准，不能将初缓存门报绿。

### 2026-10-05 AU001 公开 issuer／AU002 关闭票据（PARTIAL）

前置61bf9e7f5e clean，live agents已完成且无另一写者；上一状态问答no progress，本轮补生产接线所需原公开类型和生命周期。主会话唯一共享源码/测试/Git/账本写者，Codex只读审。五现有issuer/grant/authority/state类公开同identity；原issuer.close撤销原票据、不改durable claim，不是native stop/IO屏障。生产owner尚未装配，不能称ready。

详细命令、初红和限制见[evidence/agent-unit-model/public-issuer-lifecycle.md](evidence/agent-unit-model/public-issuer-lifecycle.md)。初公开81P exit0 .58s；关闭初86P .71s、state重入87P .70s各exit0。审阅发现最后grant序列化可重入close，实际反例6P1F exit1 .20s；在原锁登记前重核，最终同组88P exit0 .66s，新增14项不累计快照。真实原SQLite claim保留及effect/query慢state并发关闭反例，不冒native进程。最终product integration311P1F exit1 16.97s，仍原strict冷代次失败不改断言，初组17.23s保留。所有测试串行terminal，五单strict资料exit0不当产品验收。

冷代次与scope外Profile import补丁待答复；production owner/authority/current-state/scope/native evidence/lease/receipt、旧consumer、生命周期/tasks/results/Skill/A18及资源ABSENT继续。Core/全Server/品牌发行本轮未跑，原红保留，M0/成本unknown。未做未经授权操作。核对本轮源码/新增证据后显式阶段提交，goal继续active。

### 2026-10-06 用户裁定落地：持久激活代次＋显式生产属主接线（PARTIAL）

前置344d58525431、开工clean（用户新增.env未跟踪且绝不入库）；上一状态问答属历史。用户已裁定：代数按activation-generation-proposal.md实现、Profile一行import补丁可改（已应用并复验6P）、真实模型/Harness调用授权（本轮M0未调用）。主会话唯一共享源码/测试/Git/账本写者；architecture-reviewer第1次架构评审（只读，多条修正采纳，确定性请求键一处保留分歧并记录），test-author仅写指定反例文件（13项，主会话复跑核实）。

修改：新增pacthold/core/activation_generation.py（高水位CAS＋birth事务fresh依据＋journal归属证据；门面链AST规则只许core/environment故落core）；environment.py三处（durable模式参数、_commit_activation_stage单次原子CAS分配/失败耗代无残留、instantiate代次默认1旁路修复）；products/agent-tools/deployment/composition.py（成对policy_factory/owner_ports_factory仅v2、依据化冷重开守卫、birth写依据、durable恒开、close链修复：revoke→detach重试→成功才放写锁且错误保留、并发close store只关一次、回调重入close被阻）；deployment/owner_ports.py（唯一records导入点＋OwnerPorts/AssembledOwner单一装配点＋单verifier/原store身份断言＋canonical journal绑定证据＋符号链接守卫）；test_independent_server_providers.py旧"一律拒"正例改夹具为真正无依据历史根（断言原文保留）。新反例test_activation_generation.py 13项＋test_owner_wiring.py 14项。详见[evidence/agent-unit-model/activation-generation-owner-wiring.md](evidence/agent-unit-model/activation-generation-owner-wiring.md)。

验证（专属Python串行、句柄terminal）：产品integration **312P/0F exit0、16.6s**（原311P/1F的唯一冷重开失败由持久代数真正修复，严格断言未删未改）；代数反例13P/0F exit0；属主接线反例14P/0F exit0；核心全量269P/3F exit1、7.7s仍同三个已登记kernel_direction继承ID无新增（中途环境模块导入触发门面链AST 4F，移core后恢复）；原journal组合107P/0F exit0；Profile六项6P/0F exit0。均C（真实临时SQLite/journal＋受控端口），三家provider消费生产owner的纵向接线、真实authority/目录/租约/回执、配置事实确认、生命周期/任务/结果仍缺；P无原生进程、M0（真实调用已授权但本轮未需要）。

初跑失败账均测试侧：门面链AST（模块移core即恢复基线）、仓库根路径差两层、缺records PYTHONPATH、symlink子例误用异root、混用反例误用第二journal对象（改同对象pin＋重复接线拒，装配层顺带加already-assembled拒绝）、契约类缺frozen、bind误用带版本surface id；断言一律未放宽、无skip、无mock冒绿。

架构评审累计1/3次；子代理：architecture-reviewer×1、test-author×1，费用精确值unknown。工单strict与diff-check随后核验；无第三方安装更新、无用户DB/凭据/全局配置/服务操作、无push/主树合并。显式stage本轮文件形成检查点后继续三家生产接线与后续工单，不标任何完成门。

### 2026-10-06 属主→provider 管线合同冻结与三家家族接线（PARTIAL）

前置3f40afad33。architecture-reviewer第2次咨询（管线合同/旧消费者迁移边界/生命周期归属/P-M分层，只读）；裁决：factory扩两参收**不含issuer的provider_view**（高优先：插件永不获签发权）、records补免调用属主读（高优先：解P级投影阻塞）、终止方法族先冻结再实现、acquireAccess补requestId。评审对旧消费者的反直觉裁定采纳：不整体迁移，endpoint/credential/restart-resume/附件四类语义由新owner承接、代码按家族typed退役，sidecar负退出条件"无第二解析者"import边界锁死。

实现：owner_ports.py加OwnerProviderView＋provider_view；UnitRecords加owner_read_unit/owner_read_session/owner_read_unit_confirmation（免invocation，原授权读面不变）；schema.py给acquireAccess加requestId并effectful统一由requestId驱动；客户端镜像generate_schema.py --write再生成并复验（仅schema-management.json变化）。接口冻结后并行放行三个slice-worker家族切片（各写各包、均声明写权释放）：三家server_plugin传view＋同一性断言＋反例（codex210P/0F、pi271P/0F含构造期拒绝新旧双路混用、claude200P/0F含三参数化混用反例），原有断言零删除零放宽。详见[evidence/agent-unit-model/provider-owner-pipeline.md](evidence/agent-unit-model/provider-owner-pipeline.md)。

集成复跑（主会话串行、句柄terminal）：产品integration **312P/0F exit0**；证据反例28P/0F（属主接线15＋代数13）；三家210/271/200P/0F逐包核实；核心269P/3F同三个已登记继承ID无新增；原journal组合107P/0F。集成初红均夹具侧：三处单参factory/lambda与一处cls默认参被owner_view顶位（两参化恢复）、客户端镜像过期致真实服务CLI拒schema（再生成后恢复）；断言未放宽、无skip。

C为真实临时SQLite/journal＋家族Python实现与受控端口；P无原生进程、M0（授权已给，本轮未需要）。未验证：三家纵向端到端（下一切片codex C→P）、projection/channel_factory/lease_port生产装配、records终止方法族＋AgentLifecycle、acquireAccess wire绑定、逐家退役闸、真实进程/模型。家族申报两次只读git status越界（无树变更），如实入账。架构评审累计2/3次；子代理slice-worker×3；无第三方安装/用户数据/服务/push/主树合并，费用unknown。检查点后继续纵向切片与生命周期，不标完成门。

### 2026-10-06 统一终止方法族冻结＋safety-reviewer 加固（PARTIAL）

前置b1d2afbf59。主会话唯一共享写者；safety-reviewer（只读）审终止面与免调用属主读，两项"必须修"与四项"建议修"全落地；codex真实适配器切片并行进行中另记。records新增harness_unit_terminations单一终止账本（stop/release，begin/record一对＋TerminationRecordTicket＋unknown保占用与活票据）＋reconcile_termination冷恢复＋owner_read_termination投影（projection标记）。

安全修复：confirmed证据改经NativeTerminationEvidencePort验证、入库端口返回provenance refs（调用者字符串永不作证明）；record事务内按票据回绑identity并写前校验（消除"拒后已落库"未知窗口与篡改面）；读侧补state/revision/identity/outcome/JSON异常全套复核；epoch检查入事务；evidence单拷贝；correlation撞车typed拒。反例：伪造证据拒且保opening、端口坏形状拒、跨重启冷恢复与异step拒、四类损坏拒、单发/身份/票据伪造保持。详见[evidence/agent-unit-model/termination-face-freeze.md](evidence/agent-unit-model/termination-face-freeze.md)。

验证（串行、terminal）：test_unit_records.py **38P/0F exit0**（原30＋新8）；test_owner_wiring.py 15P/0F（补两坏形状例）；records导出import核验exit0。C真实临时SQLite＋受控端口，P/M无。登记设计边界：owner读与授权读同类型（provider即属主）；record_unit/record_session同型事务外epoch为既有模式未扩面。失败账一处测试侧mappingproxy序列化已修，断言未放宽、无skip。

无用户数据/服务/push/主树合并；M0费用unknown。检查点后接codex集成与AgentLifecycle（第3次架构咨询），不标完成门。

### 2026-10-06 codex 真实进程 P 级＋store 受控释放接缝（PARTIAL）

前置344ba9efab。codex slice-worker持家族写权完成真实三适配器（runtime_channel：绝对路径codex app-server stdio、私根布局realpath校验、HOME/XDG/凭据形键隔离＋/proc核证、managed stdin写屏障、显式收回；projection：只经owner_read_*免调用读；lease：opaque grant＋bind绑原writer lease＋revoke fence）与17项P级真实进程测试（零模型显式断言），全包227P/0F主会话复核；写权已释放。真实证据：0.159.0实证兼容initialize/thread往返/错误保真/丢回执只读恢复（unknown保占、不重发、recover只读回收迟到回执）；thread/list省略params帧差异如实登记；turn/config/stop边缘未测不声明；close后ps无残留。详见[evidence/agent-unit-model/codex-p-process-and-release-seam.md](evidence/agent-unit-model/codex-p-process-and-release-seam.md)。

architecture-reviewer第3次咨询（累计3/3达标）裁定release走新增受控释放接缝并关闭unknown→released潜伏缺口、新增窄观察端口、apply_profile签名与wire门控清单。主会话落地store接缝：record_operation_step(release_holder=...)＋_write_usages释放分支（仅active可释放、holder精确匹配、unknown结果下释放拒、终态幂等、历史不可改写）＋read_usages读接缝；test_usage_release.py 6反例（含缺口回归钉）。

验证（串行、terminal）：codex 227P/0F（210 C＋17 P真实进程）；environment-api+persistence **76P/0F**（原70＋6）；产品integration **312P/0F**；records组合115P/0F；核心269P/3F同三个已登记继承ID。失败账均夹具侧（revision硬编码、UsageMutation payload Mapping、operation_ref撞身份、导入位置），断言未放宽无skip。

C/P分账如实：P仅codex一家真实进程（零模型）；pi/claude真实进程、AgentLifecycle、wire生命周期绑定、三家消费终止族、旧消费者退役、任务/结果、发行与七家扩展继续。M0（授权已有未调用）；无凭据/全局配置/服务/push/主树合并，费用unknown。检查点后按评审3裁定实现AgentLifecycle，不标完成门。

### 2026-10-06 AgentLifecycle 核心协调器（stop/release/recover）检查点（PARTIAL）

前置eb354763d0。主会话按architecture-reviewer第3次裁定实现pacthold/agents/lifecycle.py：agent-stop/agent-release/agent-recovery三kind各一单步；stop/release为cleanup调用（targetRef=nodeRef、directoryBindingRef取Node持久绑定）、recover普通调用；同请求重放只读、claimed永不重发；capabilities按issuer同store钉法；public.py的AgentServices增lifecycle字段＋compose-once守卫（lifecycle_observation_port一次性注入）。核验栈：issue→provider→verified_consumption→LifecycleObservation四元组＋owner出处→终止投影（version/action/confirmed/identity.unitRef+inputDigest）或recover的A13字段比对（unit/nativeSessionRefs集合/configurationTarget/provider）→同事务concluded（release附受控释放变更）；任一失败unknown零释放。release预检恰为Node active publication Usages，不符派发前拒。

反例test_lifecycle.py 8项（复用test_assembly真实装配＋受控端口）：结论带属主证明＋重放不重派、效果失败unknown不重发、错correlation/unit→unknown、终止unknown→unknown、release精确集/幂等/已释放新请求拒、recover伪造sessionRefs拒、preconditions形状、未装配capabilities=false+typed拒。实现修正：context_ref补environmentNamespace/directoryBindingRef、重放先短路释放预检；断言未放宽无skip。详见[evidence/agent-unit-model/lifecycle-coordinator.md](evidence/agent-unit-model/lifecycle-coordinator.md)。

验证（串行、terminal）：test_lifecycle.py **8P/0F exit0**；产品integration **312P/0F**；核心269P/3F同三个已登记继承ID。剩余按评审3清单：wire生命周期绑定＋schema lifecycleOperation形状＋镜像再生成＋test_management守卫改写（保留未装配拒绝语义）；apply_profile派生＋CLI；三家消费终止族与效果证据。C受控，P/M无新增；无用户数据/服务/push/主树合并，M0费用unknown。检查点后并行推进wire与apply_profile，不标完成门。

### 2026-10-06 wire 生命周期绑定＋apply_profile 检查点（PARTIAL）

前置efb2b18dcf。wire切片由品牌无关slice-worker完成（写权释放）：agent_core_wire.py三处理器（lifecycleOperation直投影）＋preconditions形状校验补漏＋supportedMethods按nodeLifecycle门控零新错误映射；schema.py管理块增lifecycleOperation形状；镜像生成器再生成两次核验；test_management原守卫**改写不删**（未装配仍CAPABILITY_UNSUPPORTED/不广告/零reserve＋nodeLifecycle False断言），test_wire_lifecycle.py 8新反例。主会话并行落apply_profile（声明永取核心Profile快照、A11零回写、同请求异内容拒）＋test_apply_profile.py 6反例；连带修复客户端negotiate键集补nodeLifecycle（契约合法扩展后138项单根因连带红）＋两处测试键集跟随契约。详见[evidence/agent-unit-model/wire-lifecycle-and-apply-profile.md](evidence/agent-unit-model/wire-lifecycle-and-apply-profile.md)。

验证（串行、terminal）：全产品 `products/agent-tools/tests` **689P/0F exit0**（含CLI/契约/发行/真实HTTP）；证据组合（management+wire+lifecycle+apply_profile）**65P/0F**；核心269P/3F同三继承ID无新增；records组合115P/0F。失败账：wire二次投影2项、客户端键集138项连带、两处夹具键集；断言未放宽无skip。

剩余：CLI生命周期命令与三Skill同步、三家消费终止族与效果证据、任务/结果闭环、发行验收、真实M（pi+deepseek）、七家扩展。C受控；P/M无新增，M0；无用户数据/服务/push/主树合并，费用unknown。检查点后继续，不标完成门。

### 2026-10-06 CLI 生命周期命令接线（测试待补）＋子代理通道故障记录（PARTIAL）

前置e8ed406be9。平台事件如实入账：四个并行slice-worker（CLI命令、三家终止族）连续遭遇"Model request failed"（用户确认为opencode账号额度耗尽；换账号后本会话仍秒失败——**会话启动时快照子代理模型绑定，运行中不热加载，须开新会话生效**）。CLI切片代理中断前留下半成品：lifecycle.py（请求/投影校验＋disposition，语义完整）＋cli.py接线（nodes stop/release/recover/apply-profile）。主会话修复两处破损后全绿：list/inspect分派分支缺`method, params = prepared`（UnboundLocalError 24F→1F）、恢复NODE_OBSERVATION_UNAVAILABLE发前门（→0F）。

验证：全产品 `products/agent-tools/tests` **689P/0F exit0**（修复前后同基线，无回归）。**CLI生命周期反例测试尚未编写**（形状/能力门控/幂等/丢回执/token不回显/A17），下一切片必须补齐后才算本项收口；命令行为未经独立反例验证，不声明完成。三家终止族消费切片零进展（全部代理失败未落盘）。

交接状态：7检查点已提交（3f40afad33→e8ed406be9）＋本CLI接线为第8检查点；工作树仅剩本文件与cli.py/lifecycle.py/test_profile测试相关改动待提交。剩余队列不变：三家终止族→任务/结果→三Skill同步→发行验收→真实M→七家扩展。M0、费用unknown（子代理失败轮次的token消耗记平台账）。

### 2026-10-06 第一批并行切片整合＋Spec Kit 配置语义修订纳入（PARTIAL）

前置86126f94d4。开工核验clean（仅.env未跟踪，绝不入库）；活服务ordessa_server属另一worktree，未触碰。用户mid-turn裁定：specs/029四文档为直接修订原Spec Kit（非新增工单），配置统一Profile JSON/临时清单可直接提交/运行中整单更新由核心算差异交owner/生命周期与任务独立于Profile/restartRequired默认不隐式重启/复用原Profile快照+Assembly+管理协调器+授权+Operation链/期望与actual严格分开/遗漏旧声明须明确reset或disabled不得猜成重置/unknown不重发部分应用逐项报告；按核心契约→实现→wire/schema→CLI→Skill顺序纳入，验收矩阵PJ01–PJ13（plan.md）。回执：已完整读取四文档修订diff（+107/−22）并纳入本账，PJ项均未实现，随本检查点显式提交四文档。

第一批并行子代理（安全边界已全部释放写权，成果保留未回退）：test-author产出products/agent-tools/tests/test_lifecycle_cli.py（25函数97参数化用例：形状/白名单/能力门控/幂等/丢回执exit6/A17哨兵token/跨环境拒/投影形状）；pi slice-worker产出runtime_channel/projection/lease/termination四适配器＋配置journal＋终止族消费（318P=271+47，其中20项真实pi进程0.86.1零模型P级：/proc核证HOME/XDG/PI_CODING_AGENT_DIR/PI_OFFLINE隔离、凭据形键不存在、ACK-clamp readback失配unknown、真实stop退出码+/proc零残留）；claude slice-worker产出owner_projection/assembly/termination/configuration_face/native_evidence/ownership（242P=200+42，全C受控：受控sleep子进程实证终止效果、伪造证据拒；P级当时二进制缺席标ABSENT）；repo-scout两份盘点落盘legacy-consumer-remaining-map.md（15类活消费者+退出条件）与tasks-results-gap-map.md（ManagedInputReservations已实现零装配、supports.managedInput硬编码False、三家完成事件解释器已在提供者侧缺回写桥、cancel无语义）。

主会话串行整合复跑（专属Python，句柄terminal）：`PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src <python> -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q` **786P/0F exit0、216.57s**（原689＋新97）；`PYTHONPATH=plugins/harness/pi/src:packages/backend/harness-transport/src:plugins/harness/records/src <python> -m pytest -c plugins/harness/pi/pyproject.toml plugins/harness/pi/tests -q` **318P/0F、18.62s**；claude同型 **242P/0F、17.43s**。失败账：首次全量缺PYTHONPATH致14F（ModuleNotFoundError: ordessa_harness_*，环境问题非代码回归，test_independent_server_providers.py导入三家）；补显式三家+运输+records路径后全绿。断言未放宽、无skip、无mock冒P。

平台事件：上一会话四个并行slice-worker曾因opencode账号额度秒败（会话启动时快照子代理模型绑定）；本会话新绑定生效后全部正常。用户mid-turn修复Claude Code二进制（/home/maoqh/.local/bin/claude，2.1.291实测），claude P级切片解锁待派。发现两项待修缺口：agent_core_wire.py:73-78/111-112未广告不派发applyProfile（apply-profile端到端不可达，核心apply_profile已在management.py:180）；lifecycle.py:152-163对expectedPublicationRevision只白名单不比较（PJ04基础版本核对缺口）。均属主执行者共享域，随配置语义修订一并落。

C/P/M：C新增139（97 CLI反例+42 claude）；P新增20（仅pi真实进程零模型）；M0（真实模型/真实Harness授权已有，claude修复后待用）。未验证：三家纵向端到端、PJ01–PJ13全矩阵、applyProfile派发、任务/结果、发行验收、真实M。成本：子代理4个（test-author×1、slice-worker×2、repo-scout×1），token精确值以平台账为准（subagent_tokens合计约1.3亿含上下文重读），真实外部模型调用0。无第三方安装/用户DB/凭据/全局配置/服务操作/push/主树合并。显式stage本轮34文件（四Spec文档+pi/claude切片+CLI反例+两侦察图+本账），.env不入库；检查点后按Spec修订顺序落核心契约，不标完成门。

### 2026-10-06 第二批：Claude P 级真实进程＋codex 终止族＋配置语义架构裁定（PARTIAL）

前置d7c0c04273。用户mid-turn修复Claude Code（/home/maoqh/.local/bin/claude→/home/maoqh/.local/share/claude/versions/2.1.291，原生ELF，SHA-256 078fad28…，2.1.291实测）。architecture-reviewer第4次咨询（只读）完成配置语义修订7问全裁定：临时清单快照落同DomainStore独立命名空间agents.profile-snapshots、内容寻址确定性ref（snap-<digest>，revision恒1）、与operation reserve同事务（PJ12原子/孤儿分账）；互斥/归一化/摘要在核心入口reserve前（digest取manifest_content canonical输出）；整单diff派生放apply_profile扩展＋configuration.py纯函数derive_change，base核对走fence→operation链，同ID改kind/schema一律发前拒（转换支持单独立项）；omission单次交互reserve前拒＋错误details带具名缺口ID＋修复后须新requestId，reset/disabled确认后沿applied不新增outcome，skippedOptional/缺口进operation_view投影；allow_restart仅表示接受restartRequired结果、重启永远走独立lifecycle且授权按次核对、CLI禁止--and-restart类旗标；expectedPublicationRevision只白名单不比较是真bug必须修CAS；wire复用agents.nodes.applyProfile名升级参数、契约升agent-assembly/3、能力门控广告于configurationManagement下、低层configuration.apply逐字节不变；红线：快照库不得长出"每节点最新期望"索引、匿名快照须独立权限对象类。实施顺序：契约冻结→快照持久→管理协调器整单→wire→CLI→Skill。

Claude slice-worker产出runtime_channel.py（真实进程通道：SHA pin、私根布局、HOME/XDG/CLAUDE_CONFIG_DIR隔离、凭据形键全丢、managed写屏障、close/release）＋13项P级真实进程测试（**关键事实：initialize握手免登录**，receipt tokenSource:"none"为进程自身无登录事实；模型turn/can_use_tool/result需登录，未借用户登录，如实ABSENT）＋claude-real-process-evidence.md；终止族真实消费（真实进程句柄→ClaudeTerminationCoordinator→真实退出码证据互证，伪造退出码typed拒，unknown路径进程不触碰）。codex slice-worker产出termination.py（CodexTerminationEvidencePort：pin argv/密封私根/真实pid/returncode/proc残留/伪造拒/observe_termination冷观察）＋provider stop/release完整begin→效果→证据→record＋runtime_channel close保record/release拒活进程＋19项C＋5项P（真实codex 0.159.0停止退出码证据/proc零残留/二次stop单发/epoch变更opening保留）。如实登记：codex二进制自身启动时spawn短命git子进程（plugins clone），stop后约2秒自清，P测试60秒有界等待。

主会话串行核实（句柄terminal）：`PYTHONPATH=plugins/harness/codex/src:packages/backend/harness-transport/src:plugins/harness/records/src <python> -m pytest -c plugins/harness/codex/pyproject.toml plugins/harness/codex/tests -q` **251P/0F exit0、22.70s**（229C＋22P）；claude同型 **255P/0F exit0、22.17s**（242C＋13P）。断言未放宽、无skip、无mock冒P。

C/P/M：C新增19（codex终止）；P新增18（claude 13＋codex 5，真实进程零模型）；M0。三家P级现全有真实进程证据（pi 20＋codex 22＋claude 13）。未验证：登录态模型面（claude需登录、pi/codex离线）、PJ01–PJ13、applyProfile派发、任务/结果、发行验收、真实M。成本：子代理3个（architecture-reviewer×1约54万token、slice-worker×2），真实外部模型调用0。无第三方安装/用户凭据/全局配置/服务操作/push/主树合并。显式stage本轮11文件，检查点后按裁定顺序落核心契约（步骤1–3主执行者独占），不标完成门。

### 2026-10-06 核心优先／Luna 指导派工与继承配置切片复验（PARTIAL）

用户要求先完成不认识具体 Harness 的核心，主会话全程指导多个 Luna 承担编码和验证。已核实前置26491dd180744d38dec4edb392fa59795ae476fe、23tracked dirty +513/-113 为前执行者配置语义成果，另.env未跟踪（不读不提交）。上轮状态/目录问答no progress，本轮实际补上中断全套验证并审出明确缺陷。三个 gpt-6-luna 子代理仅阶段A只读，主会话唯一测试/Git/账本作者；具体后续单文件写权见[evidence/agent-unit-model/luna-core-dispatch-20261006.md](evidence/agent-unit-model/luna-core-dispatch-20261006.md)。这是用户新分工授权，不改原合同语义，不开新树/第二共享写者。

实际命令 `PYTHONPATH=plugins/harness/codex/src:plugins/harness/pi/src:plugins/harness/claude-code/src:packages/backend/harness-transport/src:plugins/harness/records/src /home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q`：787P/0F，exit0，218.57s，句柄46323已terminal。此前786P属旧快照，不累计；此次未跑evidence独立组合或全Core/品牌包，不将产品绿当PJ全验收。strict五单校验exit0，仅资料结构。

Luna只读核实：Agent模块未导入具体Harness品牌；但inline准备先stage未提交snapshot又read，必失败；snapshot namespace/权限类偏离最近裁定；wire没有临时清单及applyProfile转发、omission安全具名投影；无变化重放/迟到事实/拒单请求键/未dispatch竞态待反例。各项不能因787绿忽略。保留并显式纳入继承23文件及本轮账/派工记录作为PARTIAL检查点，再分别开放核心与wire非重叠写权，主会话不自行大部分编码。模型M0，无新原生模型调用/第三方安装/用户数据/登录/全局配置/用户服务/push/主树合并；费用unknown，token以平台账为准。

### 2026-10-06 核心配置原子性、拒单／无变化回放与多提供者独立验证（PARTIAL）

前置检查点3072100ec8f7d6c3f01a55261c1b9cf242bda583保存继承切片。三名gpt-6-luna在原树按唯一文件写权完成全部本轮生产代码／新测试：core_impl写profiles/assembly/management及公开错误同一性导出；wire_impl只做公开DTO解码、核心委托和错误投影；review写单Environment/Registry的双协议受控提供者验证并独立读审。主会话负责接口指导、读审、串行执行、状态及Git，没有自行承担生产代码或测试实现。各写者均冻结后才实跑；修复再释放再冻结，无并行测试。

实际修复：inline清单准备不再读取尚未提交快照，原快照和Operation reserve仍同事务；独立agents.profile-snapshots及对象read/write权限预检，拒权零占用；遗漏拒单在原env_requests存安全ID收据、未提交清单正文/快照/配置scope，旧ID修正请求冲突；原OperationStore拒读data-only收据时仅用exact-digest域结果正向核实，域结果缺席重抛Unknown，绝不空回退；no-change原请求先查原收据，无重派；新请求须核对完整owner确认与当前revision/unit/scope/actual/unknownItems，否则原unknown/refused，不把历史applied当当前事实。公开wire沿既有/3互斥来源、applyProfile能力门控、ApplicationPolicy公开DTO及具名遗漏错误，不加入品牌解释或另一调用链。低层applyConfiguration保留。

实跑命令／完整失败账／限制见[evidence/agent-unit-model/luna-core-dispatch-20261006.md](evidence/agent-unit-model/luna-core-dispatch-20261006.md)。八文件末端组合 **137P/0F、exit0、10.12s**：新增核心16、wire16、独立双提供者／导入反例11，共43；其余为原assembly/apply_profile/management/lifecycle/wire-lifecycle，不累计快照。中间126P7F与136P1F均保留失败原因，修正夹具使用公开JSON/ActivationRef/零占用与已用请求区别，未改原断言/Store契约或skip。新增证据均C（真实临时SQLite＋受控owner），两不同协议格式完整prepare→apply→inspect及一家退役另一家继续可用；不当三家原生P/M。Luna终审无本切片新阻断：Unknown域缺席重抛、完整实际事实比较均闭合。schema镜像核验exit0、strict五工单校验exit0，仅材料检查。

当前剩余未收口：required材料装配、公开访问/连接、托管输入公共接入及真实writer/结果回写、CLI/Skill、完整PJ矩阵与发行隔离仍PARTIAL。另发现派发前重核拒绝会留reserved并推进基础快照，不能单独终结操作而把未发送清单当后续基础；[pre-dispatch-refusal-proposal.md](pre-dispatch-refusal-proposal.md)已准备原子修复提案。统一只读查询范围见[operation-read-proposal.md](operation-read-proposal.md)，两项均已用自然语言问用户，未获裁定前不实施依赖语义。核心全套继承kernel_direction三红本轮未复跑，不当已修。M0；无第三方安装、用户数据/凭据/全局配置/用户服务操作、push或主树合并；费用unknown，子代理token以平台账为准。.env不读不入库。整体未完成。

产品末端回归：首次 **786P/1F exit1、215.71s**（旧CLI测试假定健康wire未广告applyProfile，事实已变化）。wire Luna将原负例改为真实无issuer首次装配，保capability refused／不广告／零作用，并新增健康wire广告但CLI缺baseProfileRef在客户端schema发前PARAMETER_INVALID的反例；生产CLI未改，仍未可用。定向CLI **99P exit0、58.36s**，冻结后追加断言的两项单独再跑 **2P/97 deselected exit0、1.47s**（过程账见evidence）。最终冻结全套同前述完整命令（加`--tb=short`）**788P/0F exit0、217.70s**，句柄83852已terminal；不是与137项证据相加的独立计数。diff检查exit0；新竞态与CLI形状缺口已窄登记known-issues。全部测试无skip，不用fixture冒真实任务。

待下一核心批的只读依赖盘点已收入本轮evidence：复用原ResourceProvider/SecretRef端口，但Agent受权材料路由／短借作用scope／unknown归还尚缺，不能另走CoreRuntime.submit第二账；ManagedInputReservations可按原一次性composition公开，生产capture/native state/single-submit writer/双来源receipt恢复由各domain owner提供，核心不解释品牌帧。managedInput继续false，不以挂载类冒生产可运行。主会话显式核对本轮源码／测试／文档后保存PARTIAL检查点，无push或主树合并。

### 2026-10-06 托管输入的核心公共装配与缺席反例（PARTIAL）

前置8900a56f2df6dfb960e74983f9fa824590b4e321，tracked clean，仅.env未跟踪且不读取。继续指导三名Luna：core_impl唯一生产写域public.py；core_review唯一新增测试文件；wire_impl独立只读复核。主会话只指导、读审、串行测试、账本和Git。公开重新导出原9项输入DTO/ports/class，在原AgentServices内用同Environment/NodePublication装配ManagedInputReservations；3个可选端口首次固定，后续不同实例及None后注入均拒。没有新核心、registry、持久账、品牌协议或原生writer，原显式issuer API不改，managedInput继续false。

完整命令及反例见[evidence/agent-unit-model/public-input-composition-20261006.md](evidence/agent-unit-model/public-input-composition-20261006.md)。首轮五文件121P/0F exit0 9.74s；追加缺单端口及缺观察反例后13文件组合261P/0F exit0 18.13s（新增公开装配14项，其他247既有）；源码及测试冻结产品全套788P/0F exit0 218.25s；独立审阅后只调整普通Session正例为无first观察端口，新增文件定向14P/0F exit0 0.51s，所有原断言保留。均C级受控SQLite/port/issuer，新增P0/M0；不累计重复快照，不用产品绿代生产输入。没有skip，继承kernel_direction三红未复跑。

边界：输入claim/reconcile仍按原API接收issuer，校验同Store，不新增唯一部署issuer对象绑定；未来宿主必须使用原装配issuer/verifier。本批不公开任意context/evidence到wire。生产capture/native state/writer/双来源回执未装配，不能对用户声称已发原生输入。两项待裁定提案（统一操作读取、派发前拒绝原子恢复）仍待回答，不把继续当选项裁定。

下一缺口只读盘点：完整材料路由还缺资源选择、授权scope、原Operation步骤接缝，不能转调CoreDispatch另建执行账；公开access仅schema/Provider合同、未有Core服务或wire。另发现配置更新只拦resourceRefs而未拦递归secretRef，准备路径已拦；后续优先按原required拒绝/optional skipped规则补发前门，不擅自实现秘密解析。全程无模型调用、第三方安装、用户服务/数据/凭据/全局配置操作、push或主树合并；子代理费用unknown，token以平台账为准。整体未完成。

### 2026-10-06 配置未解析SecretRef发前门与后续语义裁定（PARTIAL）

前置7ff3021d7b。三名Luna继续按原树唯一写权：core_impl仅management.py；core_review新增test_configuration_unresolved_secrets.py；wire_impl独立只读。主会话指导/读审/串行测试/账本/Git，没有自行写实现或测试。按既有未装配材料规则，把递归secretRef与resourceRefs同列unresolved：required在reserve/claim/apply作用前ConfigurationUnsupported，optional从effectiveDeclarations剔除、逐项rejected，opaque引用仍保留原请求身份。没有秘密解析、借用、新注册中心或执行账。mode=no-change-verification及Profile metadata restore保留原行为；含秘密引用的这两特定场景只做源码审阅，未新增实测，不冒绿。

过程证据见[evidence/agent-unit-model/configuration-unresolved-secrets-20261006.md](evidence/agent-unit-model/configuration-unresolved-secrets-20261006.md)：首次五文件82P/1F exit1 6.17s，whole Profile夹具遗漏原model声明而先触发omission，失败保留；只修完整清单沿model id改payload，原异常类型/零副作用断言保留，复跑83P/0F exit0 6.28s（新增7，既有76）。冻结后产品全套788P/0F exit0 215.85s，句柄71668terminal；不与新增证据累计成场景数。独立终审合法SecretRef形状、optional owner只收正常声明、同id重放无重复作用。C级临时SQLite受控owner，P新增0/M0，无skip。继承kernel_direction三红未复验。

用户已逐项答复采用：确定未发送的配置拒绝须原子记录并恢复上次配置基准，已claim/unknown继续占用不重发；统一读取仅本principal自己的状态/版本/目标/是否有结果，操作及目标双read ACL，不正文/恢复/重发。已写回两提案裁定段，下一批准备实施，当前尚未实现。access租约签发/续期/撤销/断开与unknown恢复合同仍缺，不能用InvocationContext或C1另一执行账租约冒充。完整资源选择/受权材料路由、生产输入及CLI/Skill仍未收口。无第三方安装、用户数据/服务/凭据/全局配置操作、push或主树合并；.env不读不入库，费用unknown。整体未完成。

### 2026-10-06 已裁定拒绝／只读查询进入下一核心批（IMPLEMENTING）

前置01fd4442d5，tracked clean/.env仅未跟踪且不读。两项用户逐项确认后，三名Luna再次获非重叠写域：core_impl同Store可选版本化未claim终结能力、SQLite原事务与management；core_review独立拒绝反例；wire_impl小只读operations_read服务、public组合与独立查询反例，不写wire/CLI/schema。写权及验收见[evidence/agent-unit-model/core-refusal-read-20261006.md](evidence/agent-unit-model/core-refusal-read-20261006.md)。保留原OperationStorePort冻结面，缺可选能力/旧回滚事实不猜、不双事务；issuer权限重核claim前后都可能失败，持久任何step存在即不得恢复base。读取只metadata且零owner，不用有作用的configuration.query或带正文operation_view。准备未发布节点的合法读权限接缝需独立核实，不把无Node记录自动当损坏或放宽其他目标。

本段为开始实施记录，不是完成或测试通过；当前批尚无新测试证据。原生P新增0/M0，禁止用户服务/模型/数据/凭据/全局配置操作/push/主树合并继续有效。

### 2026-10-06 已裁定核心拒绝恢复与metadata只读完成受控验证（PARTIAL）

前置01fd4442d5，沿上段独占写权三名Luna完成全部实现/新测试，主会话仅指导、读审、串行执行、账本/Git。原OperationStorePort/oe-contract/1未变，新增同Store可选pre-dispatch-refusal/1；SQLite以无任意step、reserved/digest/revision及fence CAS原子终结拒绝与恢复预留前来源；首次仍抛原typed错误，原request后续只回放terminal receipt。issuer claim后失效优先保留未知占用。缺可选方法额外callable核验以防Protocol类型缓存假阳性，旧intent缺事实拒绝且保持占用，不双写模拟。原全optional分支完整具名rejected未改。

原AgentServices加小只读AgentOperations，沿唯一core.operation-identities/OperationStore、可信principal与双read ACL，严格6字段metadata不正文/结果/evidence/steps；不读owner、不issuer、不恢复、不状态推进。未发布preparation只投影已固定计划目标且检查Node读权；published或其他本应有Node的操作缺记录拒绝；provider退役/Usage释放后合法历史仍读。未wire/CLI，不广告任务结果完成。

实测完整命令/失败账见[evidence/agent-unit-model/core-refusal-read-20261006.md](evidence/agent-unit-model/core-refusal-read-20261006.md)：首六文件82P17F1E exit1 8.87s，含read_domain形状、非法canary夹具、失效反复注入/CAS时间/继承方法删除及原错误合同变化；二轮97P2F exit1 8.99s，未提交竞争事务与Protocol缓存缺方法typed漏洞；按唯一作者修复、原断言/原management测试未改无skip，三轮99P0F exit0 8.89s。全冻结产品788P0F exit0 216.51s。新增两个直接store反例后最终16文件组合293P0F exit0 23.19s（本批拒绝15＋读取10，另268回归），原environment-api contract及SQLite独立76P0F exit0 1.05s。不是多个套件相加的独立场景数；临时真实SQLite＋受控owner契约C，新增原生P0/M0；继承kernel_direction三红未复验。

跨作者独立终审窄范围无具体阻断；完整材料/SecretRef授权路由、access租约签发撤权合同、生产输入writer/回执、完整结果投影和CLI/Skill/发行隔离仍缺。全optional未发但基础推进的旧分支另备[all-optional-refusal-proposal.md](all-optional-refusal-proposal.md)，已自然语言提问待答，本次不私改既有结果协议。known-issues已对应更新已修窄范围与剩余边界，不称所有拒单均修。无原生模型调用/第三方安装/用户服务、数据、凭据、全局配置操作/push/主树合并；.env不读不入库；费用unknown、tokens以平台为准。保存PARTIAL检查点，整体未完成。

### 2026-10-06 输入统一部署权限来源与核心依赖方向复验（PARTIAL）

前置a5524f05a74d0e3ee26a58ce11c08da3c5958afb，tracked clean、.env仅未跟踪不读。用户对自然语言解释明确答“采用，统一使用服务器配置”，裁定写入[input-issuer-binding-proposal.md](input-issuer-binding-proposal.md)。继续三名gpt-6-luna：core_impl独占inputs/public源；wire_impl新增9项输入反例、四原fixture只调构造绑定；core_review独占跨组件测试迁移/静态保留守卫/CI。主会话只指导、读审、串行实跑、文档/Git，全部生产编码及新测试由Luna完成。

ManagedInputReservations初次绑定原部署issuer，同Store不同authority或不同issuer对象在claim/query前拒绝；未绑定仍能reserve，但不能通过方法实参晚注入，公共重组不能换issuer。保留原context/verifier/持久step与unknown机制，不新增核心、权限真值、品牌协议或原生writer。独立审查发现原claim在请求级鉴权前读操作，沿原Environment/principal/reserve invoke许可前移，Node write仍由原intent目标核验，新增三种拒权零读取反例。

完整命令、退出码和失败账见[evidence/agent-unit-model/input-issuer-kernel-boundary-20261006.md](evidence/agent-unit-model/input-issuer-kernel-boundary-20261006.md)。输入六文件：首收集1E exit2（新测试错误import），再132P1F exit1（新capture fixture key错误），仅原作者修引用/夹具，原断言不删；最终133P0F exit0、10.04s，新9＋原124。核心/迁移集成首273P1F exit1（新AST守卫Python3.14/3.12摘要差异）；以只读HEAD原测试重算跨版本规范化保留摘要后274P0F exit0、7.46s：核心261＋原迁移11＋定位反例2。原11测试46assert及主体保留，仅SIGKILL子进程源码路径改，CI增加独立集成步骤；原核心方向scanner/自反例未改，继承三方向红实测已消除。无skip；不把迁移计数减少算删测，也不把runner报告GREEN_NO_SKIPS时仍ABSENT的worker/sidecar/ACP资产算产品可用。产品本轮全冻结全套788P0F exit0、217.32s，句柄4875terminal，不与133项组合累计独立场景数。

输入新证据为真实临时SQLite＋受控owner/权限的C；原迁移包含自有Python/SQLite SIGKILL恢复已通过，非原生Harness P/M，本轮新增原生P0/M0。严格五工单校验exit0只是材料检查。完整受权材料/SecretRef路由、access签发撤权及真实writer fence、生产输入发送/双来源回执、结果投影与CLI/Skill/隔离发行仍未收口；全optional拒单恢复提案待答未私改。无安装/用户服务/数据/凭据/全局配置/模型调用/push或主树合并。费用unknown，子代理tokens以平台账为准。

### 2026-10-06 继续核心014资源准入元数据／材料受权扩展裁定（IMPLEMENTING）

前置7f7b98fb73，tracked clean、.env仅未跟踪不读。用户明确继续不停止，仍指导多个gpt-6-luna：core_impl独占registration/environment/resources/public，wire_impl独占新resource_provider_admission_view测试，core_review只读审查及材料接缝提案；主会话唯一文档/串行验证/Git。工单[014-resource-admission-metadata.md](work-orders/014-resource-admission-metadata.md)固定Stage descriptor/support snapshot、同Registry/唯一active Host、独立agents.resources read、无provider callable、零材料作用；原C1二元lookup/DTO签名保持。首strict校验exit1（新单缺节及共享路径串行声明等），只补工单结构/声明后全14单strict exit0，仅材料检查。源码/测试尚未实跑，不称通过。

独立三路盘点一致：C1 Acquire不承载Agent授权/完整ResourceRef，UNKNOWN无lease/handle时现reconcile无法查询；SecretPort adapter不能证明target/activation授权；访问lease也缺权威撤权到实际writer fence的完整接缝。因此不把现接口接上冒材料或访问可用。用户已明确答复“采用这个受权扩展”，记录[material-authorized-capability-proposal.md](material-authorized-capability-proposal.md)：同已注册provider可选受权能力，原issuer/operation/step/Usage、精确版本/用途/消费target、lost receipt原correlation query，首片非秘密。014收口后继续冻结具体合同并实现，不为了检查点停工。全optional确定未发送恢复基准的另问题已重新用自然语言提出，仍待答，未实施该分支。M0/用户服务0，未新增安装或跨树写。

014实测收口：[resource-admission-metadata-20261006.md](evidence/agent-unit-model/resource-admission-metadata-20261006.md)。新增首17P2F（误用新test不存在辅助方法）后19P过；原公共链306P1F抓Environment反向依赖agents DTO，沿原guard把类型移core，不改断言，307P过。跨作者读审追加Host身份副本与明确未发布stage清理，新增21项首20P1F（原policy断言插入错函数），恢复原断言原意义；最终新21P0F exit0 0.18s、core+集成+API307P0F exit0 8.22s、产品全冻结788P0F exit0 217.74s。三名Luna完成全部源码/测试，主会话串行复验、读审、账本/Git。资源元数据读写权独立；同Registry原descriptor/支持集固定且commit前整批核验；返回descriptor/Host activation均副本；原C1二元lookup及签名不改。未知publish不回滚，不触Agent unknown步骤/Usage。新增21为in-memory单元/合同，不冒实际材料获取或真实服务绿；原生新增P0/M0。

继续015：主会话已将[material-contract-v1.md](material-contract-v1.md)冻结为首阶段不可变ResourceRef/Pin/Node目标/关联/描述/receipt/三态及可选provider能力，权限仅原Issuer/Verifier，撤销了Luna曾建议的新Authorizer（未实现）。首阶段只合同，后续才同Registry能力、具名step/Usage与真实材料消费；不把纯DTO或014绿冒材料可用。所有代码在本轮产品回归期间冻结，仅准备后续设计。整体仍PARTIAL，依用户“不要停”继续下一批。
