"""Build-time Harness API mirror: verify by default, --write to regenerate.

Reads source declarations without evaluating JavaScript, launching commands or
importing Harness runtime. The packaged client consumes only its JSON mirror.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_FAMILIES = {"claude-code", "codex", "dsh", "hermes", "kilo", "opencode", "pi", "qwen"}


def _bare(command):
    if not isinstance(command, str) or not _NAME.fullmatch(command):
        raise ValueError("Harness source candidate is not a bounded bare command name")
    return command


def _profile_block(text, family):
    match = re.search(r'(?ms)^  "?' + re.escape(family) + r'"?: \{(.*?)(?=^  [\w"-]+: \{|^\})', text)
    if match is None:
        raise ValueError("Harness command source profile is missing: " + family)
    return match.group(1)


def _js_names(block, fields):
    commands = set()
    for field in fields:
        expression = re.search(r"(?m)^    " + field + r": ([^\n]+),$", block)
        if expression is None:
            continue
        expression = expression.group(1)
        plain = re.fullmatch(r'"([^"]+)"', expression)
        conditional = re.fullmatch(r'process\.platform === "win32" \? "([^"]+)" : "([^"]+)"', expression)
        if plain:
            commands.add(_bare(plain.group(1)))
        elif conditional:
            commands.update(_bare(value) for value in conditional.groups())
        else:
            raise ValueError("Harness command source expression requires explicit catalog review")
    if not commands:
        raise ValueError("Harness command source contains no candidate names")
    return commands


def source_candidates(root):
    """Bounded literal extraction: an unsupported source shape fails closed."""
    harness = root / "plugins/harness"
    toml = (harness / "src/ordessa_harness/harnesses.toml").read_text(encoding="utf-8")
    names = {}
    for block in re.split(r"(?m)^\[\[harness\]\]\s*$", toml)[1:]:
        family = re.findall(r'(?m)^harness_type = "([^"]+)"$', block)
        executable = re.findall(r'(?m)^identity = "([^"]+)"$', block)
        if len(family) != 1 or len(executable) != 1:
            raise ValueError("Harness native identity declaration is ambiguous")
        family = family[0]
        if family not in _FAMILIES:
            continue
        if family in names:
            raise ValueError("Harness family has duplicate native declarations")
        names[family] = {_bare(executable[0])}
        for argv in re.findall(r"(?m)^argv = (\[[^\n]+\])$", block):
            decoded = json.loads(argv)
            if not isinstance(decoded, list) or not decoded:
                raise ValueError("Harness launch argv is malformed")
            names[family].add(_bare(decoded[0]))
    upstream = (harness / "third_party/harness_remote/bridge/src/harness-profiles.js").read_text(encoding="utf-8")
    for family, source_family in (("codex", "codex"), ("pi", "pi"), ("claude-code", "claude")):
        names.setdefault(family, set()).update(_js_names(_profile_block(upstream, source_family), ("adapterCommand",)))
    extensions = (harness / "runtime/profile_extensions.mjs").read_text(encoding="utf-8")
    for family in ("claude-code", "hermes", "dsh", "kilo", "qwen"):
        names.setdefault(family, set()).update(_js_names(_profile_block(extensions, family), ("command", "adapterCommand")))
    if set(names) != _FAMILIES:
        raise ValueError("Harness candidate source family set differs from the reviewed catalog")
    return [{"familyId": family, "commands": sorted(commands)} for family, commands in sorted(names.items())]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify or explicitly regenerate the Harness-owned command-name catalog")
    parser.add_argument("--write", action="store_true", help="Replace the packaged command catalog from the public Harness API")
    options = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    # Public, dependency-free API loaded only at build time, never by the CLI.
    api_source = str(root / "plugins/harness/api/src")
    sys.path.insert(0, api_source)
    try:
        from ordessa_harness_api.command_discovery import command_catalog_document
        document = command_catalog_document()
    finally:
        sys.path.remove(api_source)
    if document["catalog"]["candidates"] != source_candidates(root):
        raise SystemExit("Public Harness command catalog differs from the native/adapter source declarations")
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n"
    mirror = root / "products/agent-tools/src/ordessa_agent_tools/harness_commands.json"
    if options.write:
        mirror.write_text(encoded, encoding="utf-8")
    if not mirror.is_file() or mirror.read_text(encoding="utf-8") != encoded:
        raise SystemExit("Client Harness command mirror differs from the public catalog; regenerate explicitly with --write")
    print("Harness command candidate mirror verified (8 families; no runtime readiness claim)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
