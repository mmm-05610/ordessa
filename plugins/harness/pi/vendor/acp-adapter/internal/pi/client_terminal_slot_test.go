package pi

// The bridge is not the only holder of a session's turn slot. Pi keeps one too: while rpcSession.active is
// set, beginRun refuses the next run. A terminal frame is what the bridge answers the turn with, so a
// client that sends its next message as soon as it reads that frame is admitted by the bridge and then
// judged by this slot — which means the slot has to be released before the frame can be read at all.
//
// These counterexamples drive the real delivery path and look at the slot at the instant the frame first
// becomes readable. The stream is left unbuffered so that is the earliest possible moment: releasing the
// slot before the delivery is then a guarantee rather than an outcome of scheduling, while a release that
// still sits after it can only be caught by the replay below.

import (
	"testing"
	"time"

	"github.com/beyond5959/acp-adapter/internal/codex"
)

// terminalSlotReplays is how often the delivery is replayed. Whether the reader or the release path wins
// the session slot after the handoff is the runtime's choice, and on this machine the release wins roughly
// ninety-nine deliveries in a hundred, so the count is the evidence: a slot released after the frame is
// caught by at least one of these with overwhelming probability, and a slot released before it never is.
const terminalSlotReplays = 4000

// terminalSlotSession builds a session that owns one run, with a stream the test consumes directly. The
// session is closed so the usage lookup completeRun makes short-circuits instead of talking to a Pi
// process: nothing here needs a backend, only the ordering inside this client.
func terminalSlotSession() (*rpcSession, *activeRun) {
	sess := &rpcSession{threadID: "thread-slot", closed: true, pending: map[string]chan rpcEnvelope{}}
	run := newActiveRun("turn-slot", runKindPrompt, false)
	run.events = make(chan codex.TurnEvent)
	sess.active = run
	return sess, run
}

// slotAtDelivery hands the run's next frame to a reader that reports what the session slot looks like the
// moment that frame is visible. A nil answer means a client may send its next message at that instant; a
// non-nil answer means Pi would refuse it while its own turn was already reported as over.
func slotAtDelivery(t *testing.T, sess *rpcSession, run *activeRun) (*activeRun, codex.TurnEvent) {
	t.Helper()

	type observation struct {
		slot  *activeRun
		event codex.TurnEvent
	}
	observed := make(chan observation, 1)
	go func() {
		event, ok := <-run.events
		if !ok {
			observed <- observation{}
			return
		}
		observed <- observation{slot: sess.currentRun(), event: event}
	}()

	select {
	case got := <-observed:
		return got.slot, got.event
	case <-time.After(10 * time.Second):
		t.Fatalf("the terminal frame was never delivered")
		return nil, codex.TurnEvent{}
	}
}

func TestCompletedFrameNeverPrecedesTheRunSlotRelease(t *testing.T) {
	for range terminalSlotReplays {
		sess, run := terminalSlotSession()
		go sess.completeRun(run, "end_turn", "")

		slot, event := slotAtDelivery(t, sess, run)
		if event.Type != codex.TurnEventTypeCompleted {
			t.Fatalf("the frame handed over was %q, not the terminal one", event.Type)
		}
		if slot != nil {
			t.Fatalf("the terminal frame was readable while Pi still held the run slot: the next message would be refused")
		}
	}
}

// TestStreamStillClosesAfterTheTerminalFrame keeps the other half of the same seam: releasing the slot
// early must not retire the stream before its last frame, because a cancelled turn treats the close as the
// proof that the backend stopped.
func TestStreamStillClosesAfterTheTerminalFrame(t *testing.T) {
	for range terminalSlotReplays {
		sess, run := terminalSlotSession()
		go sess.completeRun(run, "end_turn", "")

		_, event := slotAtDelivery(t, sess, run)
		if event.Type != codex.TurnEventTypeCompleted {
			t.Fatalf("the frame handed over was %q, not the terminal one", event.Type)
		}
		select {
		case _, ok := <-run.events:
			if ok {
				t.Fatalf("a second frame followed the terminal one")
			}
		case <-time.After(10 * time.Second):
			t.Fatalf("the stream stayed open after the terminal frame: a cancelled turn would never see the run retire")
		}
	}
}
