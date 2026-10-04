---
id: "013"
slug: "local-initialization"
batch: "agent-tools-first-20261004"
baseline: "adce734db21945181bf93da9720158d05e957654"
baseline_status: "approved"
state: "AT_013_DONE"
depends_on: [{"condition": "005已验证CLI独立分发基础；不依赖未完成native能力", "order": "005"}]
write_paths: ["products/agent-tools/**", "plugins/harness/api/src/ordessa_harness_api/command_discovery.py"]
forbidden: ["其他工作树/**", "用户数据库/凭据/全局配置", "plugins/agent-tools/**"]
ruling: "R-0006"
terminal: ["AT_013_DONE", "AT_013_PARTIAL"]
waive: []
serialize_with: ["001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"]
parallelism: "none"
parallelism_reason: "主会话写CLI/Skill/测试，执行者仅public候选目录和生成镜像，审阅者只读；无同文件并写"
---
# AT-013 本机初始化发现

## Objective

用户要求CLI/Skill初始化探查系统Harness二进制。候选名称由Harness公开API权威发布并构建期镜像；CLI无后端运行依赖。

## Scope

init仅读当前调用者机器绝对PATH、文件类型和execute权限，不执行二进制/version、不联网/安装/启动服务、不修改全局配置。output仅用户选的新文件600、不覆盖。不是Server宿主发现或运行配置真值。

## Requirements

### Requirement: 真实文件观察与证据分层

#### Scenario: 正向

**WHEN** PATH有常规可执行候选
**THEN** 给出family/command/所有shadow路径与来源，仅executableFound；artifact/provider未查、runtimeReady未知。

### Requirement: 缺资源与故障拒假成功

#### Scenario: 反例

**WHEN** 空/相对PATH、目录/FIFO/坏链接/无执行位、权限变化、catalog损坏、报告已存在
**THEN** 不执行、不读取凭据、不覆盖；缺候选exit4，参数/报告拒exit2；扫描不可知保留scanUnavailable，缺catalog无fallback。

## Gates

| Gate | Assertion | Counter-example | Absent / unknown |
| --- | --- | --- | --- |
| C | 公开候选镜像digest与源码匹配 | CLI私有硬编码表、缺asset猜名单 | 拒build/发现 |
| F | Linux真实文件观察且零执行 | fixture marker被写、目录伪binary | 未找到exit4；权限不可知 |
| W | fresh wheel独立安装可init | 导入Harness/Server、触网 | 缺资源失败不skip |
| S | Skill不把本机事实当远端授权 | found提升nodes/ready、自动安装或登录 | 明确unknown |

## Validation

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -c products/agent-tools/pyproject.toml products/agent-tools/tests -q
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python products/agent-tools/packaging/generate_harness_catalog.py
```

## DoD

定向、全client回归、fresh wheel真实init、Skill资产和独立复查通过；命令/退出/数量/未测scope记status。Windows未在真实宿主验证不算绿；Runtime仍未提供。

## Current state

Linux实现完成，全products260P，隔离wheel初始化定向通过；真实本机PATH观察codex/pi，只说明文件线索。Windows实际宿主未测。

## Stages

- [x] 冻结Harness public候选目录和CLI只读边界。
- [x] 实现镜像/扫描/新报告/Skill，独立反例修复。
- [x] 全目录回归与fresh wheel隔离安装验证。
- [x] 追加最终独立复核和本机安装包使用记录至status。

## Acceptance

Linux本单所有门有实测证据可AT_013_DONE；任何实现资源缺失或明确缺陷则AT_013_PARTIAL。不把本机发现、Skill格式或本单完成当整个Agent运行产品完成；Windows保持未验证。
