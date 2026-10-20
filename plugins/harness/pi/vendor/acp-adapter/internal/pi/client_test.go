package pi

import (
	"strings"
	"testing"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

func TestApprovalFromGatePayloadKeepsFileOperationAndRejectsUnknown(t *testing.T) {
	t.Parallel()

	for _, operation := range []string{"read", "write", "edit"} {
		approval, ok := approvalFromGatePayload(gateRequestPayload{
			Gate: "acp-adapter", Approval: "file", ToolName: operation,
			ToolCallID: "tool-1", Files: []string{"/unit/allowed.txt"},
		})
		if !ok || approval.Kind != codex.ApprovalKindFile || approval.FileOperation != operation {
			t.Fatalf("operation %q was not preserved: approval=%+v ok=%v", operation, approval, ok)
		}
	}

	if _, ok := approvalFromGatePayload(gateRequestPayload{
		Gate: "acp-adapter", Approval: "file", ToolName: "bash", Files: []string{"/unit/allowed.txt"},
	}); ok {
		t.Fatal("unknown/command tool must not be turned into a file approval")
	}
	if _, ok := approvalFromGatePayload(gateRequestPayload{
		Gate: "acp-adapter", Approval: "read", ToolName: "read", Files: []string{"/unit/allowed.txt"},
	}); ok {
		t.Fatal("unknown approval kind must fail closed")
	}

	legacy, ok := approvalFromGatePayload(gateRequestPayload{
		Gate: "acp-adapter", Approval: "file", Files: []string{"/unit/allowed.txt"},
	})
	if !ok || legacy.FileOperation != "edit" {
		t.Fatalf("legacy file payload must keep edit semantics: approval=%+v ok=%v", legacy, ok)
	}
}

func TestGateExtensionRoutesReadThroughFilePermissionAndKeepsDefaultBashGate(t *testing.T) {
	t.Parallel()
	for _, fragment := range []string{
		`event.toolName === "read"`,
		`approval: "file"`,
		`toolName: event.toolName`,
		`event.toolName !== "read"`,
		`event.toolName === "bash"`,
	} {
		if !strings.Contains(gateExtensionSource, fragment) {
			t.Fatalf("gate extension missing required routing fragment %q", fragment)
		}
	}
}

func TestSessionApprovalRuleFromApproval(t *testing.T) {
	t.Parallel()

	rule, ok := sessionApprovalRuleFromApproval(codex.ApprovalRequest{
		Kind:    codex.ApprovalKindCommand,
		Command: "go test ./...",
	})
	if !ok {
		t.Fatalf("expected command approval rule")
	}
	if rule.Kind != codex.ApprovalKindCommand || rule.Command != "go test ./..." {
		t.Fatalf("unexpected command rule: %+v", rule)
	}

	fileRule, ok := sessionApprovalRuleFromApproval(codex.ApprovalRequest{
		Kind:  codex.ApprovalKindFile,
		Files: []string{"b.txt", "a.txt", "a.txt", "  "},
	})
	if !ok {
		t.Fatalf("expected file approval rule")
	}
	if len(fileRule.Files) != 2 || fileRule.Files[0] != "a.txt" || fileRule.Files[1] != "b.txt" {
		t.Fatalf("unexpected file rule: %+v", fileRule)
	}
}

func TestClientRememberSessionApproval(t *testing.T) {
	t.Parallel()

	client := NewClient(Config{})
	threadID := "session-1"
	approval := codex.ApprovalRequest{
		ThreadID: threadID,
		Kind:     codex.ApprovalKindCommand,
		Command:  "echo approved by fake pi",
	}

	if client.shouldAutoApprove(threadID, approval) {
		t.Fatalf("approval should not be cached before remember")
	}

	client.rememberSessionApproval(threadID, approval)

	if !client.shouldAutoApprove(threadID, approval) {
		t.Fatalf("approval should be cached after remember")
	}

	client.removeSession(threadID)
	if client.shouldAutoApprove(threadID, approval) {
		t.Fatalf("approval cache should be cleared with session removal")
	}
}

func TestSessionFileApprovalCacheDoesNotCrossReadAndWriteOperations(t *testing.T) {
	t.Parallel()

	client := NewClient(Config{})
	threadID := "session-file-operations"
	path := "/unit/allowed.txt"
	read := codex.ApprovalRequest{
		ThreadID: threadID, Kind: codex.ApprovalKindFile,
		FileOperation: "read", Files: []string{path},
	}
	write := codex.ApprovalRequest{
		ThreadID: threadID, Kind: codex.ApprovalKindFile,
		FileOperation: "write", Files: []string{path},
	}
	edit := codex.ApprovalRequest{
		ThreadID: threadID, Kind: codex.ApprovalKindFile,
		FileOperation: "edit", Files: []string{path},
	}

	client.rememberSessionApproval(threadID, read)
	if !client.shouldAutoApprove(threadID, read) {
		t.Fatal("matching read approval should be cached for this session")
	}
	if client.shouldAutoApprove(threadID, write) || client.shouldAutoApprove(threadID, edit) {
		t.Fatal("read approval must not authorize write or edit")
	}

	client.rememberSessionApproval(threadID, write)
	if !client.shouldAutoApprove(threadID, write) {
		t.Fatal("matching write approval should be cached for this session")
	}
	if client.shouldAutoApprove(threadID, edit) {
		t.Fatal("write approval must not authorize edit")
	}

	legacyEdit := codex.ApprovalRequest{
		ThreadID: threadID, Kind: codex.ApprovalKindFile, Files: []string{path},
	}
	legacyRule, ok := sessionApprovalRuleFromApproval(legacyEdit)
	if !ok || legacyRule.FileOperation != "edit" {
		t.Fatalf("legacy file approval must normalize to edit: %+v ok=%v", legacyRule, ok)
	}
	if _, ok := sessionApprovalRuleFromApproval(codex.ApprovalRequest{
		Kind: codex.ApprovalKindFile, FileOperation: "execute", Files: []string{path},
	}); ok {
		t.Fatal("unknown file operation must not produce a session cache rule")
	}
}
