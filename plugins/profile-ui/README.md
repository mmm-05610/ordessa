# ordessa-profile

Profile 插件族（`specs/001-profile/`）：为一个 Harness 保存可复用配置；
配置面（facet）由能力插件贡献；会话内覆盖与同 Harness 会话切换。

- 依赖：仅 `pacthold`（治理内核/插件 SDK）。禁止 import 宿主内部
  （`ordessa_server*`、`ordessa_harness`）或兄弟插件——
  `tests/boundary_check.sh` 是门禁。
- 存储：插件私有 SQLite（`profile_schema` 账本，v1）。
- 入口：`agent_box.plugins` group 的 `profile` entry point；
  共享宿主装配属串行集成波次（plan §8）。

```sh
pip install -e plugins/profile
python -m pytest plugins/profile/tests -q
```
