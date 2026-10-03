"""EXT-6 — blocking semantics: the enforcement claim is inexpressible."""
from __future__ import annotations

import pytest

from ordessa_extensions.blocking import (
    COUNTEREXAMPLE, OBSERVATIONAL, BlockingSemanticsError, STATEMENT,
    require_observational,
)
from ordessa_extensions.capabilities import statement_for
from ordessa_extensions.definitions import HookDefinition


def test_observational_is_the_only_allowed_value():
    require_observational("observational")  # no raise
    for claim in ("blocking", "enforce", "must_pass", True, None):
        with pytest.raises(BlockingSemanticsError) as excinfo:
            require_observational(claim)
        assert excinfo.value.code == "BLOCKING_CLAIM_REFUSED"


def test_counterexample_is_the_codex_hook_face_with_citation():
    assert "Codex" in COUNTEREXAMPLE
    assert "classification.md:52" in COUNTEREXAMPLE
    assert "不阻断" in COUNTEREXAMPLE


def test_capability_table_refuses_enforcement_on_every_graded_brand():
    from ordessa_extensions.capabilities import BRAND_STATEMENTS
    for harness_id, statement in BRAND_STATEMENTS.items():
        assert statement.value("blocking_semantics") == "unsupported"


def test_projection_payload_schema_admits_only_observational():
    from ordessa_extensions.adapters.contribution import build_payload_schema
    from ordessa_harness_api import ContractError
    schema = build_payload_schema()
    hook = dict(hookId="h", event="SessionStart", matcher=None,
                actionKind="command", command=["echo"], handlerRef=None,
                timeoutSeconds=5, runAsync=False, pin="0.147.0",
                contentSha256="sha256:" + "0" * 64)
    schema.validate({"hooks": [dict(hook, semantics="observational")],
                     "runtimeGeneration": "g", "projectId": "p"})
    with pytest.raises(ContractError):
        schema.validate({"hooks": [dict(hook, semantics="blocking")],
                         "runtimeGeneration": "g", "projectId": "p"})


def test_statement_documented_for_the_report():
    assert "no block/enforce guarantee" in STATEMENT


def test_definition_model_keeps_async_honest():
    # async hooks exist in the model (EXT-2) — but async-ness must never
    # read as a stronger guarantee; the model carries it as plain data.
    definition = HookDefinition(
        hook_id="async-one", event="PreToolUse", action_kind="command",
        command=("logger", "pre"), handler_ref=None, timeout_seconds=5,
        run_async=True, pin="0.147.0",
        content_sha256="sha256:" + "33" * 32)
    assert definition.run_async is True
    assert definition.payload()["runAsync"] is True
