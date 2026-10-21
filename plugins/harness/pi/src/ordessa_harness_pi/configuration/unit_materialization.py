"""Fixed Pi Profile catalogue materialization through the caller's bound Use.

This writes initial native files, not runtime configuration confirmation. It
neither selects a model by a guessed settings dialect nor binds credentials.
The Unit owner must supply its already admitted prepare invocation and fixed
Profile snapshot; this module cannot authenticate facts or grant access.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
import math
import posixpath
import re

from ordessa_agents.preparation import PreparedAgent, ConfigurationResources
from ordessa_agents.profiles import decode_revision, encode_revision_ref, ProfileRevisionRef
from ordessa_agents.harness.definitions.model_compilation import RequestParams
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_harness_pi.acp_model_facts import render_pi_provider, translate_protocol
from .initial import initial_model_params


class PiProfileMaterializationRefused(ValueError):
    """Fixed Profile cannot be faithfully rendered by this narrow Pi port."""


def _refuse():
    # Never include payload/secret/provider exception text in diagnostics.
    raise PiProfileMaterializationRefused("Fixed Pi Profile materialization unavailable")


_NATIVE_MODEL_FIELDS = frozenset({
    "id", "name", "provider", "api", "baseUrl", "reasoning", "thinkingLevelMap",
    "input", "cost", "promptCache", "contextWindow", "maxTokens", "samplingParams",
    "headers", "compat",
})


def _native_model_definition(value, *, provider, model, endpoint, api):
    """Validate one complete Pi 0.86.1 Model row against the fixed Profile.

    ``provider`` is part of the public Pi Model object but not the nested
    ``models.json`` row. It binds the supplied real model facts to the exact
    selected Profile; it is removed only when writing that provider's row.
    """
    if not isinstance(value, Mapping) or set(value) - _NATIVE_MODEL_FIELDS:
        _refuse()
    required = {"id", "name", "provider", "api", "baseUrl", "reasoning", "input",
                "cost", "contextWindow", "maxTokens"}
    if not required <= set(value):
        _refuse()
    if (value["id"] != model or value["provider"] != provider or value["api"] != api
            or value["baseUrl"] != endpoint):
        _refuse()
    for key in ("id", "name", "provider", "api", "baseUrl"):
        item = value[key]
        if (type(item) is not str or not item or item.strip() != item
                or any(ord(char) < 32 or ord(char) == 127 for char in item)):
            _refuse()
    if type(value["reasoning"]) is not bool:
        _refuse()
    inputs = value["input"]
    if (not isinstance(inputs, (list, tuple)) or not inputs or "text" not in inputs
            or any(item not in ("text", "image") for item in inputs)
            or len(set(inputs)) != len(inputs)):
        _refuse()
    for key in ("contextWindow", "maxTokens"):
        if type(value[key]) is not int or value[key] <= 0:
            _refuse()
    cost = value["cost"]
    if not isinstance(cost, Mapping) or set(cost) - {"input", "output", "cacheRead", "cacheWrite", "tiers"}:
        _refuse()
    if not {"input", "output", "cacheRead", "cacheWrite"} <= set(cost):
        _refuse()
    for key in ("input", "output", "cacheRead", "cacheWrite"):
        amount = cost[key]
        if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
            _refuse()
    if "tiers" in cost:
        tiers = cost["tiers"]
        if not isinstance(tiers, (list, tuple)):
            _refuse()
        for tier in tiers:
            if (not isinstance(tier, Mapping)
                    or set(tier) != {"input", "output", "cacheRead", "cacheWrite", "inputTokensAbove"}):
                _refuse()
            for amount in tier.values():
                if type(amount) not in (int, float) or not math.isfinite(amount) or amount < 0:
                    _refuse()
    if "thinkingLevelMap" in value:
        levels = value["thinkingLevelMap"]
        if (not isinstance(levels, Mapping)
                or set(levels) - {"off", "minimal", "low", "medium", "high", "xhigh", "max"}
                or any(item is not None and type(item) is not str for item in levels.values())):
            _refuse()
    if "promptCache" in value:
        cache = value["promptCache"]
        if (not isinstance(cache, Mapping) or set(cache) - {"short", "long"}
                or any(type(item) not in (int, float) or not math.isfinite(item) or item < 0
                       for item in cache.values())):
            _refuse()
    for key in ("samplingParams", "compat"):
        if key in value and not isinstance(value[key], Mapping):
            _refuse()
    # Provider/model-specific headers could carry credentials. This bounded
    # process capability supplies auth at spawn, so native model rows cannot.
    if value.get("headers") not in (None, {}):
        _refuse()
    try:
        row = json.loads(safe_json({key: value[key] for key in value if key != "provider"}))
    except Exception:
        _refuse()
    return row


class PiUnitProfileMaterializer:
    """One explicit model declaration and externally supplied model catalogue.

    Catalogue IDs validate selection; they are not native model definitions.
    Native provider/model declarations stay owned by the selected Pi version.
    Initial ``requestParams.retry`` is projected through the pinned Pi settings
    file shape; every other request-parameter family remains unsupported here.
    credential_environment_variable is an optional name only; its value is never
    read. Secret references and unowned declarations remain unsupported here.
    The returned applied fact proves matching file readback only, never live
    Pi/native model selection or authentication.
    """
    def __init__(self, *, fixed_revision, harness_definition_ref, model_declaration_id, model_catalogue,
                 credential_environment_variable=None, native_model_definition=None):
        if type(fixed_revision) is not ProfileRevisionRef:
            _refuse()
        if not isinstance(model_declaration_id, str) or not model_declaration_id:
            _refuse()
        if not isinstance(model_catalogue, (tuple, list)):
            _refuse()
        if credential_environment_variable is not None and (
                not isinstance(credential_environment_variable, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", credential_environment_variable) is None):
            _refuse()
        if not isinstance(harness_definition_ref, Mapping):
            _refuse()
        self.harness_definition_ref = json.loads(safe_json(harness_definition_ref))
        self.fixed_revision = fixed_revision
        self.model_declaration_id = model_declaration_id
        self.model_catalogue = tuple(model_catalogue)
        self.credential_environment_variable = credential_environment_variable
        try:
            self.native_model_definition = (None if native_model_definition is None else
                json.loads(safe_json(native_model_definition)))
        except Exception:
            _refuse()

    def _selected(self, snapshot):
        if not isinstance(snapshot, Mapping) or set(snapshot) != {"ref", "manifest"}:
            _refuse()
        try:
            ref = json.loads(safe_json(snapshot["ref"]))
            manifest = json.loads(safe_json(snapshot["manifest"]))
            revision = decode_revision({"ref": ref, "content": manifest})
            if (revision.ref != self.fixed_revision
                    or manifest["schemaVersion"] != "1"
                    or manifest["harnessDefinitionRef"] != self.harness_definition_ref):
                _refuse()
            declarations = manifest["declarations"]
            if len(declarations) != 1:
                _refuse()
            declaration = declarations[0]
            if (declaration["declarationId"] != self.model_declaration_id
                    or declaration["configurationKind"] != "assets.model-provider"
                    or declaration["schemaVersion"] != "1"
                    or declaration["action"] != "value" or declaration.get("resourceRefs")):
                _refuse()
            payload = declaration["payload"]
            if (not isinstance(payload, dict)
                    or set(payload) - {"provider", "model", "endpoint", "protocol", "credentialRef", "authentication", "brandFields", "requestParams"}
                    or payload.get("credentialRef") is not None):
                _refuse()
            request_params = RequestParams.from_record(payload.get("requestParams"))
            if (request_params.reasoning_effort is not None
                    or request_params.max_tokens is not None
                    or request_params.timeout_ms is not None):
                _refuse()
            retry_settings = None
            if request_params.retry is not None:
                retry = request_params.retry
                retry_settings = {
                    "enabled": retry["enabled"],
                    "maxRetries": retry["maxRetries"],
                    "provider": {
                        "maxRetries": retry["provider"]["maxRetries"],
                        "maxRetryDelayMs": retry["provider"]["maxRetryDelayMs"],
                    },
                }
            initial_payload = dict(payload)
            initial_payload.pop("requestParams", None)
            params = initial_model_params(initial_payload, None, models=list(self.model_catalogue))
            native_definition = None
            if self.native_model_definition is not None:
                _, api = translate_protocol("pi", payload["protocol"])
                native_definition = _native_model_definition(self.native_model_definition,
                    provider=payload["provider"], model=params["model"],
                    endpoint=params["provider"]["baseUrl"], api=api)
            return payload, params, native_definition, retry_settings
        except PiProfileMaterializationRefused:
            raise
        except Exception:
            _refuse()

    def selected_launch_configuration(self, snapshot):
        """Pure provider/model selection from the exact same fixed declaration.

        No thinking default is invented: the current initial dialect has no
        supported thinking payload. The caller binds this result into its own
        immutable launch plan; this function neither starts nor authenticates.
        """
        payload, params, _, _ = self._selected(snapshot)
        return {"provider": payload["provider"], "model": params["model"]}

    def __call__(self, agent, use, invocation_facts, snapshot):
        if (type(agent) is not PreparedAgent or agent.harness.harness_id != "pi"
                or agent.harness.resources.kind != "pi-agent-dir"
                or agent.harness.resources.applied is not False
                or not isinstance(invocation_facts, Mapping)
                or invocation_facts.get("action") != "prepare"
                or invocation_facts.get("query") is not False
                or agent.profile_revision != safe_json(encode_revision_ref(self.fixed_revision))):
            _refuse()
        payload, params, native_definition, retry_settings = self._selected(snapshot)
        try:
            # Both rendering and actual startup must bind the same declaration.
            # A correctly written catalogue cannot excuse a different/default
            # model passed to the native process.
            argv = agent.harness.launch_spec.argv
            for flag, expected in (('--pi-provider', payload['provider']), ('--pi-model', params['model'])):
                if argv.count(flag) != 1:
                    _refuse()
                index = argv.index(flag)
                if index + 1 >= len(argv) or argv[index + 1] != expected:
                    _refuse()
            provider = render_pi_provider(provider=payload["provider"],
                base_url=params["provider"]["baseUrl"], protocol=payload["protocol"])
            # Existing renderer historically chooses one environment key. Never
            # inherit that choice implicitly for a different Profile/provider.
            provider.pop("apiKey", None)
            if self.credential_environment_variable is not None:
                provider["apiKey"] = "$" + self.credential_environment_variable
            # The default route keeps Pi's catalogue. Only a caller supplying a
            # complete native Model definition bound to the exact Profile may
            # add a model row; selection IDs alone never invent model facts.
            if native_definition is not None:
                provider["models"] = [native_definition]
            content = json.dumps({"providers": {payload["provider"]: provider}},
                                 sort_keys=True, indent=2, allow_nan=False) + "\n"
            files = use.files
            root = files.root()
            location = agent.harness.resources.location
            if (not isinstance(root, str) or not posixpath.isabs(root)
                    or not isinstance(location, str) or not posixpath.isabs(location)
                    or posixpath.normpath(root) != root or posixpath.normpath(location) != location
                    or location == root or not location.startswith(root.rstrip("/") + "/")
                    or agent.harness.launch_spec.env.get("PI_CODING_AGENT_DIR") != location):
                _refuse()
            relative = posixpath.relpath(location, root)
            if files.path(relative) != location:
                _refuse()
            settings_target = posixpath.join(relative, "settings.json")
            if retry_settings is not None and files.exists(settings_target):
                # Never merge with or replace an existing instance's Pi
                # settings. This Unit's initial declaration has no authority
                # over pre-existing configuration in the same private area.
                _refuse()
        except PiProfileMaterializationRefused:
            raise
        except Exception:
            _refuse()
        # Effects use only this bound Use FileArea. Any exception or lost reply
        # propagates without retry; original Unit prepare retains its own hold.
        if files.ensure(relative) != location:
            _refuse()
        target = posixpath.join(relative, "models.json")
        files.write_text(target, content)
        if files.read_text(target) != content:
            _refuse()
        if retry_settings is not None:
            settings_content = json.dumps({"retry": retry_settings}, sort_keys=True,
                                          indent=2, allow_nan=False) + "\n"
            files.write_text(settings_target, settings_content)
            if files.read_text(settings_target) != settings_content:
                _refuse()
        return ConfigurationResources(agent.harness.resources.kind, location, True)
