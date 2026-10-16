import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import path from "node:path"
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../../../..")
export function capturedLaunchText() {
  return execFileSync(requiredPython(),["-c","from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog; import sys; sys.stdout.buffer.write(capture_selected_harness_catalog().launch_descriptor_bytes)"],{cwd:root,encoding:"utf8"})
}
export function capturedLaunchEnvironment(extra={}) { return {...process.env,...extra,ORDESSA_CAPTURED_LAUNCH_DESCRIPTORS:capturedLaunchText()} }

function requiredPython() { if (!process.env.ORDESSA_TEST_PYTHON) throw new Error("ORDESSA_TEST_PYTHON_REQUIRED"); return process.env.ORDESSA_TEST_PYTHON }

export function capturedCapabilityText() {
  return execFileSync(requiredPython(),["-c","from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog; from ordessa_server.composition.native_channels.profile_claims import captured_capability_text; print(captured_capability_text(capture_selected_harness_catalog()))"],{cwd:root,encoding:"utf8"}).trim()
}
