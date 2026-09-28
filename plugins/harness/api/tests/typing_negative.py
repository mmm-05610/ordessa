"""Expected mypy failures: closed union and non-optional permit/target types."""

from ordessa_harness_api import ApplicationResult, ConfigurationService, Intent, ResumeRequest, RuntimeAdapter, SetField


def wrong_result(result: ApplicationResult) -> str:
    return result.applied_revision  # E: Refused/Unknown have no applied_revision


def wrong_intent(intent: Intent) -> str:
    return intent.typed_value  # E: only SetField has typed_value


def wrong_permit(service: ConfigurationService) -> None:
    service.apply("plan", "key", None)  # E: permit cannot be None


def wrong_construction() -> None:
    SetField("owner", "path", "field", {})  # E: structured source/target/path required


def wrong_resume(adapter: RuntimeAdapter) -> None:
    adapter.resume("session/new")  # E: typed ResumeRequest required
    ResumeRequest("old", "native", 2, method="session/new")  # E: method not caller controlled
