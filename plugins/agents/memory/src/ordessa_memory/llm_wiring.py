"""LLM wiring: resolve the extraction/embedding providers from the
model-provider catalog port (MB-4, AR-2).

The mem0 server bundles exactly three LLM providers (openai, anthropic,
gemini) and two embedders (openai, gemini) — pinned upstream facts
(``BUNDLED_LLM_PROVIDERS``/``BUNDLED_EMBEDDER_PROVIDERS`` in the pinned
``server/main.py``). This module scans the resolved provider definitions the
catalog port exposes and picks the bundled-name rows; anything else — a
custom OpenAI-compatible endpoint under a non-bundled name above all — is a
typed ``WiringUnsupported``, and the memory feature stays off. It never
stuffs a custom endpoint into ``OPENAI_API_KEY`` to impersonate ``openai``
(AR-2 failure counterexample).

The catalog arrives as the provided port object (duck-typed ``list()`` —
this package never imports ``ordessa_model_provider``); credentials travel
as references, and the key content is resolved only when the provisioner
writes the data-root ``.env``.

Pure module: no HOME, no network, no spawn, no file writes, no secret
content.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

BUNDLED_LLM_PROVIDERS = ("openai", "anthropic", "gemini")
BUNDLED_EMBEDDER_PROVIDERS = ("openai", "gemini")

#: The ``.env`` key each bundled provider's API key rides (pinned upstream
#: ``server/.env.example`` vocabulary).
ENV_KEY_NAMES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                 "gemini": "GOOGLE_API_KEY"}

MODEL_DEFAULTS = {"openai": "gpt-5-mini", "anthropic": "claude-sonnet-4-5",
                  "gemini": "gemini-2.5-flash"}


class WiringUnsupported(Exception):
    """No usable bundled provider: the honest state the feature reports
    while staying off."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProviderFacts:
    """One resolved bundled provider row (references only — never content)."""

    provider: str
    base_url: str | None
    credential_ref: str | None
    models: tuple[str, ...]


@dataclass(frozen=True)
class WiringPlan:
    """The extraction (LLM) and embedding sides; they may come from
    different bundled rows (an anthropic LLM needs an openai/gemini
    embedder — the upstream embedder vocabulary has no anthropic)."""

    llm: ProviderFacts
    embedder: ProviderFacts | None
    llm_model: str
    embedder_model: str | None


def _rows(catalog: Any) -> list[Mapping[str, Any]]:
    if catalog is None:
        return []
    items = catalog.list(include_archived=False)
    if isinstance(items, Mapping):
        items = items.get("items")
    return [row for row in (items or []) if isinstance(row, Mapping)]


def _active(row: Mapping[str, Any]) -> bool:
    return row.get("archivedAt") is None and row.get("state") != "archived"


def _provider_facts(row: Mapping[str, Any]) -> ProviderFacts:
    models = tuple(str(m.get("modelId")) for m in (row.get("models") or [])
                   if isinstance(m, Mapping) and m.get("modelId"))
    provenance = row.get("provenance") or {}
    base_url = row.get("baseUrl") or (provenance.get("baseUrl") if isinstance(provenance, Mapping) else None)
    return ProviderFacts(
        provider=str(row.get("provider")), base_url=base_url,
        credential_ref=row.get("credentialId"), models=models)


def _pick(rows: Sequence[Mapping[str, Any]], providers: Sequence[str]) -> ProviderFacts | None:
    """First active row whose provider name IS a bundled name, with a
    credential reference to bind. Provider-name equality is the bundled
    test: a custom endpoint saved under ``acme`` is not ``openai``, whatever
    its wire dialect."""
    for row in rows:
        if not _active(row):
            continue
        if row.get("provider") in providers and row.get("credentialId"):
            return _provider_facts(row)
    return None


def resolve_wiring(catalog: Any) -> WiringPlan:
    """Resolve the extraction/embedding plan from the catalog; raise
    ``WiringUnsupported`` honestly when no bundled provider is usable."""
    rows = _rows(catalog)
    llm = _pick(rows, BUNDLED_LLM_PROVIDERS)
    if llm is None:
        raise WiringUnsupported(
            "当前无可用 bundled provider（openai/anthropic/gemini 均未配置或缺少凭据引用）；"
            "记忆抽取保持关闭，不得以自定义端点冒充 bundled provider")
    embedder = llm if llm.provider in BUNDLED_EMBEDDER_PROVIDERS else None
    if embedder is None:
        embedder = _pick(rows, BUNDLED_EMBEDDER_PROVIDERS)
    if embedder is None:
        raise WiringUnsupported(
            f"LLM provider {llm.provider} 无可用 embedder（bundled embedder 仅 "
            f"{'/'.join(BUNDLED_EMBEDDER_PROVIDERS)}）；记忆抽取保持关闭")
    llm_model = llm.models[0] if llm.models else MODEL_DEFAULTS[llm.provider]
    embedder_model = (embedder.models[0] if embedder.models else None) or \
        ("text-embedding-3-small" if embedder.provider == "openai" else "gemini-embedding-001")
    return WiringPlan(llm=llm, embedder=embedder, llm_model=llm_model,
                      embedder_model=embedder_model)


def env_key_rows(plan: WiringPlan) -> dict[str, str]:
    """The ``.env`` rows the plan needs: one ENV_KEY_NAMES entry per distinct
    provider credential reference. Values here are the REFERENCE strings —
    the provisioner resolves content only at write time into the data-root."""
    rows: dict[str, str] = {}
    for facts in (plan.llm, plan.embedder):
        if facts is None or facts.credential_ref is None:
            continue
        rows[ENV_KEY_NAMES[facts.provider]] = facts.credential_ref
    return rows


def configure_payload(plan: WiringPlan) -> dict[str, Any]:
    """The ``POST /configure`` body for the plan: provider/model/base_url
    facts only — keys ride the server's own environment, never the config."""
    def provider_block(facts: ProviderFacts, model: str | None) -> dict[str, Any]:
        config: dict[str, Any] = {"model": model}
        if facts.base_url and facts.provider == "openai":
            # The pinned upstream OpenAI LLM/embedder read
            # ``config.openai_base_url`` (source-verified at the pin).
            config["openai_base_url"] = facts.base_url
        return {"provider": facts.provider, "config": config}

    payload: dict[str, Any] = {
        "llm": provider_block(plan.llm, plan.llm_model),
        "embedder": provider_block(plan.embedder, plan.embedder_model),
    }
    return payload
