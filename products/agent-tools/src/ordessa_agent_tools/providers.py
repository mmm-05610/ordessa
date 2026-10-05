"""Validation of public registry observations; no providers or native clients."""
import re


def definition_ref_valid(value, environment=None):
    return (isinstance(value, dict) and set(value) == {'environmentNamespace', 'definitionId', 'revision'}
            and all(isinstance(item, str) and item and len(item) <= 128 and not any(ord(c) < 32 for c in item) for item in value.values())
            and (environment is None or value['environmentNamespace'] == environment))


def provider_view_valid(value, environment, runtime_version, allowed_methods):
    if not isinstance(value, dict) or set(value) != {'descriptor', 'providerRef'}:
        return False
    descriptor, ref = value['descriptor'], value['providerRef']
    if (not isinstance(descriptor, dict) or set(descriptor) != {'providerId', 'contractVersion', 'definitionRef', 'implementationDigest', 'supportedMethods'}
            or not isinstance(ref, dict) or set(ref) != {'environmentNamespace', 'providerId', 'ownerActivationRef', 'generation', 'contractVersion', 'implementationDigest'}):
        return False
    owner, methods = ref['ownerActivationRef'], descriptor['supportedMethods']
    return (isinstance(descriptor['providerId'], str) and re.fullmatch(r'[a-z][a-z0-9._-]{0,127}', descriptor['providerId']) is not None
            and definition_ref_valid(descriptor['definitionRef'], environment)
            and descriptor['contractVersion'] == runtime_version == ref['contractVersion']
            and isinstance(descriptor['implementationDigest'], str) and re.fullmatch(r'sha256:[0-9a-f]{64}', descriptor['implementationDigest']) is not None
            and descriptor['implementationDigest'] == ref['implementationDigest']
            and descriptor['providerId'] == ref['providerId'] and ref['environmentNamespace'] == environment
            and type(ref['generation']) is int and ref['generation'] > 0
            and isinstance(owner, dict) and set(owner) == {'environmentNamespace', 'pluginId', 'generation'}
            and owner['environmentNamespace'] == environment and type(owner['generation']) is int and owner['generation'] == ref['generation']
            and isinstance(owner['pluginId'], str) and bool(owner['pluginId']) and not any(ord(c) < 32 for c in owner['pluginId'])
            and isinstance(methods, list) and all(isinstance(method, str) and method in allowed_methods for method in methods)
            and len(methods) == len(set(methods)))


def provider_result_valid(action, result, environment, runtime_version, allowed_methods, requested_definition=None):
    if action == 'describe':
        return (provider_view_valid(result, environment, runtime_version, allowed_methods)
                and result['descriptor']['definitionRef'] == requested_definition)
    if not isinstance(result, dict) or set(result) != {'providers'} or not isinstance(result['providers'], list):
        return False
    values = result['providers']
    if not all(provider_view_valid(value, environment, runtime_version, allowed_methods) for value in values):
        return False
    ids = [value['descriptor']['providerId'] for value in values]
    definitions = [tuple(value['descriptor']['definitionRef'][name] for name in ('environmentNamespace', 'definitionId', 'revision')) for value in values]
    return len(ids) == len(set(ids)) and len(definitions) == len(set(definitions))
