# OpenCode native resource owner checkpoint

The independent OpenCode provider owns the native driver and deployment template.
This cut removes the aggregate driver copy and template implementation. Existing
native tests and the Server driver-conformance test consume the provider-owned
resource; template/declaration tests consume its explicit declaration source.
The historical serialized bundle key `runtime/drivers/opencode-native.mjs` is
preserved. No old-module forwarding or implicit resource fallback is added.

The old aggregate install-set producer can no longer select OpenCode: its plugin
root does not own the resource. This is an explicit capability withdrawal from
that producer, not a claim that an OpenCode Unit production launcher is ready.
Other existing aggregate execution paths are outside this resource-only cut;
this checkpoint does not claim that the full Harness aggregate has retired.

Validation: the six existing provider-owned native regression files passed all
32 controlled cases with no skips or model calls. Exact candidate template and
capability-declaration suites passed 77 cases. The Server conformance and retired
install-set negative case each passed. The complete independent OpenCode suite
passed 35 cases, and the original aggregate Harness gate passed 404 cases with
its three historical skips unchanged. Main still requires the full
PR checks; the remaining owner/activation migration blockers are not waived.
