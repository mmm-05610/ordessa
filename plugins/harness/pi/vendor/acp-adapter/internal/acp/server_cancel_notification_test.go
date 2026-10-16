package acp

import (
	"encoding/json"
	"testing"
	"time"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

func TestStandardCancelNotificationRetiresTurnWithoutResponseAndAllowsReuse(t *testing.T) {
	app := newCancelRaceAppClient(nil, &codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "cancelled"}, cancelRaceRetireGap)
	h := startCancelRaceHarness(t, app)
	var seen []RPCMessage
	h.prompt("3", "cancel by notification")
	h.awaitTurnStarted(&seen)
	if err := json.NewEncoder(h.writer).Encode(map[string]any{"jsonrpc": "2.0", "method": methodSessionCancel,
		"params": map[string]any{"sessionId": h.sessionID}}); err != nil {
		t.Fatal(err)
	}
	result, failure := h.promptReply("3", &seen)
	if failure != nil || result.StopReason != "cancelled" || !app.retired() {
		t.Fatalf("notification did not establish real retirement: result=%+v error=%+v", result, failure)
	}
	assertFollowUpAccepted(t, h, &seen, "5")
	h.drain(20*time.Millisecond, &seen)
	for _, msg := range seen {
		if msg.Method == "" && msg.ID == nil {
			t.Fatalf("notification produced an unsolicited response: %+v", msg)
		}
	}
}

func TestMalformedCancelNotificationDoesNotReplyOrBreakSubsequentRequest(t *testing.T) {
	h := startCancelRaceHarness(t, &slotAppClient{stdioMockAppClient: &stdioMockAppClient{}})
	for _, params := range []any{map[string]any{}, map[string]any{"sessionId": "missing"}} {
		if err := json.NewEncoder(h.writer).Encode(map[string]any{"jsonrpc": "2.0", "method": methodSessionCancel, "params": params}); err != nil {
			t.Fatal(err)
		}
	}
	var seen []RPCMessage
	assertFollowUpAccepted(t, h, &seen, "5")
	h.drain(20*time.Millisecond, &seen)
	for _, msg := range seen {
		if msg.Method == "" && msg.ID == nil {
			t.Fatalf("malformed notification produced a response: %+v", msg)
		}
	}
}
