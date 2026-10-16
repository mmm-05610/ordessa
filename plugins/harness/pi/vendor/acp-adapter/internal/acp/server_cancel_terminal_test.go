package acp

// A cancelled turn may only be reported as cancelled on the backend's own terminal evidence. These
// counterexamples pin the evidence rules, including the shapes a Pi RPC peer can produce but that no
// end-to-end fixture reaches: a stream that closes without any terminal event, an error event whose
// message is empty, a terminal frame the loop already read before the cancellation was handled, and
// the content frames that arrive while the backend is tearing the turn down.

import (
	"strings"
	"testing"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

func retireAfter(events ...codex.TurnEvent) <-chan codex.TurnEvent {
	stream := make(chan codex.TurnEvent, len(events))
	for _, event := range events {
		stream <- event
	}
	close(stream)
	return stream
}

func TestCancelTerminalWithoutAnyTerminalEventIsNotCancelled(t *testing.T) {
	terminal := waitForCancelTerminal(retireAfter(
		codex.TurnEvent{Type: codex.TurnEventTypeStarted},
		codex.TurnEvent{Type: codex.TurnEventTypeAgentMessageDelta, Message: "partial output"},
	))
	reason, failure := cancelTerminalResult(terminal)
	if reason != "" {
		t.Fatalf("a stream that never reported a terminal reason produced %q", reason)
	}
	if failure == "" {
		t.Fatalf("closing the stream alone was accepted as evidence of cancellation")
	}
}

func TestCancelTerminalWithEmptyErrorMessageIsStillAnError(t *testing.T) {
	terminal := waitForCancelTerminal(retireAfter(
		codex.TurnEvent{Type: codex.TurnEventTypeError},
	))
	if !terminal.failed {
		t.Fatalf("an error event without a message was not recorded as an error: %+v", terminal)
	}
	reason, failure := cancelTerminalResult(terminal)
	if reason != "" {
		t.Fatalf("empty-message error produced a stopReason: %q", reason)
	}
	if failure == "" {
		t.Fatalf("empty-message error produced no failure to report")
	}
}

func TestCancelTerminalReportsTheBackendOwnReason(t *testing.T) {
	cases := []struct {
		backend  string
		expected string
	}{
		{backend: "cancelled", expected: "cancelled"},
		{backend: "end_turn", expected: "end_turn"},
	}
	for _, tc := range cases {
		terminal := waitForCancelTerminal(retireAfter(codex.TurnEvent{
			Type:       codex.TurnEventTypeCompleted,
			StopReason: tc.backend,
		}))
		reason, failure := cancelTerminalResult(terminal)
		if failure != "" {
			t.Fatalf("%s terminal reported a failure: %q", tc.backend, failure)
		}
		if reason != tc.expected {
			t.Fatalf("backend reason %s mapped to %q want %q", tc.backend, reason, tc.expected)
		}
	}
}

// TestCancelTerminalSeededFromAFrameAlreadyRead keeps the race honest: when the terminal frame is
// already off the stream by the time the cancellation is handled, it must still be the backend's own
// reason that is reported, not a cancellation the lifecycle would otherwise write over it.
func TestCancelTerminalSeededFromAFrameAlreadyRead(t *testing.T) {
	terminal := waitForCancelTerminal(
		retireAfter(),
		codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "end_turn"},
	)
	reason, failure := cancelTerminalResult(terminal)
	if failure != "" {
		t.Fatalf("seeded terminal reported a failure: %q", failure)
	}
	if reason != "end_turn" {
		t.Fatalf("a frame read before the cancellation was taken over by it: %q", reason)
	}
}

// TestCancelTerminalKeepsTheErrorTheCancelledCompletionFollows replays a possible backend frame order
// when a turn fails: an error event, then a completion that labels the turn cancelled,
// then the stream closes. The error is the fact the client must be given; a cancelled completion that
// follows it describes how the backend tore the turn down, not whether the turn succeeded.
func TestCancelTerminalKeepsTheErrorTheCancelledCompletionFollows(t *testing.T) {
	terminal := waitForCancelTerminal(retireAfter(
		codex.TurnEvent{Type: codex.TurnEventTypeError, Message: "backend error: upstream refused the prompt"},
		codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "cancelled"},
	))
	reason, failure := cancelTerminalResult(terminal)
	if reason != "" {
		t.Fatalf("a turn the backend reported an error for was answered with a stopReason: %q", reason)
	}
	if !strings.Contains(failure, "backend error") {
		t.Fatalf("the error the backend reported was replaced by %q", failure)
	}
}

// TestCancelTerminalReportsACancellationWithNoError is the contrast the rule above must not swallow: a
// backend that only reports a cancelled completion did cancel the turn, and that is still reported as
// cancelled rather than as a failure.
func TestCancelTerminalReportsACancellationWithNoError(t *testing.T) {
	terminal := waitForCancelTerminal(retireAfter(
		codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "cancelled"},
	))
	reason, failure := cancelTerminalResult(terminal)
	if failure != "" {
		t.Fatalf("a cleanly cancelled turn reported a failure: %q", failure)
	}
	if reason != "cancelled" {
		t.Fatalf("reason=%q, want the cancellation the backend reported", reason)
	}
}

// TestCancelTerminalProjectsLateFrames covers the part of the normal branch a cancelled turn must not
// lose: text, item and usage frames that arrive after the cancellation still reach the client.
func TestCancelTerminalProjectsLateFrames(t *testing.T) {
	terminal := waitForCancelTerminal(retireAfter(
		codex.TurnEvent{Type: codex.TurnEventTypeAgentMessageDelta, Delta: "late text"},
		codex.TurnEvent{Type: codex.TurnEventTypeItemStarted, ItemID: "item-1", ItemType: "commandExecution"},
		codex.TurnEvent{
			Type:       codex.TurnEventTypeTokenUsageUpdated,
			TokenUsage: &codex.ThreadTokenUsage{Total: codex.TokenUsageBreakdown{TotalTokens: 42}},
		},
		codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "end_turn"},
	))
	if len(terminal.pending) != 3 {
		t.Fatalf("late frames were not kept for delivery: %+v", terminal.pending)
	}

	lifecycle := newTurnLifecycle("session-1", "turn-1")
	updates := cancelTerminalUpdates(lifecycle, terminal.pending)
	if len(updates) != 3 {
		t.Fatalf("late frames did not all reach the client: %+v", updates)
	}
	if updates[0].Type != sessionUpdateTypeMessage || updates[0].Delta != "late text" {
		t.Fatalf("late text was not projected: %+v", updates[0])
	}
	if updates[1].Status != "item_started" || updates[1].ItemID != "item-1" {
		t.Fatalf("late tool frame was not projected: %+v", updates[1])
	}
	if updates[2].Type != sessionUpdateTypeUsage {
		t.Fatalf("late usage frame was not projected: %+v", updates[2])
	}
	if lifecycle.lastUsage == nil {
		t.Fatalf("the reply of a completed turn lost its usage")
	}
}
