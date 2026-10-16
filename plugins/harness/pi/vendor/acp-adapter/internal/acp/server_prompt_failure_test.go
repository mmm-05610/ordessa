package acp

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

func TestPromptFailureUsesRPCErrorWithOriginalTerminalMessage(t *testing.T) {
	for _, kind := range []codex.TurnEventType{codex.TurnEventTypeError, codex.TurnEventTypeCompleted} {
		t.Run(string(kind), func(t *testing.T) {
			var out bytes.Buffer
			server := &Server{codec: NewStdioCodec(strings.NewReader(""), &out)}
			lifecycle := &turnLifecycle{sessionID: "session-1", turnID: "turn-1"}
			_, terminal, reason := lifecycle.apply(codex.TurnEvent{Type: kind, StopReason: "error", Message: "controlled 403 FreeTierError"})
			if !terminal || reason != "error" {
				t.Fatalf("failure terminal lost: %v %q", terminal, reason)
			}
			server.writePromptTerminal(json.RawMessage(`3`), reason, nil, lifecycle.lastFailure, lifecycle.sessionID, lifecycle.turnID)
			var message struct {
				ID     int             `json:"id"`
				Result json.RawMessage `json:"result"`
				Error  struct {
					Code    int            `json:"code"`
					Message string         `json:"message"`
					Data    map[string]any `json:"data"`
				} `json:"error"`
			}
			if err := json.Unmarshal(out.Bytes(), &message); err != nil {
				t.Fatal(err)
			}
			if message.ID != 3 || len(message.Result) != 0 || message.Error.Code != -32603 || message.Error.Message != "backend prompt failed" {
				t.Fatalf("invalid failure response: %s", out.Bytes())
			}
			if message.Error.Data["error"] != "controlled 403 FreeTierError" || message.Error.Data["sessionId"] != "session-1" || message.Error.Data["turnId"] != "turn-1" {
				t.Fatalf("original failure context lost: %s", out.Bytes())
			}
		})
	}
}

func TestPromptResultRejectsInternalErrorStopReason(t *testing.T) {
	var out bytes.Buffer
	server := &Server{codec: NewStdioCodec(strings.NewReader(""), &out)}
	server.writePromptResult(json.RawMessage(`7`), "error")
	var message map[string]any
	if err := json.Unmarshal(out.Bytes(), &message); err != nil {
		t.Fatal(err)
	}
	if message["error"] == nil || message["result"] != nil {
		t.Fatalf("internal error became successful result: %s", out.Bytes())
	}
}
