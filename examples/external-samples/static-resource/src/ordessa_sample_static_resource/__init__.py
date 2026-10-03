"""External sample #2: `ordessa-sample-static-resource` (import
`ordessa_sample_static_resource`)."""
from ordessa_sample_static_resource.plugin import (
    FROZEN_RESOURCES_SHA256,
    PLUGIN_ID,
    METHOD_GET,
    METHOD_LIST,
    SampleStaticResourcePlugin,
)

__all__ = [
    "FROZEN_RESOURCES_SHA256",
    "PLUGIN_ID",
    "METHOD_GET",
    "METHOD_LIST",
    "SampleStaticResourcePlugin",
]
