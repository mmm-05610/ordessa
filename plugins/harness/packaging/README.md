# packaging/ — 可选安装打包（不是运行链）

这里的东西**只在人工执行安装/构建时**被读取：`npm ci` 的 npm 根、离线锁、
vendor 安装包、SBOM、上游安装器 provenance。主运行链（Server → sidecar
bundle → Worker → bwrap → adapter）从不读这个目录，也不会因为它缺失而降级、
猜测启动路径或自动安装任何东西。运行链用的入口是部署文档里显式给出的
`adapter.command` / `adapter.args` / `adapter.driver`。

目录按品牌一一对应：`packaging/<品牌>/` 就是一次 `npm ci` 的工作目录，
清单与锁同目录、不拆版本、不合并依赖。构建产物落到插件目录之外，由
Operator 绑定成 `runtimeArtifactMounts` 的 source 路径。

| npm 根 | 直接依赖（钉版） | 锁条目数 | 构建脚本 |
| --- | --- | --- | --- |
| `codex/` | `@agentclientprotocol/codex-acp` 1.1.14 | 25 | `build-codex-runtime-artifact.mjs` |
| `pi/` | `@automatalabs/pi-acp` 0.5.0 | 325 | `build-pi-runtime-artifact.mjs` |
| `claude/` | `@agentclientprotocol/claude-agent-acp` 0.81.2 | 112 | `build-claude-runtime-artifact.mjs` |
| `claude-legacy/` | `@agentclientprotocol/claude-agent-acp` 0.75.1 | 112 | `build-claude-runtime-artifact.mjs --legacy-alias` |
| `dsh/` | `@deepseek-ai/dsh` | 584 | `build-dsh-runtime-artifact.mjs` |
| `kilo/` | `@kilocode/cli` | 5 | `build-kilo-runtime-artifact.mjs` |
| `qwen/` | `@qwen-code/qwen-code` | 49 | `build-qwen-runtime-artifact.mjs` |

`codex/`、`pi/` 各自的 `vendor/*.tgz` 是本品牌的用户级 ACP 适配器离线安装包，
`artifacts/SBOM.json` 是同目录那把 `package-lock.json` 的钉版投影
（`source_lock: package-lock.json`）。这两家原先共用一个 npm 根
（`runtime/`，一度叫 `packaging/codex-pi/`），锁已按品牌真正拆开：

* 拆法是从**已评审的那把共用锁里剪出各自的可达子树**，不是重新解析。每个保留
  条目的 `version` / `resolved` / sha512 `integrity` 逐字节不变，所以拆锁后的
  传递依赖变化为空；两家共用 `node_modules/zod@4.6.4`，剪完各自留一份同版本。
* `overrides` 也只带本品牌仍解析得到的钉版：两家都保留
  `@agentclientprotocol/sdk` 1.3.0，因为共用锁里两个适配器各自的
  `node_modules/@agentclientprotocol/sdk` 就是被这条 override 钉在 1.3.0。
* `build-pi-runtime-artifact.mjs` 原本会从同一个根里算出 Codex 闭包来证明
  "Pi 工件不带 Codex 的包"。拆开后再没有 Codex 闭包可算，该函数改成与 Codex
  构建器对称：闭包缺失即不可能泄漏，按名字排除的断言照旧执行。

`claude-legacy/` 只供旧 `claude` upstream alias 使用，不能替换 `claude-code`
的 0.81.2 工件。先在该目录 `npm ci`，再执行
`node packaging/builders/build-claude-runtime-artifact.mjs --legacy-alias --output ABSOLUTE_DIR`。
构建器验证 lock 与 0.75.1 包闭包，独立 marker 和树摘要；运行时固定挂载目标为
`/runtime/artifacts/claude-legacy-runtime`。当前统一 `harness-install-set.py` 只组装八个
canonical 家族，尚未自动安装这个 alias 工件；Operator 须明确提供只读挂载，
否则 access entry 拒绝连接。

安装器里**家族 id 不等于目录名**（`claude-code` → `claude/`），所以映射只写在
一处：`harness-install-set.py` 的 `NPM_ROOTS`。`hermes` 与 `opencode` 没有
npm 根（前者是 Python 包，后者钉单文件二进制）。任何一条映射缺失或写错，表现
都是静默跳过 `npm ci` 后报"适配器缺失"，所以新增家族时必须同时登记这张表，
并被上表那一列构建脚本对上。

`codex/provenance/` 是上游官方安装器的**签入字节 + sha256 元数据**
（`codex-deepseek-setup.sh`、`official-script.json`）。`codex/production.py`
的 `OFFICIAL_SCRIPT` / `OFFICIAL_SCRIPT_METADATA` 只把它们当证据比对，
从不执行、从不投影进 guest。

原 `runtime/package.json` 里的 `dependencies` / `overrides` 钉版现在只存在于
上面这些品牌锁里。`runtime/package.json` 保留下来，但只承载 sidecar 视图自身
需要的 ESM 包根信息（`type`、`engines.node`）——它随视图一起被打包，不带任何
安装期数据。
