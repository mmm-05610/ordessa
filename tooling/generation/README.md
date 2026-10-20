# Generation tools

`generate-harness-deployment.py BRAND <template arguments>` generates a single
brand's deployment through its public production template. It supplies the
Server's explicitly selected, captured registry to the template. No Harness is
started, credentials are not resolved, and capabilities remain declarations.

Run with the installed workspace Python environment, for example:

```sh
.venv-nightly/bin/python tooling/generation/generate-harness-deployment.py pi \
  --artifact-token pi-runtime --tree-digest sha256:<64-hex-digits> --out /tmp/pi-deployment.json
```

Available templates are `codex`, `claude-code`, `dsh`, `hermes`, `kilo`,
`opencode`, `pi`, and `qwen`. Each retains its own options and document format.
OpenCode uses `--binary-token` and `--binary-digest`; the other templates use
`--artifact-token` and `--tree-digest`. Hermes' previously broken parser named
`--artifact-source` while reading a nonexistent `artifact_token` attribute; the
current entry accepts the token required by its document contract. Paths are
bound by the operator separately, never converted into tokens by fallback.

Direct brand modules require an explicit capability callback. The generation
tool owns that application selection; libraries never discover a global
registry. Command catalog and CLI schema generation are separate tools in this
directory, with their existing frozen wire outputs.
