"""Explicit pinned SDK providers; no kernel registry, admission or runtime state."""
from types import MappingProxyType
from ...sdk.harness import HarnessDescriptor,HarnessError,ProfileContent
from ...sdk.prepare import canonical_json


class HarnessCatalog:
    def __init__(self,providers):
        pinned={};descriptors={}
        for provider in providers:
            descriptor=getattr(provider,'descriptor',None)
            if type(descriptor) is not HarnessDescriptor or not all(callable(getattr(provider,method,None)) for method in ('validate_profile','prepare','open_session')):
                raise HarnessError('HARNESS_PROVIDER_INVALID')
            key=canonical_json(dict(descriptor.definition_ref))
            if key in pinned:raise HarnessError('HARNESS_PIN_CONFLICT')
            pinned[key]=provider;descriptors[key]=canonical_json(descriptor.projection())
        self._providers=MappingProxyType(pinned)
        self._descriptors=MappingProxyType(descriptors)

    def resolve(self,definition_ref):
        try:key=canonical_json(dict(definition_ref))
        except Exception:raise HarnessError('HARNESS_PIN_INVALID') from None
        provider=self._providers.get(key)
        if provider is None:raise HarnessError('HARNESS_UNAVAILABLE')
        if canonical_json(provider.descriptor.projection())!=self._descriptors[key]:raise HarnessError('HARNESS_PIN_CHANGED')
        return provider

    def validate_profile(self,content):
        if type(content) is not ProfileContent:raise HarnessError('PROFILE_CONTENT_REQUIRED')
        result=self.resolve(content.harness_definition_ref).validate_profile(content)
        if result is not None:raise HarnessError('HARNESS_VALIDATION_PROTOCOL_INVALID')

    def prompt_handlers(self):
        """Protocol-id -> provider-owned prompt handler (native brands only)."""
        handlers={}
        for provider in self._providers.values():
            factory=getattr(provider,'prompt_handler',None)
            if not callable(factory):continue
            try:handler=factory()
            except Exception:raise HarnessError('NATIVE_PROMPT_HANDLER_INVALID') from None
            protocol=getattr(handler,'protocol_id',None)
            if type(protocol) is not str or not protocol or protocol in handlers:
                raise HarnessError('NATIVE_PROMPT_HANDLER_INVALID')
            if not all(callable(getattr(handler,name,None)) for name in
                    ('encode_prompt','accept','outcome','encode_cancel')):
                raise HarnessError('NATIVE_PROMPT_HANDLER_INVALID')
            handlers[protocol]=handler
        return handlers

    def native_codecs(self):
        """Protocol-id -> provider-owned native codec (strictly validated)."""
        from ...sdk.native_codec import validate_codec
        codecs = {}
        for provider in self._providers.values():
            factory = getattr(provider, 'native_codec', None)
            if not callable(factory):
                continue
            try:
                codec = validate_codec(factory())
            except Exception:
                raise HarnessError('NATIVE_CODEC_INVALID') from None
            protocol = codec.protocol_id
            if protocol in codecs:
                raise HarnessError('NATIVE_CODEC_INVALID')
            codecs[protocol] = codec
        return codecs

    def descriptors(self):
        return tuple(self.resolve(provider.descriptor.definition_ref).descriptor for provider in self._providers.values())
