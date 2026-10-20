"""Temporary ledger recorder for verify-clean; loaded only by that gate."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class VerifyCleanRecorder:
    def __init__(self) -> None:
        self.collected: list[str] = []
        self.reports: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def pytest_collection_modifyitems(self, session: Any, config: Any, items: list[Any]) -> None:
        # pytest's documented user_properties channel is included in each JUnit
        # testcase. Preserve existing properties; duplicate reserved properties
        # are intentionally left for the XML verifier to reject.
        for item in items:
            item.user_properties.append(("ordessa_nodeid", item.nodeid))

    def pytest_collection_finish(self, session: Any) -> None:
        self.collected = [item.nodeid for item in session.items]

    def pytest_runtest_logreport(self, report: Any) -> None:
        stages = self.reports.setdefault(report.nodeid, {})
        stages.setdefault(report.when, []).append(
            {
                "outcome": report.outcome,
                "wasxfail": getattr(report, "wasxfail", None),
                "longrepr": str(report.longrepr)[:1600] if report.failed else None,
            }
        )

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        destination = os.environ.get("ORDESSA_VERIFY_LEDGER_JSON")
        if not destination:
            return
        Path(destination).write_text(
            json.dumps(
                {
                    "collected_nodeids": self.collected,
                    "reports": self.reports,
                    "pytest_exitstatus": int(exitstatus),
                },
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )


def pytest_configure(config: Any) -> None:
    config.pluginmanager.register(VerifyCleanRecorder(), "verify-clean-recorder")
