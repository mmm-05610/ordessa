# profile-contribution — Model Provider ⇄ Profile 可选 glue

迁移自 `plugins/model-provider/profile-contribution` @ `9305563719d25e04076b9221a7284660bd8f8642`
（逐字保真，依赖方向单向：只依赖核心包端口协议）。本线增量：

- `facet_registration.py`：`assets.model-provider` facet 的 typed 描述与原子 choice 值校验
  （MP-01：provider/model 永不拆两项；profile Harness 绑定不变；敏感材料不做 facet 值）。
  注册载荷形状对齐 profile-v2 目标契约；**实际 `addEditor`/`addSettingsSection` 注册属 Z1 的
  profile-api**（REQ-Z3-3，OPEN）——本包不私建注册表。

验证：`.venv/bin/python -m pytest plugins/assets/model-provider/profile-contribution -q` →
13 passed（7 迁移 + 6 增量；增量先红：模块缺席 1 collection error，后绿）。
