"""Jev SDK 0.7.2 adapter; no task-controlled connection options or retries."""
import asyncio
from contextvars import ContextVar
import logging
import math
import time
from dataclasses import dataclass
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

import httpx2
from pydantic import Field
from typesafe_sdk import (
    AsyncTypeSafeClient, Choice, Score, Noul, RetryPolicy, SystemOneResponse,
    Usage, TypeSafeAuthenticationError, TypeSafePermissionDeniedError,
    TypeSafeAPIResponseValidationError, TypeSafeError, __version__,
)
from decision_runtime.definitions.values import canonical, decode, digest, plain, name
from decision_runtime.definitions.models import DecisionQuestion, DecisionAnswer
from decision_runtime.definitions.ports import ModelCallContext

PROTOCOL_VERSION = 'jev-protocol/1'
TOLERANCE = 1e-6
_SDK_CALL = ContextVar('ordessa_jev_sdk_call', default=False)


PROTOCOL_DIAGNOSTICS = frozenset({'unspecified', 'sdk_response_schema', 'response_decode',
    'response_fields', 'model_identity', 'answer_set', 'answer_kind', 'number_invalid',
    'probability_keys', 'probability_sum', 'choice_not_maximum', 'score_legend',
    'score_expected_value', 'usage_invalid'})


class JevProviderError(RuntimeError):
    """Only a bounded code crosses the provider boundary; never an SDK body."""
    def __init__(self, code, *, diagnostic='unspecified'):
        self.code = code
        self.diagnostic = diagnostic if isinstance(diagnostic, str) and diagnostic in PROTOCOL_DIAGNOSTICS else 'unspecified'
        super().__init__(code)


class _NoSDKPayloads(logging.Filter):
    def filter(self, record):
        return not _SDK_CALL.get()


class _Response(SystemOneResponse):
    # Supported public custom response model, preserving absent token evidence.
    usage: Usage = Field(default_factory=Usage)


@dataclass(frozen=True)
class JevProviderSettings:
    binding_ref: str = 'jev-official/1'
    secret_ref: str = 'jev-api-key'
    base_url: str = 'https://api.typesafe.ai'
    model: str = 'jev-1.13.0'
    accepted_response_models: tuple[str, ...] = ()
    timeout_seconds: float = 10.0
    protocol_validation_version: str = PROTOCOL_VERSION

    def __post_init__(self):
        name(self.binding_ref); name(self.secret_ref); name(self.model)
        if not isinstance(self.accepted_response_models, (tuple,list)):
            raise JevProviderError('settings_invalid')
        accepted = tuple(self.accepted_response_models) or (self.model,)
        for model_id in accepted: name(model_id)
        if len(accepted)>16 or len(set(accepted))!=len(accepted):
            raise JevProviderError('settings_invalid')
        object.__setattr__(self,'accepted_response_models',accepted)
        url = urlsplit(self.base_url)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.query or url.fragment):
            raise JevProviderError('settings_invalid')
        if (self.protocol_validation_version != PROTOCOL_VERSION
                or type(self.timeout_seconds) not in (int, float)
                or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0):
            raise JevProviderError('settings_invalid')

    @property
    def settings_digest(self):
        return digest('descriptor', {'kind': 'jev_provider_settings', **plain(self)})


def _number(value, minimum=0, maximum=1):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise JevProviderError('protocol_invalid', diagnostic='number_invalid')
    return float(value)


def _probabilities(raw, keys):
    if not isinstance(raw, Mapping) or set(raw) != set(keys):
        raise JevProviderError('protocol_invalid', diagnostic='probability_keys')
    values = {k: _number(v) for k, v in raw.items()}
    if abs(math.fsum(values.values()) - 1) > TOLERANCE:
        raise JevProviderError('protocol_invalid', diagnostic='probability_sum')
    return values


class JevDecisionProvider:
    """Owns one dedicated SDK client. Cancelled runs never close this resource.

    ``transport`` is a host-only injection seam, owned and closed by this client.
    ``http_client`` permits a host-configured HTTP client (for example, a
    diagnostic subclass retaining httpx2's normal trust_env proxy/CA behavior).
    Ownership transfers to the SDK client and is closed with this provider. The
    two seams are mutually exclusive; neither changes provider policy.
    The SDK's named logger is filtered only within this adapter's async call
    context to prevent raw body logging. Unrelated SDK users retain their logs.
    Safe call evidence belongs to the runtime, not SDK debug logging.
    """
    def __init__(self, settings: JevProviderSettings, *, secret_resolver: Callable[[str], str],
                 transport: httpx2.AsyncBaseTransport | None = None,
                 http_client: httpx2.AsyncClient | None = None):
        if not isinstance(settings, JevProviderSettings) or not callable(secret_resolver):
            raise JevProviderError('settings_invalid')
        if (transport is not None and http_client is not None
                or http_client is not None and not isinstance(http_client, httpx2.AsyncClient)):
            raise JevProviderError('settings_invalid')
        if __version__ != '0.7.2':
            raise JevProviderError('sdk_version_unsupported')
        logger = logging.getLogger('typesafe_sdk')
        if not any(isinstance(f, _NoSDKPayloads) for f in logger.filters):
            logger.addFilter(_NoSDKPayloads())
        self._settings = settings
        self.settings_digest = settings.settings_digest
        self.binding_ref = settings.binding_ref
        self._closed = False
        self._close_lock = asyncio.Lock()
        failure = False
        try:
            key = secret_resolver(settings.secret_ref)
            if not isinstance(key, str) or not key.strip():
                raise ValueError()
            self._client = AsyncTypeSafeClient(
                api_key=key, model=settings.model, base_url=settings.base_url,
                retry=RetryPolicy(max_retries=0), timeout=settings.timeout_seconds,
                transport=transport, http_client=http_client,
            )
        except Exception:
            failure = True
        if failure:
            raise JevProviderError('client_configuration_failed')

    def __repr__(self):
        return '<JevDecisionProvider>'

    async def decide(self, question: DecisionQuestion, model_context: ModelCallContext):
        if self._closed:
            raise JevProviderError('provider_closed')
        if not isinstance(question, DecisionQuestion) or not isinstance(model_context, ModelCallContext):
            raise JevProviderError('call_refused')
        # Both the context metadata and the independently bound opaque permit must agree.
        if (model_context.question_digest != question.question_digest
                or model_context.provider_settings_digest != self.settings_digest
                or not math.isfinite(model_context.monotonic_deadline)):
            raise JevProviderError('call_refused')
        mapping_failed = False
        try:
            q = self._map_question(question)
        except Exception:
            mapping_failed = True
        if mapping_failed:
            raise JevProviderError('policy_invalid')
        state = plain(question.bounded_state)
        remaining = model_context.monotonic_deadline - time.monotonic()
        if remaining <= 0:
            raise JevProviderError('call_refused')
        timeout = min(remaining, self._settings.timeout_seconds)
        failure = None; diagnostic = 'unspecified'
        try:
            model_context.claim(question, self.settings_digest)
        except Exception:
            failure = 'call_refused'
        if failure:
            raise JevProviderError(failure)
        # No intervening await between the single permit claim and entering the SDK.
        log_token = _SDK_CALL.set(True)
        try:
            response = await asyncio.wait_for(
                self._client.system_one(
                    state=state, questions={question.question_id: q},
                    timeout=timeout, response_model=_Response,
                ),
                timeout=remaining,
            )
        except asyncio.CancelledError:
            raise
        except (TypeSafeAuthenticationError, TypeSafePermissionDeniedError):
            failure = 'authentication_failed'
        except TypeSafeAPIResponseValidationError:
            failure = 'protocol_invalid'; diagnostic = 'sdk_response_schema'
        except asyncio.TimeoutError:
            failure = 'provider_timeout'
        except TypeSafeError:
            failure = 'provider_failed'
        except Exception:
            failure = 'provider_failed'
        finally:
            _SDK_CALL.reset(log_token)
        if failure:
            # Raised outside except: no sensitive SDK exception context escapes.
            raise JevProviderError(failure, diagnostic=diagnostic)
        try:
            return self._map_response(question, response)
        except JevProviderError as error:
            diagnostic = error.diagnostic
        except Exception:
            diagnostic = 'response_fields'
        raise JevProviderError('protocol_invalid', diagnostic=diagnostic)

    @staticmethod
    def _map_question(question):
        if question.kind == 'choice':
            ids = set(question.options)
            business = ids - {'none_suitable', 'insufficient_evidence'}
            if not 2 <= len(ids) <= 66 or len(business) > 64:
                raise JevProviderError('policy_invalid')
            if question.allowed_answer_ids and set(question.allowed_answer_ids) != ids:
                raise JevProviderError('policy_invalid')
            return Choice(instructions=question.question_text, criteria=plain(question.options))
        if question.kind == 'score':
            if not 2 <= len(question.scale) <= 10:
                raise JevProviderError('policy_invalid')
            return Score(instructions=question.question_text, criteria=plain(question.scale))
        return Noul(instructions=question.question_text)

    def _map_response(self, question, response):
        # Public raw response preserves unknown kinds the SDK otherwise drops.
        try:
            raw = decode(response.raw_http_response.content)
        except Exception:
            raise JevProviderError('protocol_invalid', diagnostic='response_decode') from None
        if not isinstance(raw, Mapping):
            raise JevProviderError('protocol_invalid', diagnostic='response_fields')
        if (raw.get('model') not in self._settings.accepted_response_models
                or response.model != raw.get('model')):
            raise JevProviderError('protocol_invalid', diagnostic='model_identity')
        if (not isinstance(raw.get('answers'), Mapping)
                or set(raw['answers']) != {question.question_id}
                or set(response.answers) != {question.question_id}):
            raise JevProviderError('protocol_invalid', diagnostic='answer_set')
        answer = raw['answers'][question.question_id]
        if not isinstance(answer, Mapping) or answer.get('type') != question.kind:
            raise JevProviderError('protocol_invalid', diagnostic='answer_kind')
        receipt = {'resolved_model': response.model,
                   'requested_model': self._settings.model,
                   'protocol_validation_version': PROTOCOL_VERSION,
                   'question_digest': question.question_digest,
                   'provider_settings_digest': self.settings_digest}
        if question.kind == 'noul':
            value = _number(answer['noul'])
        elif question.kind == 'choice':
            probabilities = _probabilities(answer['probabilities'], question.options)
            choice = answer['choice']
            best = max(probabilities.values())
            winners = sorted(k for k, v in probabilities.items() if v == best)
            if choice not in winners:
                raise JevProviderError('protocol_invalid', diagnostic='choice_not_maximum')
            receipt.update(probabilities=probabilities, confidence=_number(answer['confidence']),
                           selection_status='unique' if len(winners) == 1 else 'tie',
                           tied_option_ids=winners if len(winners) > 1 else [])
            value = choice if len(winners) == 1 else None
        else:
            keys = [str(i) for i in range(len(question.scale))]
            probabilities = _probabilities(answer['probabilities'], keys)
            legend = answer['legend']
            if not isinstance(legend, Mapping) or set(legend) != set(keys):
                raise JevProviderError('protocol_invalid', diagnostic='score_legend')
            if canonical([legend[k] for k in keys]) != canonical(question.scale):
                raise JevProviderError('protocol_invalid', diagnostic='score_legend')
            value = _number(answer['score'], 0, len(keys) - 1)
            expected = math.fsum(int(k) * p for k, p in probabilities.items())
            if abs(value - expected) > TOLERANCE:
                raise JevProviderError('protocol_invalid', diagnostic='score_expected_value')
            receipt.update(probabilities=probabilities, confidence=_number(answer['confidence']))
        usage = {'status': 'unknown'}
        reported = {k: getattr(response.usage, k) for k in ('input_tokens', 'output_tokens')}
        if any(v is not None for v in reported.values()):
            if any(v is not None and (type(v) is not int or v < 0) for v in reported.values()):
                raise JevProviderError('protocol_invalid', diagnostic='usage_invalid')
            usage = {'status': 'reported' if all(v is not None for v in reported.values()) else 'partial', **reported}
        return DecisionAnswer(question.question_id, question.kind, value, receipt, usage)

    async def close(self):
        async with self._close_lock:
            if self._closed:
                return
            self._closed = True
            await self._client.aclose()

    async def aclose(self):
        await self.close()
