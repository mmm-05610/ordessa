"""Model-provider-owned wire model facts; native dialects are not accepted here.

The four legacy field checks/refusal strings are retained from the compat
validator. Optional capability/protocol facts use this domain's existing strict
normalizer instead of being dropped by the historical four-field surface.
"""
from typing import Mapping
from server_plugin_api.wire_errors import WireError
from server_plugin_api.wire_shape import bounded
from .protocols import normalize_model_facts


def models(value):
    if not isinstance(value, list):
        raise WireError('INVALID_REQUEST', 'models must be a list')
    result = []
    required = {'modelId', 'displayName', 'availability', 'unavailableReason'}
    optional = {'capabilities', 'protocols'}
    for item in value:
        if (not isinstance(item, Mapping) or not required <= set(item)
                or set(item) - required - optional):
            raise WireError('INVALID_REQUEST', 'each model has an invalid shape')
        availability, reason = item['availability'], item['unavailableReason']
        if availability not in {'unknown', 'available', 'unavailable'}:
            raise WireError('INVALID_REQUEST', 'model availability is invalid')
        if reason is not None and not isinstance(reason, str):
            raise WireError('INVALID_REQUEST', 'unavailableReason must be a string or null')
        out = {'modelId': bounded(item['modelId'], 'modelId', 256),
               'displayName': bounded(item['displayName'], 'displayName', 256),
               'availability': availability, 'unavailableReason': reason}
        out.update({key: item[key] for key in optional if key in item})
        result.append(normalize_model_facts(out))
    return result
