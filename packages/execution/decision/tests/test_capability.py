"""`decisions` capability against the frozen F1 contracts (offline)."""
import asyncio

import pytest

from ordessa_interfaces_contracts import (
    Capability, OperationResult, validate_capability)

from ordessa_decision import DecisionRunner, FilesystemEvidenceStore, RulesOutcome
from ordessa_decision.capability import build_capability as original_build_capability, factory
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.settings import DecisionsSettings


class Engine:
    engine_id = "fake"

    def validate(self, payload):
        pass

    def evaluate(self, payload, facts):
        return RulesOutcome(values={"double": facts["input"]["n"] * 2},
                            disposition="passed")

    def close(self):
        pass


class Context:
    def __init__(self,request_id='req-1'):self.request_id=request_id
    principal = {"id": "worker"}
    request_id = "req-1"
    deadline = None


def build_capability(settings):
    # Explicit controlled external authority; JSON principal alone is not trusted.
    return original_build_capability(settings,invocation_resolver=lambda context:context,
        evidence_scope_resolver=lambda invocation,operation:EvidenceScope('principal','worker'))


def settings(tmp_path):
    return DecisionsSettings(
        runner_factory=lambda **kwargs: DecisionRunner(host_limits=None, **kwargs),
        evidence=FilesystemEvidenceStore(tmp_path / "evidence"),
        default_engine=Engine())


def job(**overrides):
    value = {"spec_version": "decision-job/1", "job_id": "cap-job", "version": 1,
             "input": {"n": 2},
             "limits": {"max_model_calls": 0, "max_steps": 2,
                        "max_value_bytes": 1024, "timeout_seconds": 2.0},
             "steps": [{"id": "rules", "type": "rules", "engine": None,
                        "when": {"fact": "input.n", "op": "gte", "value": 1},
                        "payload": {"values": {"double": "input.n * 2"}}}],
             "result": {"from": "rules", "path": ["values", "double"]}}
    value.update(overrides)
    return value


def test_capability_matches_the_contract_and_factory_builds_it(tmp_path):
    capability = build_capability(settings(tmp_path))
    assert type(capability) is Capability
    assert validate_capability(capability).id == "decisions"
    assert set(capability.handlers) == {f"decisions.{name}" for name in
                                        ("validate", "run", "get", "evidence", "query")}
    built = factory.build({"services": {"decisions": settings(tmp_path)}})
    assert built.descriptor.descriptor_digest == capability.descriptor.descriptor_digest


def test_validate_and_run_are_async_operations(tmp_path):
    capability = build_capability(settings(tmp_path))
    validated = asyncio.run(capability.handlers["decisions.validate"]({"job": job()}, Context()))
    assert validated.status == "completed" and validated.data["job_id"] == "cap-job"
    refused = asyncio.run(capability.handlers["decisions.validate"]({"job": {}}, Context()))
    assert refused.status == "refused"
    assert refused.error.code == "INVALID_INPUT"
    ran = asyncio.run(capability.handlers["decisions.run"]({"job": job()}, Context()))
    assert type(ran) is OperationResult and ran.status == "completed"
    assert ran.data["result"] == 4
    assert ran.data["evidence"]["durability"] == "durable"
    digest = ran.data["evidence"]["digest"]
    assert ran.evidence_refs == ("sha256:" + digest,)
    got = asyncio.run(capability.handlers["decisions.get"]({"digest": digest}, Context()))
    assert got.status == "completed" and got.data["summary"]["result_digest"]


def test_dry_run_with_an_ask_step_is_unsupported_not_silently_run(tmp_path):
    capability = build_capability(settings(tmp_path))
    ask = job(steps=[{"id": "ask", "type": "ask", "engine": None, "when": {"fact": "input.n", "op": "gte", "value": 0},
                      "payload": {"question": {"kind": "choice", "text": "Pick",
                                                      "options": {"a": "A", "b": "B"}}}}],
              result={"from": "ask", "path": ["answer"]},
              limits={"max_model_calls": 1, "max_steps": 2,
                      "max_value_bytes": 1024, "timeout_seconds": 2.0})
    result = asyncio.run(capability.handlers["decisions.run"](
        {"job": ask, "dry_run": True}, Context()))
    assert result.status == "refused"
    assert result.error.code == "CAPABILITY_UNSUPPORTED"


def test_unknown_outcome_persists_its_evidence(tmp_path):
    class Boom:
        binding_ref = "boom/1"
        settings_digest = "sha256:" + "b" * 64

        async def decide(self, question, context):
            context.claim(question, self.settings_digest)
            raise TimeoutError("bounded")

    settings_ = DecisionsSettings(
        runner_factory=lambda **kwargs: DecisionRunner(host_limits=None, **kwargs),
        evidence=FilesystemEvidenceStore(tmp_path / "evidence"),
        provider=Boom())
    capability = build_capability(settings_)
    result = asyncio.run(capability.handlers["decisions.run"](
        {"job": job(steps=[{"id": "ask", "type": "ask", "engine": None,
                            "when": {"fact": "input.n", "op": "gte", "value": 0},
                            "payload": {"question": {"kind": "choice", "text": "Pick",
                                                     "options": {"a": "A", "b": "B"}}}}],
                    result={"from": "ask", "path": ["answer"]},
                    limits={"max_model_calls": 1, "max_steps": 2,
                            "max_value_bytes": 1024, "timeout_seconds": 2.0})}, Context()))
    assert result.status == "unknown"
    assert result.error.code == "EFFECT_UNKNOWN"
    digest = result.evidence_refs[0].removeprefix("sha256:")
    stored = asyncio.run(capability.handlers["decisions.get"]({"digest": digest}, Context()))
    assert stored.status == "completed"


def test_capability_get_reads_across_processes(tmp_path):
    import subprocess
    import sys

    capability = build_capability(settings(tmp_path))
    ran = asyncio.run(capability.handlers["decisions.run"]({"job": job()}, Context()))
    digest = ran.data["evidence"]["digest"]
    code = ("from ordessa_decision import FilesystemEvidenceStore; from ordessa_decision.evidence import EvidenceScope; "
            f"print(FilesystemEvidenceStore({str(tmp_path / 'evidence')!r}).scoped(EvidenceScope('principal','worker')).get({digest!r})['job_digest'])")
    finished = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert finished.returncode == 0, finished.stderr
    assert len(finished.stdout.strip()) == 64


def test_concurrent_runs_share_the_store_without_interference(tmp_path):
    settings_ = settings(tmp_path)
    capability = build_capability(settings_)

    async def run_many():
        return await asyncio.gather(*[
            capability.handlers["decisions.run"](
                {"job": job(job_id=f"cap-job-{index}")}, Context(f'req-{index}'))
            for index in range(6)])

    results = asyncio.run(run_many())
    assert all(item.status == "completed" for item in results)
    digests = {item.data["evidence"]["digest"] for item in results}
    assert len(digests) == 6
    files = sorted(p.name for p in settings_.evidence.scoped(EvidenceScope('principal','worker')).root.iterdir() if not p.name.startswith('.'))
    assert files == sorted(digest + ".json" for digest in digests)


def test_query_reads_the_original_run_without_claiming_or_executing(tmp_path):
    from ordessa_decision.definitions.values import digest_hex, job_document_bound
    from ordessa_decision.job import validate_job

    evaluations = []
    class CountingEngine(Engine):
        def evaluate(self, payload, facts):
            evaluations.append(dict(facts))
            return super().evaluate(payload, facts)

    configured = DecisionsSettings(
        runner_factory=lambda **kwargs: DecisionRunner(host_limits=None, **kwargs),
        evidence=FilesystemEvidenceStore(tmp_path / "evidence"),
        default_engine=CountingEngine())
    capability = build_capability(configured)
    ran = asyncio.run(capability.handlers["decisions.run"](
        {"job": job()}, Context('orig-run')))
    assert ran.status == "completed" and len(evaluations) == 1

    queried = asyncio.run(capability.handlers["decisions.query"](
        {"originalRequestId": "orig-run", "job": job()}, Context('query-read')))
    assert queried.status == "completed" and queried.data == ran.data
    assert queried.operation_ref == ran.operation_ref
    assert len(evaluations) == 1  # the read never executes the job

    conflict = asyncio.run(capability.handlers["decisions.query"](
        {"originalRequestId": "orig-run", "job": job(input={"n": 3})}, Context('query-other')))
    assert conflict.status == "refused" and conflict.error.code == "CONFLICT"
    missing = asyncio.run(capability.handlers["decisions.query"](
        {"originalRequestId": "never-ran", "job": job()}, Context('query-missing')))
    assert missing.status == "refused" and missing.error.code == "INVALID_INPUT"

    raw = validate_job(job()).raw
    request_digest = digest_hex({"job": raw, "dryRun": False},
                                maximum=job_document_bound(None))
    store = configured.evidence.scoped(EvidenceScope("principal", "worker"))
    created, operation, recorded = store.claim_run("pending-run", request_digest)
    assert created is True and recorded is None
    pending = asyncio.run(capability.handlers["decisions.query"](
        {"originalRequestId": "pending-run", "job": job()}, Context('query-pending')))
    assert pending.status == "accepted" and pending.data == {"state": "pending"}
    assert pending.operation_ref == operation
    assert store.read_run("pending-run", request_digest)[1] is None
