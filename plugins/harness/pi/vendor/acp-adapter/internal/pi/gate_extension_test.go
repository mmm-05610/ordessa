package pi

import (
	"encoding/json"
	"os/exec"
	"regexp"
	"strings"
	"testing"
)

func TestGateExtensionBehaviorWithControlledPiPeers(t *testing.T) {
	if _, err := exec.LookPath("node"); err != nil {
		t.Fatalf("Node is required to exercise the generated Pi extension source: %v", err)
	}

	source := gateExtensionSource
	importLine := `import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";`
	if strings.Count(source, importLine) != 1 {
		t.Fatal("expected exactly one Pi type-only import in generated extension")
	}
	source = strings.Replace(source, importLine, "", 1)
	source = strings.Replace(source, "export default function (pi: ExtensionAPI) {", "function extension(pi) {", 1)
	source = strings.Replace(source, "function looksNetworkCommand(command: string): boolean {", "function looksNetworkCommand(command) {", 1)
	payloadSignature := regexp.MustCompile(`(?s)function payloadForTool\(event: \{.*?\}\) \{`)
	if !payloadSignature.MatchString(source) {
		t.Fatal("could not strip the generated extension's Pi event type annotation")
	}
	source = payloadSignature.ReplaceAllString(source, "function payloadForTool(event) {")
	if strings.Contains(source, ": ExtensionAPI") || strings.Contains(source, "import type") ||
		strings.Contains(source, "event: {") || strings.Contains(source, "command: string") {
		t.Fatal("generated extension still contains TypeScript-only syntax after controlled stripping")
	}

	sourceJSON, err := json.Marshal(source)
	if err != nil {
		t.Fatalf("could not encode generated extension source for the Node harness: %v", err)
	}
	harness := `
const assert = require("node:assert/strict");
const source = ` + string(sourceJSON) + `;

const envKey = "ORDESSA_APPROVED_CHECK_COMMAND";
const extensionFactory = new Function("process", "Buffer", source + "\nreturn extension;");
function installGate(command, configured = true) {
  const handlers = Object.create(null);
  const env = configured ? { [envKey]: command } : {};
  extensionFactory({ env }, Buffer)({ on(name, handler) { handlers[name] = handler; } });
  assert.equal(typeof handlers.tool_call, "function");
  assert.equal(typeof handlers.before_agent_start, "function");
  return handlers;
}

async function callTool(handlers, toolName, input, options = {}) {
  const confirmations = [];
  const ctx = {
    hasUI: options.hasUI !== false,
    ui: { async confirm(title, message, config) {
      confirmations.push({ title, message: JSON.parse(message), config });
      return options.confirm !== false;
    } },
  };
  const result = await handlers.tool_call({ type: "tool_call", toolCallId: "controlled-call", toolName, input }, ctx);
  return { result, confirmations };
}

async function main() {
  const legacy = installGate(undefined, false);
  assert.equal(await legacy.before_agent_start({ systemPrompt: "base prompt" }), undefined,
    "without the explicit env, the hook must leave the existing prompt unchanged");
  const legacyBash = await callTool(legacy, "bash", { command: "echo ordinary" });
  assert.equal(legacyBash.result, undefined, "default bash still uses the old approval path");
  assert.equal(legacyBash.confirmations.length, 1);
  assert.equal(legacyBash.confirmations[0].message.command, "echo ordinary");

  const command = "python -m pytest catalog/tests";
  const configured = installGate(command);
  const prompt = await configured.before_agent_start({ systemPrompt: "base prompt" });
  assert.match(prompt.systemPrompt, /base prompt/);
  assert.ok(prompt.systemPrompt.includes(JSON.stringify(command)));
  assert.match(prompt.systemPrompt, /no other bash command/);

  const exact = await callTool(configured, "bash", { command });
  assert.equal(exact.result, undefined, "the exact approved command proceeds to confirmation");
  assert.equal(exact.confirmations.length, 1, "exact command still requires the existing UI approval");
  assert.equal(exact.confirmations[0].message.command, command);

  for (const altered of ["", " ", command + " ", command + "; echo extra", "echo other"]) {
    const rejected = await callTool(configured, "bash", { command: altered });
    assert.equal(rejected.result?.block, true, "altered command must block: " + JSON.stringify(altered));
    assert.equal(rejected.confirmations.length, 0, "mismatched command must block before UI confirmation");
  }

  const noUI = await callTool(configured, "bash", { command }, { hasUI: false });
  assert.equal(noUI.result?.block, true, "exact command still fails closed without the original UI owner");
  assert.equal(noUI.confirmations.length, 0);
  const denied = await callTool(configured, "bash", { command }, { confirm: false });
  assert.equal(denied.result?.block, true, "the existing user denial still blocks the command");
  assert.equal(denied.result.reason, "Blocked by user");
  assert.equal(denied.confirmations.length, 1);

  const file = await callTool(configured, "write", { path: "spec.md", content: "x" });
  assert.equal(file.result, undefined, "file operations retain their original confirmation route");
  assert.equal(file.confirmations.length, 1);
  assert.equal(file.confirmations[0].message.toolName, "write");

  for (const invalid of ["", "   ", "python -m pytest\nother", "python\u0000 -m pytest", "x".repeat(4097), "é".repeat(2049)]) {
    const invalidGate = installGate(invalid);
    const invalidPrompt = await invalidGate.before_agent_start({ systemPrompt: "base prompt" });
    assert.match(invalidPrompt.systemPrompt, /command is invalid/);
    const rejected = await callTool(invalidGate, "bash", { command: invalid });
    assert.equal(rejected.result?.block, true, "invalid configured command must fail closed");
    assert.equal(rejected.confirmations.length, 0);
  }

  const maxBytesCommand = "é".repeat(2048);
  const maxBytesGate = installGate(maxBytesCommand);
  const maxBytesPrompt = await maxBytesGate.before_agent_start({ systemPrompt: "base prompt" });
  assert.doesNotMatch(maxBytesPrompt.systemPrompt, /command is invalid/,
    "the exact 4096-byte UTF-8 boundary is valid");
  const maxBytesCall = await callTool(maxBytesGate, "bash", { command: maxBytesCommand });
  assert.equal(maxBytesCall.result, undefined);
  assert.equal(maxBytesCall.confirmations.length, 1);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
`

	output, err := exec.Command("node", "-e", harness).CombinedOutput()
	if err != nil {
		t.Fatalf("generated gate extension behavior failed: %v\n%s", err, output)
	}
}
