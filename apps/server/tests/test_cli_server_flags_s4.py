"""T014-S4: the Server CLI's business grammar arrives through the product's
`cli.server-flags` contribution; the host keeps only `--data-root`/`--port`.

The pre-move behaviour is the oracle: a reference parser rebuilt verbatim
from the host's old `parser()` is compared byte-for-byte against the
contribution-driven one (usage, help, parsed values), the old dispatch's
refusal messages are asserted verbatim against argparse's own error output,
and a routing-recording composition proves which method the plan selects
with which arguments. The move fails loudly if reverted: the host source is
scanned for business flag spellings and the product for their presence.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from ordessa_server import __main__ as host_cli
from ordessa_server_product import cli as product_cli
from ordessa_server_product.composition import create_composition
from server_plugin_api import (
    CLI_SERVER_FLAGS_API_VERSION,
    CLI_SERVER_FLAGS_POINT_ID,
    Contribution,
    ContributionBatch,
    ServerCliPlan,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
HOST_SRC = REPO_ROOT / "apps" / "server" / "src" / "ordessa_server"
PRODUCT_SRC = REPO_ROOT / "products" / "server" / "src"

BUSINESS_FLAG_SPELLINGS = (
    "--execution-mode", "--native-harness", "--native-adapter-command",
    "--native-adapter-arg", "--native-continuation", "--sidecar-deployment",
    "--plugin-root", "--mount",
)

NATIVE_ARGV = [
    "--data-root", "/d", "--port", "9001", "--execution-mode", "native",
    "--native-harness", "pi", "--native-adapter-command", "/usr/bin/node",
    "--native-adapter-arg", "a1", "--native-adapter-arg", "a2",
    "--native-continuation", "--plugin-root", "/p",
]
SIDECAR_ARGV = [
    "--data-root", "/d", "--sidecar-deployment", "/s/deploy.json",
    "--plugin-root", "/p", "--mount", "TOKEN=/x", "--mount", "OTHER=/y",
]


def reference_parser() -> argparse.ArgumentParser:
    """The host parser exactly as it stood before the grammar moved."""
    value = argparse.ArgumentParser(description="Run the Ordessa loopback Server")
    value.add_argument("--data-root", type=Path, required=True)
    value.add_argument("--port", type=int, default=8732)
    value.add_argument("--execution-mode", choices=("isolated", "native"), default="isolated")
    value.add_argument("--native-harness", help="one registered native Agent Harness id")
    value.add_argument("--native-adapter-command", help="absolute executable path of its ACP adapter")
    value.add_argument("--native-adapter-arg", action="append", default=[],
                       help="one adapter argument (repeatable)")
    value.add_argument("--native-continuation", action="store_true",
                       help="declare adapter resume support; runtime observation is still required")
    value.add_argument(
        "--sidecar-deployment", type=Path,
        help="non-secret Harness sidecar deployment JSON",
    )
    value.add_argument(
        "--plugin-root", type=Path,
        help="machine-local root the deployment's plugin-relative sources are read from",
    )
    value.add_argument(
        "--mount", action="append", default=[], metavar="TOKEN=PATH",
        help="bind one mount token the deployment names to a machine-local path "
             "(repeatable; the document itself carries no host path)",
    )
    return value


class _RecordingComposition:
    """The real product's grammar and plan; composition methods recorded."""

    def __init__(self, *, contribute=True):
        self.calls: list = []
        self._contribute = contribute
        self.inner = create_composition()

    def server_cli_contributions(self):
        if not self._contribute:
            return ContributionBatch()
        return self.inner.server_cli_contributions()

    def plan_server_cli(self, values):
        return self.inner.plan_server_cli(values)

    def __getattr__(self, name):
        if name.startswith("_") or name in ("inner", "calls", "_contribute"):
            raise AttributeError(name)

        def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return object()

        return _record


@pytest.fixture
def routed(monkeypatch):
    """`main` against a recording composition; uvicorn/create_app faked."""
    calls: dict = {}

    def _run(app, **kwargs):
        calls["run"] = (app, kwargs)

    monkeypatch.setattr("uvicorn.run", _run)
    monkeypatch.setattr(
        "ordessa_server.transport.http.create_app",
        lambda runtime: ("app", runtime))

    def _install(composition):
        monkeypatch.setattr(
            "ordessa_server.bootstrap._resolve_product_composition",
            lambda: composition)
        return composition

    _install.calls = calls
    return _install


# -- 1. the contribution-driven grammar is byte-identical to the old host one


def test_usage_and_help_render_identically_to_the_moved_grammar():
    contributed = host_cli.parser(product_cli.SERVER_CLI_FLAGS)
    reference = reference_parser()
    assert contributed.format_usage() == reference.format_usage()
    assert contributed.format_help() == reference.format_help()


@pytest.mark.parametrize("argv", [
    ["--data-root", "/d"],
    ["--data-root", "/d", "--port", "9999"],
    ["--data-root", "/d", "--plugin-root", "/p"],
    NATIVE_ARGV,
    SIDECAR_ARGV,
], ids=["minimal", "port", "plugin-root-only", "native-full", "sidecar-full"])
def test_every_flag_combination_parses_to_identical_values(argv):
    contributed = host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(argv)
    reference = reference_parser().parse_args(argv)
    assert vars(contributed) == vars(reference)


# -- 2. the parsed facts are routed through the product's plan


def test_native_flags_route_to_native_runtime_with_declared_feeds(routed):
    composition = routed(_RecordingComposition())
    assert host_cli.main(NATIVE_ARGV) == 0
    assert composition.calls == [(
        "native_runtime",
        (Path("/d"),),
        {"plugin_root": Path("/p"), "harness_id": "pi",
         "adapter_command": "/usr/bin/node", "adapter_args": ("a1", "a2"),
         "native_continuation": True},
    )]
    app, run_kwargs = routed.calls["run"]
    assert app[0] == "app"
    assert run_kwargs["port"] == 9001 and run_kwargs["workers"] == 1
    assert run_kwargs["host"] == "127.0.0.1"


def test_sidecar_flags_route_to_sidecar_runtime_with_bindings(routed):
    composition = routed(_RecordingComposition())
    assert host_cli.main(SIDECAR_ARGV) == 0
    assert composition.calls == [(
        "sidecar_runtime",
        (Path("/d"), Path("/s/deploy.json")),
        {"plugin_root": Path("/p"),
         "mount_bindings": {"TOKEN": "/x", "OTHER": "/y"}},
    )]


def test_bare_transport_flags_route_to_default_runtime(routed):
    composition = routed(_RecordingComposition())
    assert host_cli.main(["--data-root", "/d"]) == 0
    assert composition.calls == [("default_runtime", (Path("/d"),), {})]


def test_plan_arguments_are_exactly_the_declared_feeds_per_route():
    for dest, spec in product_cli._SPECS_BY_DEST.items():
        assert spec in product_cli.SERVER_CLI_FLAGS, dest
    native = create_composition().plan_server_cli(
        host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(NATIVE_ARGV).__dict__)
    expected = {s.feeds for s in product_cli.SERVER_CLI_FLAGS
                if s.feeds and s.route in ("", "native_runtime")}
    assert native.method == "native_runtime" and not native.args
    assert set(native.kwargs) == expected
    sidecar = create_composition().plan_server_cli(
        host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(SIDECAR_ARGV).__dict__)
    expected = {s.feeds for s in product_cli.SERVER_CLI_FLAGS
                if s.feeds and s.route in ("", "sidecar_runtime")}
    assert sidecar.method == "sidecar_runtime" and not sidecar.error
    # `deployment_path` is the composition method's second POSITIONAL
    # parameter — declared by its spec's `feeds`, carried in `plan.args`.
    assert set(sidecar.kwargs) == expected - {"deployment_path"}
    assert len(sidecar.args) == 1
    assert host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(
        SIDECAR_ARGV).sidecar_deployment == sidecar.args[0]


# -- 3. the combination refusals travel verbatim


@pytest.mark.parametrize("argv,message", [
    (["--data-root", "/d", "--port", "0"], "--port must be between 1 and 65535"),
    (["--data-root", "/d", "--port", "70000"], "--port must be between 1 and 65535"),
    (["--data-root", "/d", "--sidecar-deployment", "/s.json"],
     "--plugin-root is required with --sidecar-deployment"),
    (["--data-root", "/d", "--execution-mode", "native", "--native-harness", "pi"],
     "native mode requires --plugin-root, --native-harness and "
     "--native-adapter-command, without sidecar deployment or mounts"),
    (["--data-root", "/d", "--native-harness", "pi"],
     "native adapter options require --execution-mode native"),
    (["--data-root", "/d", "--execution-mode", "sideways"], None),
], ids=["port-zero", "port-high", "sidecar-no-plugin-root", "native-incomplete",
        "native-flags-isolated", "bad-choice"])
def test_refusals_report_argparse_s_own_error_with_the_moved_messages(
        routed, capsys, argv, message):
    """Byte-identity oracle: the stderr the contribution-driven `main`
    produces must equal what the pre-move host produced — the reference
    parser reporting the same message (or the same parse-time refusal) in
    the same process."""
    routed(_RecordingComposition())
    with pytest.raises(SystemExit) as exit_:
        host_cli.main(argv)
    assert exit_.value.code == 2
    new_err = capsys.readouterr().err
    with pytest.raises(SystemExit):
        reference = reference_parser()
        reference.parse_args(argv)  # raises by itself for the bad-choice row
        if message is not None:
            reference.error(message)
    assert new_err == capsys.readouterr().err


@pytest.mark.parametrize("argv,message", [
    (["--data-root", "/d", "--sidecar-deployment", "/s.json", "--plugin-root", "/p",
      "--mount", "noequals"], "--mount expects TOKEN=PATH"),
    (["--data-root", "/d", "--sidecar-deployment", "/s.json", "--plugin-root", "/p",
      "--mount", "A=/x", "--mount", "A=/y"], "--mount repeats the token 'A'"),
], ids=["mount-malformed", "mount-duplicate"])
def test_mount_binding_refusals_survive_the_move_verbatim(routed, argv, message):
    composition = routed(_RecordingComposition())
    with pytest.raises(SystemExit) as exit_:
        host_cli.main(argv)
    assert str(exit_.value) == message
    assert composition.calls == []


# -- 4. without the contribution the host carries no business grammar


def test_a_composition_without_the_contribution_refuses_business_flags(routed, capsys):
    class _NoSeam:
        def __init__(self):
            self.calls = []

        def plan_server_cli(self, values):
            return ServerCliPlan(method="default_runtime")

        def default_runtime(self, data_root, *args, **kwargs):
            self.calls.append((data_root, args, kwargs))
            return object()

    composition = routed(_NoSeam())
    assert host_cli.main(["--data-root", "/d"]) == 0
    with pytest.raises(SystemExit) as exit_:
        host_cli.main(["--data-root", "/d", "--native-harness", "pi"])
    assert exit_.value.code == 2
    assert "unrecognized arguments: --native-harness" in capsys.readouterr().err
    for spelling in BUSINESS_FLAG_SPELLINGS:
        with pytest.raises(SystemExit):
            host_cli.main(["--data-root", "/d", spelling])
    assert len(composition.calls) == 1


def test_an_empty_contribution_batch_omits_the_business_grammar(routed, capsys):
    composition = routed(_RecordingComposition(contribute=False))
    with pytest.raises(SystemExit):
        host_cli.main(["--data-root", "/d", "--execution-mode", "native"])
    assert "unrecognized arguments: --execution-mode" in capsys.readouterr().err
    assert composition.calls == []


def test_an_unknown_flag_still_answers_argparse_s_own_error(routed, capsys):
    routed(_RecordingComposition())
    with pytest.raises(SystemExit) as exit_:
        host_cli.main(["--data-root", "/d", "--not-a-flag"])
    assert exit_.value.code == 2
    assert "unrecognized arguments: --not-a-flag" in capsys.readouterr().err


# -- 5. the point identity and the boundary itself


def test_the_product_contributes_the_point_under_its_frozen_identity():
    batch = create_composition().server_cli_contributions()
    resolution = batch.resolve(CLI_SERVER_FLAGS_POINT_ID)
    assert isinstance(resolution, Contribution)
    assert resolution.api_version == CLI_SERVER_FLAGS_API_VERSION == "v1"
    assert batch.open_points == frozenset({CLI_SERVER_FLAGS_POINT_ID})
    assert [f for spec in resolution.payload for f in spec.flags] == [
        "--execution-mode", "--native-harness", "--native-adapter-command",
        "--native-adapter-arg", "--native-continuation", "--sidecar-deployment",
        "--plugin-root", "--mount",
    ]


def test_the_host_cli_carries_no_business_flag_spellings():
    for path in sorted(HOST_SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for spelling in ("--execution-mode", "--native-harness", "--sidecar-deployment"):
            assert spelling not in text, f"{path}: carries {spelling}"


def test_the_product_carries_the_business_flag_spellings():
    texts = {path: path.read_text(encoding="utf-8")
             for path in sorted(PRODUCT_SRC.rglob("*.py"))}
    joined = "\n".join(texts.values())
    for spelling in BUSINESS_FLAG_SPELLINGS:
        assert spelling in joined, spelling
