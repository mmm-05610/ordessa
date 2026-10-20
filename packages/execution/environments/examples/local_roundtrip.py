"""Use the real Local provider through EnvironmentManager.

Usage: python local_roundtrip.py /absolute/path/to/state-directory

This example uses only Python's standard library at runtime. It makes no model
or remote calls and deliberately leaves its registry and working files intact.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from ordessa_environments import (
    EnvironmentManager,
    ProcessRequest,
    SQLiteEnvironmentStore,
)
from ordessa_environments_local import LocalEnvironmentResourceProvider


async def round_trip(use, label: str) -> tuple[bytes, bytes, int]:
    request = ProcessRequest.build(
        [
            sys.executable,
            "-u",
            "-c",
            "import sys; [print(line.rstrip(), flush=True) for line in sys.stdin]; "
            "print('stderr:' + sys.argv[1], file=sys.stderr, flush=True)",
            label,
        ],
        cwd=use.files.root(),
        env={},
    )
    process = use.execution.start(request)
    await process.write_stdin(f"stdout:{label}\n".encode("utf-8"))
    await process.close_stdin()
    stdout = await process.read_stdout(256, timeout=5)
    stderr = await process.read_stderr(256, timeout=5)
    exited = await process.wait_exit(timeout=5)
    if exited.state != "exited" or exited.exit_code is None:
        raise RuntimeError(f"process exit was not confirmed: {exited.state}")
    process.release()
    return stdout, stderr, exited.exit_code


async def run(state_dir: Path) -> None:
    if not state_dir.is_absolute():
        raise SystemExit("state directory must be an absolute path")
    state_dir.mkdir(parents=True, exist_ok=True)
    environment_root = state_dir / "work"
    environment_root.mkdir(parents=True, exist_ok=True)
    registry = state_dir / "environments.sqlite"

    provider = LocalEnvironmentResourceProvider(default_root=str(environment_root))
    providers = {"local": provider}
    first_manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(registry), providers=providers
    )
    created = first_manager.create("local", {"root": str(environment_root)})

    # A second manager can read the same persisted resource when explicitly
    # bound to the same provider identity and registry.
    second_manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(registry), providers=providers
    )
    instance = second_manager.get(created.identity)
    snapshot = instance.inspect()
    listed = second_manager.list()
    assert any(item.identity == instance.identity for item in listed)
    print(f"resource={snapshot.identity} state={snapshot.observation.state}")

    first = instance.acquire("environment-api-example-a", sharing=True)
    second = first_manager.get(instance.identity).acquire(
        "environment-api-example-b", sharing=True
    )
    first.files.write_text("retained.txt", "This file survives both Use releases.\n")

    stdout_a, stderr_a, exit_a = await round_trip(first, "a")
    assert stdout_a == b"stdout:a\n"
    assert stderr_a == b"stderr:a\n"
    assert exit_a == 0
    print(f"stdout={stdout_a!r}")
    print(f"stderr={stderr_a!r}")
    print(f"exit_code={exit_a}")
    first.release()

    # The independent shared Use remains usable after the first Use is released.
    stdout_b, stderr_b, exit_b = await round_trip(second, "b")
    assert stdout_b == b"stdout:b\n"
    assert stderr_b == b"stderr:b\n"
    assert exit_b == 0
    print(f"second_stdout={stdout_b!r}")
    print(f"second_stderr={stderr_b!r}")
    print(f"second_exit_code={exit_b}")
    second.release()

    retained = environment_root / "retained.txt"
    assert retained.read_text(encoding="utf-8") == "This file survives both Use releases.\n"
    assert first_manager.get(instance.identity).snapshot.active_uses == 0
    print(f"retained_file={retained}")
    print("active_uses=0")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python local_roundtrip.py /absolute/path/to/state-directory")
    asyncio.run(run(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
