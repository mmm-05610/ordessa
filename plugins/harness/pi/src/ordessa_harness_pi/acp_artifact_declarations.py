"""Own captured artifact facts; no Host import, defaults from another brand or verifier copy."""
import json
from pathlib import Path

def artifact_declaration():
    return json.loads((Path(__file__).resolve().parent / "_registration_declarations" / 'pi-runtime-artifact.json').read_text(encoding="utf-8"))
