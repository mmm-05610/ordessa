package acp

// A terminal reply is the bridge's own answer for the session's turn slot: it releases the slot and then
// leaves, so the slot used to stay held for the length of a goroutine return after the client had already
// been told the turn was over, and a client that obeyed the protocol — send as soon as the terminal state
// arrives — was answered with "begin turn failed". These counterexamples replay exactly that client
// behaviour on both ways a turn can end, with no delay and no retry between the reply and the next message.
//
// What these pin is the bridge slot only. A terminal reply is not a promise that the backend is finished:
// a cancellation the backend never confirmed is answered with an error while its run may still be live, and
// the next message is refused by the backend on those grounds (pinned in
// test/integration/pi_approval_routing_test.go, not here).

import (
	"context"
	"fmt"
	"sync"
	"testing"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

// turnSlotIterations is how often each shape is replayed. The window is a goroutine unwind, so a broken
// bridge is caught on a fraction of replays rather than all of them. Measured on this machine with the
// ordering reverted: the normal path lost about 4 runs in 10, the cancelled path about 1 in 10 (as few as
// 2 in 60 on one run). This count is what makes a clean pass evidence rather than luck — at the worst
// observed rate a broken bridge still fails one of these replays with probability above 0.999.
const turnSlotIterations = 200

// turnSlotReject is the label the bridge puts on a message it refuses because the previous turn still
// holds the slot. It is matched explicitly so a failure names the race instead of a generic error.
const turnSlotReject = "begin turn failed"

// slotAppClient completes every turn the way a healthy backend does, and gives each turn its own id so
// releasing one turn's slot can never be mistaken for releasing the next one's.
type slotAppClient struct {
	*stdioMockAppClient

	mu    sync.Mutex
	turns int
}

func (m *slotAppClient) ThreadStart(ctx context.Context, cwd string, options codex.RunOptions) (string, error) {
	return "thread-slot", nil
}

func (m *slotAppClient) TurnStart(
	ctx context.Context,
	threadID string,
	input []codex.UserInput,
	options codex.RunOptions,
) (string, <-chan codex.TurnEvent, error) {
	m.mu.Lock()
	m.turns++
	turnID := fmt.Sprintf("turn-slot-%d", m.turns)
	m.mu.Unlock()

	events := make(chan codex.TurnEvent, 3)
	go func() {
		defer close(events)
		events <- codex.TurnEvent{Type: codex.TurnEventTypeStarted, ThreadID: threadID, TurnID: turnID}
		events <- codex.TurnEvent{
			Type:     codex.TurnEventTypeAgentMessageDelta,
			ThreadID: threadID,
			TurnID:   turnID,
			Delta:    "turn output",
		}
		events <- codex.TurnEvent{
			Type:       codex.TurnEventTypeCompleted,
			ThreadID:   threadID,
			TurnID:     turnID,
			StopReason: "end_turn",
		}
	}()
	return turnID, events, nil
}

// assertFollowUpAccepted sends the next message the instant the previous terminal reply was read, and
// requires the bridge to have finished it. The send is deliberately the very next statement: a delay or a
// retry here would hide the race instead of testing it.
func assertFollowUpAccepted(t *testing.T, h *cancelRaceHarness, seen *[]RPCMessage, id string) {
	t.Helper()

	h.prompt(id, "follow-up sent straight from the terminal reply")
	result, failure := h.promptReply(id, seen)
	if failure != nil {
		if failure.Message == turnSlotReject {
			t.Fatalf("the message sent as soon as the terminal reply arrived was refused: the previous turn still held the slot")
		}
		t.Fatalf("the follow-up turn failed: %s", failure.Message)
	}
	if result.StopReason != "end_turn" {
		t.Fatalf("the follow-up turn ended with %q, want a normally completed turn", result.StopReason)
	}
}

func TestTurnSlotNormallyCompletedTurnFreesTheSlotBeforeTheReply(t *testing.T) {
	for i := range turnSlotIterations {
		t.Run(fmt.Sprintf("iteration-%02d", i+1), func(t *testing.T) {
			h := startCancelRaceHarness(t, &slotAppClient{stdioMockAppClient: &stdioMockAppClient{}})

			var seen []RPCMessage
			h.prompt("3", "first message")
			result, failure := h.promptReply("3", &seen)
			if failure != nil {
				t.Fatalf("the first turn failed: %s", failure.Message)
			}
			if result.StopReason != "end_turn" {
				t.Fatalf("the first turn ended with %q", result.StopReason)
			}

			assertFollowUpAccepted(t, h, &seen, "4")
		})
	}
}

func TestTurnSlotCancelledTurnFreesTheSlotBeforeTheReply(t *testing.T) {
	terminal := &codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "cancelled"}
	for i := range turnSlotIterations {
		t.Run(fmt.Sprintf("iteration-%02d", i+1), func(t *testing.T) {
			app := newCancelRaceAppClient(nil, terminal, cancelRaceRetireGap)
			h := startCancelRaceHarness(t, app)

			var seen []RPCMessage
			h.prompt("3", "cancel me")
			h.awaitTurnStarted(&seen)
			h.cancel("4")
			h.awaitCancellation("4", &seen)

			result, failure := h.promptReply("3", &seen)
			if failure != nil {
				t.Fatalf("the cancelled turn reported %q", failure.Message)
			}
			if result.StopReason != "cancelled" {
				t.Fatalf("stopReason=%q, want the cancellation the backend confirmed", result.StopReason)
			}
			if !app.retired() {
				t.Fatalf("the reply was written while the backend still held the run")
			}

			// The cancelled turn is the case that matters most: the cancellation acknowledgement is not
			// the end of the turn, and the terminal reply is, so the slot has to be free by the time that
			// reply leaves — the run behind it already retired.
			assertFollowUpAccepted(t, h, &seen, "5")
		})
	}
}
