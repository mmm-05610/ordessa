# ordessa（元包）

一条命令装全默认产品：Server、唯一 CLI、agents（含品牌 provider）、environments（含 OpenShell）、decision（含 Jev）。

```bash
pip install ordessa
```

它不含任何代码，只声明下层闭包；`pip install ordessa[upper]` 才会带上退役中的上层装配
（Units / Engineering / system-access-bindings），见 `docs/migration/server-lower-closure-20261020.md`。
