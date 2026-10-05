"""Readonly old Pi pure compiler counterexamples; no native/model effect."""
import json
from ordessa_harness.pi.configuration.model import PiAdapter
from ordessa_harness_api.model_compilation import AdapterContext, TargetHandle, ChoiceRequest, RequestParams, CompileIntent
adapter = PiAdapter()
context = AdapterContext(TargetHandle("pi", "instance", "fixture"), "0.5.1", {"native_session_id": "original-session"})
retry = RequestParams.from_record({"retry": {"enabled": True, "maxRetries": 3,
    "provider": {"maxRetries": 2, "maxRetryDelayMs": 1000}}})
before = {"providers": {"acme": {"baseUrl": "https://fixture.test", "api": "openai-completions",
    "models": [{"id": "desired", "maxTokens": 4096}, {"id": "sibling", "maxTokens": 2048}]}}}
request = ChoiceRequest("fixture", "desired", "https://fixture.test", "openai-chat", "ref://fixture",
    "acme", {"provider_in_instance": True}, retry)
plan = adapter.compile(context, before, request)
fields = [list(x.field_path) for x in plan.intents if isinstance(x, CompileIntent)]
providers = [x.typed_value for x in plan.intents if isinstance(x, CompileIntent) and x.field_path == ("providers", "acme")]
unknown_context = AdapterContext(TargetHandle("pi", "instance", "fixture"), "0.5.1", {})
verdict = adapter.verify(unknown_context, {"readback": {}})
checks = {"retry_only_does_not_replace_provider_subtree": not providers,
    "restart_plan_keeps_desired_model": ["session", "model"] in fields,
    "missing_model_and_session_not_match": verdict.verdict != "match"}
print(json.dumps({"checks": checks, "intentFields": fields, "providerObjects": providers,
    "emptyReadbackVerdict": verdict.verdict}, indent=2))
assert all(checks.values()), "Pi pre-migration contract counterexamples"
