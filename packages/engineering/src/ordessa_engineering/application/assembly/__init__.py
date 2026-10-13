"""Build the Engineering gate from application-owned, injected ports.

The application assembly selects no concrete adapter or provider. The process
composition root owns that choice and the lifetime of every injected authority.
"""
from dataclasses import fields

from ..api import EngineeringService
from ..contracts.errors import ApplicationError
from ..contracts.service_ports import EngineeringPorts
from ..contracts.transactions import UoWFactory
from .method_runs import build_method_run_bindings
from .review_sources import build_review_check_admission
from .execution_dispatch import bind_execution_dispatch
from .reviewer_assignments import build_reviewer_assignment_usecases


def build_engineering_service(factory: UoWFactory, ports: EngineeringPorts) -> EngineeringService:
    if type(ports) is not EngineeringPorts:
        raise ApplicationError("INVALID_ENGINEERING_PORTS")
    if factory is None or not callable(getattr(factory, "begin", None)):
        raise ApplicationError("PERSISTENCE_AUTHORITY_UNAVAILABLE")
    dependencies = {field.name: getattr(ports, field.name) for field in fields(ports)
                    if field.name != "access"}
    return EngineeringService(factory, ports.access, **dependencies)


__all__ = ["build_engineering_service", "EngineeringPorts",
           "build_method_run_bindings", "build_review_check_admission",
           "bind_execution_dispatch", "build_reviewer_assignment_usecases"]
