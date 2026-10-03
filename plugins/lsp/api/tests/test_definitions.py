"""016 LSP-2 — 定义模型校验的正反例。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from ordessa_lsp_api import (
    FormatterDefinition,
    LspDefinitionError,
    LspSelection,
    LspServerDefinition,
    canonical_json_bytes,
    canonical_json_text,
)


def _server(name: str = "pyright", command: str = "pyright-langserver",
            languages: tuple[str, ...] = ("python",)) -> LspServerDefinition:
    return LspServerDefinition(name=name, command=command, languages=languages,
                               args=("--stdio",))


class TestDefinitions:
    def test_valid_server_round_trip(self) -> None:
        server = _server()
        assert server.kind == "lsp-server"
        assert server.to_jsonable() == {
            "args": ["--stdio"], "command": "pyright-langserver",
            "kind": "lsp-server", "languages": ["python"], "name": "pyright"}

    def test_valid_formatter(self) -> None:
        fmt = FormatterDefinition(name="ruff-format", command="ruff",
                                  languages=("python",), args=("format", "-"))
        assert fmt.kind == "formatter"

    def test_name_vocabulary(self) -> None:
        assert _server(name="a").name == "a"
        assert _server(name="py3.server-x").name == "py3.server-x"
        for bad in ("", "-lead", "Upper", "sp ace", "x" * 65, None, 7):
            with pytest.raises(LspDefinitionError):
                _server(name=bad)  # type: ignore[arg-type]

    def test_command_is_reference_only(self) -> None:
        with pytest.raises(LspDefinitionError):
            _server(command="")
        with pytest.raises(LspDefinitionError):
            _server(command="   ")
        with pytest.raises(LspDefinitionError):
            _server(command="pad\x00nul")
        with pytest.raises(LspDefinitionError):
            _server(command=" spaced ")
        with pytest.raises(LspDefinitionError):
            _server(command=7)  # type: ignore[arg-type]

    def test_args_must_be_strings(self) -> None:
        with pytest.raises(LspDefinitionError):
            LspServerDefinition(name="x", command="y", languages=("python",),
                                args=(1,))  # type: ignore[arg-type]

    def test_languages_nonempty_and_dedup(self) -> None:
        with pytest.raises(LspDefinitionError):
            _server(languages=())
        with pytest.raises(LspDefinitionError):
            _server(languages=("python", "python"))
        with pytest.raises(LspDefinitionError):
            _server(languages=("python", " "))
        assert _server(
            languages=("python", "javascript")).languages == ("python", "javascript")


class TestSelection:
    def test_scope_is_explicit(self) -> None:
        with pytest.raises(LspDefinitionError):
            LspSelection(scope="")  # type: ignore[arg-type]
        with pytest.raises(LspDefinitionError):
            LspSelection(scope="Session")  # type: ignore[arg-type]
        assert LspSelection(scope="session", servers=(_server(),)).scope == "session"
        assert LspSelection(scope="profile").scope == "profile"

    def test_shared_name_space(self) -> None:
        fmt = FormatterDefinition(name="pyright", command="pyright-fmt",
                                  languages=("python",))
        with pytest.raises(LspDefinitionError):
            LspSelection(scope="session", servers=(_server(),), formatters=(fmt,))

    def test_empty_selection_is_legal(self) -> None:
        selection = LspSelection(scope="profile")
        assert list(selection.definitions()) == []


class TestCanonicalTranscription:
    def test_byte_stable_across_insertion_order(self) -> None:
        a = {"b": 1, "a": {"y": [1, 2], "x": "值"}}
        b = {"a": {"x": "值", "y": [1, 2]}, "b": 1}
        assert canonical_json_bytes(a) == canonical_json_bytes(b)

    def test_shape(self) -> None:
        text = canonical_json_text({"k": ["v", 1]})
        assert text == '{"k":["v",1]}\n'
        assert canonical_json_bytes({"k": "值"}) == '{"k":"值"}\n'.encode("utf-8")

    def test_nan_refused(self) -> None:
        import json
        with pytest.raises(ValueError):
            canonical_json_text({"k": float("nan")})
        with pytest.raises((TypeError, ValueError)):
            canonical_json_text({"k": object()})

    def test_selection_transcription_is_definition_level(self) -> None:
        selection = LspSelection(scope="session", servers=(_server(),))
        blob = canonical_json_bytes(selection.to_jsonable())
        # 引用制：转录只含可执行引用名，不含任何二进制内容
        assert b"pyright-langserver" in blob
        assert len(blob) < 300
