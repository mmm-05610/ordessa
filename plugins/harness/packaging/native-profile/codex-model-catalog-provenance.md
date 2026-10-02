# Native model catalogue, Codex 0.147.0

`codex-model-catalog.mjs` is Ordessa-owned translation and instance-file handling.
It targets `ModelsResponse`/`ModelInfo` in the pinned upstream release:
https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/protocol/src/openai_models.rs

`codex-generic-prompt.md` is copied unchanged from the release's generic fallback
instruction template, not from any particular model's catalogue entry:
https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/models-manager/prompt.md

SHA-256: `ac8ae107a0d72fe3476b430afb161ea4e67da2e446d778aefc44828160559807`.
The upstream Apache-2.0 LICENSE and NOTICE are adjacent and shipped in the enhanced
asset. No upstream model capability entries are copied or renamed.

Reasoning levels, input modalities and context size come exclusively from the
selected model-provider record. Missing reasoning facts refuse catalogue
generation. Context size is omitted if unknown. Catalogue defaults choose medium
only if advertised, otherwise the first advertised effort; explicit preserved
preferences still must be accepted by the new native owner.

Ordessa selects conservative native execution policy (serial function calls,
no provider-specific verbosity/summary/search/lite features). These are adapter
choices, not claims about maximum backend abilities. Codex retains its normal
native defaults for unspecified fields. No global config.toml is written.

Upgrade: review the new release's schema and generic prompt, update the upstream
source digest, retain notices, rebuild the immutable asset, and rerun compiler,
native `debug models`, initial preparation, same-session restoration and
preference-preservation checks. Unit tests do not prove gateway inference.
