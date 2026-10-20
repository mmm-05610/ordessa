package acp

import (
	"testing"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

func TestPiFileApprovalOperationUsesExactACPKindAndRawInput(t *testing.T) {
	t.Parallel()

	for _, tc := range []struct {
		operation string
		kind      string
		title     string
	}{
		{"read", "read", "Read /unit/allowed.txt"},
		{"write", "edit", "Write /unit/allowed.txt"},
		{"edit", "edit", "Edit /unit/allowed.txt"},
	} {
		approval := codex.ApprovalRequest{
			ToolCallID: "tool-1", Kind: codex.ApprovalKindFile,
			FileOperation: tc.operation, Files: []string{"/unit/allowed.txt"},
		}
		toolCall := permissionRequestToolCall(approval)
		if toolCall == nil || toolCall.Kind != tc.kind || toolCall.Title != tc.title {
			t.Fatalf("operation %q mapping mismatch: %+v", tc.operation, toolCall)
		}
		if got := toolCall.RawInput["operation"]; got != tc.operation {
			t.Fatalf("operation %q missing from rawInput: %+v", tc.operation, toolCall.RawInput)
		}
	}
}

func TestLegacyAndUnknownFileOperationsAreNotReadApprovals(t *testing.T) {
	t.Parallel()

	legacy := permissionRequestToolCall(codex.ApprovalRequest{
		ToolCallID: "legacy", Kind: codex.ApprovalKindFile, Files: []string{"/unit/file.txt"},
	})
	if legacy.Kind != "edit" || legacy.Title != "Modify /unit/file.txt" {
		t.Fatalf("legacy Codex file approval semantics changed: %+v", legacy)
	}
	legacyMany := permissionRequestToolCall(codex.ApprovalRequest{
		ToolCallID: "legacy-many", Kind: codex.ApprovalKindFile,
		Files: []string{"/unit/one.txt", "/unit/two.txt"},
	})
	if legacyMany.Kind != "edit" || legacyMany.Title != "Modify 2 files" {
		t.Fatalf("legacy multi-file Codex approval semantics changed: %+v", legacyMany)
	}
	unknown := permissionRequestToolCall(codex.ApprovalRequest{
		ToolCallID: "unknown", Kind: codex.ApprovalKindFile,
		FileOperation: "read-anything", Files: []string{"/unit/file.txt"},
	})
	if unknown.Kind != "other" {
		t.Fatalf("unknown file operation must not be advertised as read/edit: %+v", unknown)
	}
}
