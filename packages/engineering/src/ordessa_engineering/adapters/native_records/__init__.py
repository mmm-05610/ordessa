"""Optional adapters over original durable execution owners."""

from .recorded_dispatch import RecordedDispatchExecution, engineering_effect_write_guard_factory, NativeDispatchSources


def __getattr__(name):
    # These live-Unit adapters require the declared execution extra. Reading
    # durable recorded results alone does not select or load a live Unit SDK.
    if name == 'OriginalDispatchSelection':
        from .selection import OriginalDispatchSelection
        return OriginalDispatchSelection
    if name == 'build_local_dispatch_bindings':
        from .local_bindings import build_local_dispatch_bindings
        return build_local_dispatch_bindings
    if name == 'build_local_dispatch_query_factory':
        from .local_bindings import build_local_dispatch_query_factory
        return build_local_dispatch_query_factory
    if name == 'build_local_method_dispatch_inputs':
        from .method_inputs import build_local_method_dispatch_inputs
        return build_local_method_dispatch_inputs
    raise AttributeError(name)

__all__ = ['RecordedDispatchExecution', 'engineering_effect_write_guard_factory',
           'NativeDispatchSources', 'OriginalDispatchSelection',
           'build_local_dispatch_bindings', 'build_local_dispatch_query_factory',
           'build_local_method_dispatch_inputs']
