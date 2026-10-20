import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import path from "node:path"
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../../../..")
export function stageAccessEntry(destination) {
  return execFileSync(requiredPython(),["-c","from pathlib import Path; import sys; from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog; from ordessa_server.composition.native_channels.access_bundle import stage_access_entry; print(stage_access_entry(Path(sys.argv[1]),capture_selected_harness_catalog()).entry)",destination],{cwd:root,encoding:"utf8"}).trim()
}

function requiredPython() { if (!process.env.ORDESSA_TEST_PYTHON) throw new Error("ORDESSA_TEST_PYTHON_REQUIRED"); return process.env.ORDESSA_TEST_PYTHON }

export function stageAccessEntryManifest(destination) {
  return JSON.parse(execFileSync(requiredPython(),["-c","from pathlib import Path; import sys,json; from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog; from ordessa_server.composition.native_channels.access_bundle import stage_access_entry; b=stage_access_entry(Path(sys.argv[1]),capture_selected_harness_catalog()); print(json.dumps({'schema_version':b.schema_version,'required':b.required,'entry':str(b.entry)}))",destination],{cwd:root,encoding:"utf8"}))
}
