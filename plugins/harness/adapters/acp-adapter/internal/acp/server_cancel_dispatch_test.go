package acp

// The cancellation is requested by closing a context, and the prompt loop waits on that context and on
// the backend stream in the same select. When both are ready the runtime picks either, so a frame read
// at the cancellation instant — an approval request, or the closed stream itself — can reach the loop
// before the cancellation has been handled. These counterexamples drive that real dispatch (an
// in-process server, a mock backend that parks on the turn context) instead of the wait helper, and pin
// what must hold whichever arm won: the turn is ended by the retirement path, an approval that arrived
// on a cancelled turn is never answered and never re-asked, and the reply is never written while the
// backend still holds the run.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/beyond5959/acp-adapter/internal/bridge"
	"github.com/beyond5959/acp-adapter/internal/codex"
)

// cancelRaceIterations is how often each shape is replayed. Which arm of the select takes a frame that
// became ready together with the cancellation is the runtime's choice, and on this machine the frame arm
// wins a few replays in twenty, so the count — not any single replay — is what makes the counterexample
// reliable: every replay must pass, and a bridge that only handles the other arm fails at least one.
const cancelRaceIterations = 120

// cancelRaceRetireGap is how long the mock backend keeps the run alive after it was asked to stop. The
// reply of a cancelled turn must never be written inside that window, and a reply that skipped the wait
// is written a hundred times sooner than the gap ends.
const cancelRaceRetireGap = 40 * time.Millisecond

// cancelDispatchErrorReplays is how often the failing-turn shape is replayed. Unlike the two shapes above
// it is not arm-selective — both arms of the select hand the same frames to the same teardown — so this
// only has to cover the arm that the runtime happens to take.
const cancelDispatchErrorReplays = 20

// cancelRaceDrain is how long the test keeps reading after a reply, in case the bridge queued something
// for the client on its way out.
const cancelRaceDrain = 10 * time.Millisecond

const cancelRaceApprovalCommand = "rm -rf /tmp/dispatch-race"

// cancelRaceAppClient emits one frame at the exact instant the turn context is closed, and retires the
// run only later. Everything it does on the bridge's behalf is recorded, so a cancelled turn that kept
// talking to the backend is visible in the test.
type cancelRaceAppClient struct {
	*stdioMockAppClient

	raceFrame *codex.TurnEvent
	terminal  *codex.TurnEvent
	retireGap time.Duration

	mu        sync.Mutex
	running   bool
	retiredAt time.Time
	answered  []string
	turns     int
}

func newCancelRaceAppClient(raceFrame, terminal *codex.TurnEvent, gap time.Duration) *cancelRaceAppClient {
	return &cancelRaceAppClient{
		stdioMockAppClient: &stdioMockAppClient{},
		raceFrame:          raceFrame,
		terminal:           terminal,
		retireGap:          gap,
	}
}

func (m *cancelRaceAppClient) ThreadStart(ctx context.Context, cwd string, options codex.RunOptions) (string, error) {
	return "thread-race", nil
}

func (m *cancelRaceAppClient) TurnStart(
	ctx context.Context,
	threadID string,
	input []codex.UserInput,
	options codex.RunOptions,
) (string, <-chan codex.TurnEvent, error) {
	m.mu.Lock()
	if m.running {
		m.mu.Unlock()
		return "", nil, errors.New("race session already has an active run")
	}
	m.turns++
	turnIndex := m.turns
	m.running = true
	m.mu.Unlock()

	events := make(chan codex.TurnEvent, 4)
	turnID := fmt.Sprintf("turn-race-%d", turnIndex)
	go func() {
		defer func() {
			m.mu.Lock()
			m.retiredAt = time.Now()
			m.running = false
			m.mu.Unlock()
			close(events)
		}()
		send := func(event codex.TurnEvent) {
			event.ThreadID = threadID
			event.TurnID = turnID
			events <- event
		}
		send(codex.TurnEvent{Type: codex.TurnEventTypeStarted})
		if turnIndex > 1 {
			// A turn after the first is not part of the race: the follow-up a client sends once it read
			// the terminal reply is served the way a healthy backend serves it, so the test can check the
			// bridge actually completed it rather than merely accepted it.
			send(codex.TurnEvent{Type: codex.TurnEventTypeAgentMessageDelta, Delta: "follow-up output"})
			send(codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "end_turn"})
			return
		}
		<-ctx.Done()
		if m.raceFrame != nil {
			send(*m.raceFrame)
		}
		if m.retireGap > 0 {
			time.Sleep(m.retireGap)
		}
		if m.terminal != nil {
			send(*m.terminal)
		}
	}()
	return turnID, events, nil
}

// TurnInterrupt returns as soon as the interrupt request is delivered, the way the Codex
// clients do: it does not wait for the run to retire, so the retirement wait is the bridge's own.
func (m *cancelRaceAppClient) TurnInterrupt(ctx context.Context, threadID, turnID string) error {
	return nil
}

func (m *cancelRaceAppClient) ApprovalRespond(
	ctx context.Context,
	approvalID string,
	decision codex.ApprovalDecision,
) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.answered = append(m.answered, approvalID+":"+string(decision))
	return nil
}

func (m *cancelRaceAppClient) answeredApprovals() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	return append([]string(nil), m.answered...)
}

func (m *cancelRaceAppClient) retired() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return !m.retiredAt.IsZero()
}

type cancelRaceHarness struct {
	t        *testing.T
	writer   *io.PipeWriter
	messages chan RPCMessage
	readErrs chan error

	// replies holds whatever reply the reader picked up while waiting for a different one: the bridge
	// answers the cancellation and the prompt in whatever order the two goroutines finish.
	replies   map[string]RPCMessage
	sessionID string
}

func startCancelRaceHarness(t *testing.T, app appClient) *cancelRaceHarness {
	t.Helper()

	clientToServerReader, clientToServerWriter := io.Pipe()
	serverToClientReader, serverToClientWriter := io.Pipe()
	ctx, cancelServe := context.WithCancel(context.Background())
	t.Cleanup(func() {
		cancelServe()
		_ = clientToServerReader.Close()
		_ = clientToServerWriter.Close()
		_ = serverToClientReader.Close()
		_ = serverToClientWriter.Close()
	})

	server := NewServer(
		NewStdioCodec(clientToServerReader, serverToClientWriter),
		app,
		bridge.NewStore(),
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		ServerOptions{
			PatchApplyMode:  "appserver",
			InitialAuthMode: "chatgpt_subscription",
		},
	)
	go func() {
		_ = server.Serve(ctx)
	}()

	messages := make(chan RPCMessage, 64)
	readErrs := make(chan error, 1)
	go scanRPCStream(serverToClientReader, messages, readErrs)

	h := &cancelRaceHarness{
		t:        t,
		writer:   clientToServerWriter,
		messages: messages,
		readErrs: readErrs,
		replies:  map[string]RPCMessage{},
	}

	// A notices-capable client, so the frame that reports the turn as started reaches the wire: the test
	// waits for it before cancelling, to be sure the turn is registered as cancellable.
	writeRPCRequest(t, clientToServerWriter, "1", "initialize", map[string]any{
		"protocolVersion": 1,
		"clientCapabilities": map[string]any{
			"session": map[string]any{"notices": map[string]any{}},
		},
	})
	h.decodeReply("1", &InitializeResult{}, nil)

	writeRPCRequest(t, clientToServerWriter, "2", "session/new", map[string]any{"cwd": "/tmp/workspace"})
	var newResult SessionNewResult
	h.decodeReply("2", &newResult, nil)
	if newResult.SessionID == "" {
		t.Fatalf("session/new returned no sessionId")
	}
	h.sessionID = newResult.SessionID
	return h
}

func (h *cancelRaceHarness) write(id, method string, params any) {
	h.t.Helper()
	writeRPCRequest(h.t, h.writer, id, method, params)
}

func (h *cancelRaceHarness) prompt(id string, text string) {
	h.t.Helper()
	h.write(id, "session/prompt", map[string]any{"sessionId": h.sessionID, "prompt": text})
}

func (h *cancelRaceHarness) cancel(id string) {
	h.t.Helper()
	h.write(id, "session/cancel", map[string]any{"sessionId": h.sessionID})
}

// readOne returns the next frame. A notification is kept in seen for the caller's assertions; a reply is
// recorded so that whoever asked for it can still find it, whichever order the bridge answered in.
func (h *cancelRaceHarness) readOne(budget time.Duration, seen *[]RPCMessage) RPCMessage {
	h.t.Helper()
	timer := time.NewTimer(budget)
	defer timer.Stop()
	select {
	case err := <-h.readErrs:
		h.t.Fatalf("rpc stream error: %v", err)
	case msg, ok := <-h.messages:
		if !ok {
			h.t.Fatalf("rpc stream closed")
		}
		h.record(msg, seen)
		return msg
	case <-timer.C:
		h.t.Fatalf("timed out waiting for an rpc frame")
	}
	return RPCMessage{}
}

func (h *cancelRaceHarness) record(msg RPCMessage, seen *[]RPCMessage) {
	if msg.Method == "" {
		if msg.ID != nil {
			h.replies[messageIDString(msg.ID)] = msg
		}
		return
	}
	if seen != nil {
		*seen = append(*seen, msg)
	}
}

// awaitReply reads frames until the reply to id arrives, collecting every notification seen on the way.
func (h *cancelRaceHarness) awaitReply(id string, budget time.Duration, seen *[]RPCMessage) RPCMessage {
	h.t.Helper()
	deadline := time.Now().Add(budget)
	for {
		if msg, ok := h.replies[id]; ok {
			delete(h.replies, id)
			return msg
		}
		remaining := time.Until(deadline)
		if remaining <= 0 {
			h.t.Fatalf("timed out waiting for the reply to %s", id)
			return RPCMessage{}
		}
		if msg := h.readOne(remaining, seen); msg.Method == "" && messageIDString(msg.ID) == id {
			delete(h.replies, id)
			return msg
		}
	}
}

func (h *cancelRaceHarness) decodeReply(id string, out any, seen *[]RPCMessage) {
	h.t.Helper()
	reply := h.awaitReply(id, 5*time.Second, seen)
	if reply.Error != nil {
		h.t.Fatalf("request %s failed: %s", id, reply.Error.Message)
	}
	if out != nil {
		if err := json.Unmarshal(reply.Result, out); err != nil {
			h.t.Fatalf("decode reply %s: %v", id, err)
		}
	}
}

// awaitTurnStarted blocks until the bridge reports this session's turn as started, which it does right
// after the turn became cancellable. Anything else the bridge happened to send — session/new announces
// the available commands after its own reply — is kept but not counted.
func (h *cancelRaceHarness) awaitTurnStarted(seen *[]RPCMessage) {
	h.t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			h.t.Fatalf("the turn never reported itself as started")
		}
		msg := h.readOne(remaining, seen)
		if msg.Method != methodSessionUpdate {
			continue
		}
		var update SessionUpdateParams
		if err := json.Unmarshal(msg.Params, &update); err != nil {
			continue
		}
		if update.SessionID == h.sessionID && update.Status == "turn_started" {
			return
		}
	}
}

// drain collects the frames the bridge already queued, so nothing written just before the reply can hide
// behind a boundary the test happened to read first.
func (h *cancelRaceHarness) drain(budget time.Duration, seen *[]RPCMessage) {
	h.t.Helper()
	deadline := time.Now().Add(budget)
	for {
		remaining := time.Until(deadline)
		if remaining <= 0 {
			return
		}
		timer := time.NewTimer(remaining)
		select {
		case msg := <-h.messages:
			timer.Stop()
			h.record(msg, seen)
		case err := <-h.readErrs:
			timer.Stop()
			h.t.Fatalf("rpc stream error: %v", err)
		case <-timer.C:
			return
		}
	}
}

// promptReply reads the reply to a prompt the caller already wrote, and returns whichever half of the
// ACP terminal state the bridge chose: a stopReason or an error.
func (h *cancelRaceHarness) promptReply(id string, seen *[]RPCMessage) (SessionPromptResult, *RPCError) {
	h.t.Helper()
	reply := h.awaitReply(id, 5*time.Second, seen)
	if reply.Error != nil {
		return SessionPromptResult{}, reply.Error
	}
	var result SessionPromptResult
	if err := json.Unmarshal(reply.Result, &result); err != nil {
		h.t.Fatalf("decode prompt reply: %v", err)
	}
	return result, nil
}

// awaitCancellation reads the reply to a session/cancel the caller already wrote and fails if the bridge
// did not accept it, which would mean the race was never entered at all.
func (h *cancelRaceHarness) awaitCancellation(id string, seen *[]RPCMessage) {
	h.t.Helper()
	var result SessionCancelResult
	h.decodeReply(id, &result, seen)
	if !result.Cancelled {
		h.t.Fatalf("the bridge did not accept the cancellation")
	}
}

func cancelRaceApprovalFrame() *codex.TurnEvent {
	return &codex.TurnEvent{
		Type:   codex.TurnEventTypeApprovalRequired,
		ItemID: "item-race",
		Approval: codex.ApprovalRequest{
			ApprovalID: "approval-race",
			ToolCallID: "item-race",
			Kind:       codex.ApprovalKindCommand,
			Command:    cancelRaceApprovalCommand,
		},
	}
}

// TestCancelDispatchApprovalFrameCannotEscapeTheRetirementPath replays the instant where the cancellation
// and an approval frame are both ready. The bridge may hand the frame to the loop or find the
// cancellation first; either way the turn has to end through the cancellation path, which waits for the
// run to retire and reports the backend's own reason. An approval that arrived on a cancelled turn must
// never be answered on the backend's behalf, and the client must never be asked to decide it again.
func TestCancelDispatchApprovalFrameCannotEscapeTheRetirementPath(t *testing.T) {
	terminal := &codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "cancelled"}
	for i := range cancelRaceIterations {
		t.Run(fmt.Sprintf("iteration-%02d", i+1), func(t *testing.T) {
			app := newCancelRaceAppClient(cancelRaceApprovalFrame(), terminal, cancelRaceRetireGap)
			h := startCancelRaceHarness(t, app)

			var seen []RPCMessage
			h.prompt("3", "race me")
			h.awaitTurnStarted(&seen)
			h.cancel("4")
			h.awaitCancellation("4", &seen)

			result, failure := h.promptReply("3", &seen)
			h.drain(cancelRaceDrain, &seen)
			if !app.retired() {
				t.Fatalf("the reply %q was written before the backend retired the run", result.StopReason)
			}
			if failure != nil {
				t.Fatalf("cancelled turn reported %q", failure.Message)
			}
			if result.StopReason != "cancelled" {
				t.Fatalf("stopReason=%q, want the backend's own terminal reason", result.StopReason)
			}
			if answered := app.answeredApprovals(); len(answered) > 0 {
				t.Fatalf("an approval that arrived on a cancelled turn was answered: %v", answered)
			}
			for _, msg := range seen {
				if msg.Method == methodSessionRequestPermission {
					t.Fatalf("a cancelled turn asked the client to decide its approval again")
				}
				if strings.Contains(string(msg.Params), cancelRaceApprovalCommand) {
					t.Fatalf("the approval of a cancelled turn reached the client: %s", msg.Params)
				}
			}
		})
	}
}

// TestCancelDispatchClosedStreamCannotEscapeTheRetirementPath replays the other arm: the stream closes at
// the same instant the cancellation lands. A stream that ends without ever reporting how the turn ended
// is not evidence of any terminal reason, so the loop must hand that closure to the cancellation path and
// report the cancellation as unconfirmed, rather than answering the prompt with a reason the backend never
// sent or announcing a terminal state it has no evidence for.
func TestCancelDispatchClosedStreamCannotEscapeTheRetirementPath(t *testing.T) {
	for i := range cancelRaceIterations {
		t.Run(fmt.Sprintf("iteration-%02d", i+1), func(t *testing.T) {
			app := newCancelRaceAppClient(nil, nil, 0)
			h := startCancelRaceHarness(t, app)

			var seen []RPCMessage
			h.prompt("3", "race me")
			h.awaitTurnStarted(&seen)
			h.cancel("4")
			h.awaitCancellation("4", &seen)

			result, failure := h.promptReply("3", &seen)
			h.drain(cancelRaceDrain, &seen)
			if failure == nil {
				t.Fatalf("a cancelled turn whose stream closed without a reason answered %q", result.StopReason)
			}
			if failure.Message != "turn cancellation not confirmed" {
				t.Fatalf("unexpected failure for the unconfirmed cancellation: %q", failure.Message)
			}
			for _, msg := range seen {
				var update SessionUpdateParams
				if err := json.Unmarshal(msg.Params, &update); err != nil {
					continue
				}
				if update.Status == "turn_cancelled" || update.Status == "turn_completed" {
					t.Fatalf("the bridge announced %q without terminal evidence", update.Status)
				}
			}
		})
	}
}

// TestCancelDispatchLateRetirementIsAwaitedBeforeTheReply pins the wait itself. The backend finishes the
// turn normally at the cancellation instant but keeps the run alive for a while: the reply may carry the
// reason the backend gave, but it may not be written while the run is still live, because that is the
// window in which the next message in the same session would be rejected by the backend.
func TestCancelDispatchLateRetirementIsAwaitedBeforeTheReply(t *testing.T) {
	terminal := &codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "end_turn"}
	for i := range cancelRaceIterations {
		t.Run(fmt.Sprintf("iteration-%02d", i+1), func(t *testing.T) {
			app := newCancelRaceAppClient(terminal, nil, cancelRaceRetireGap)
			h := startCancelRaceHarness(t, app)

			var seen []RPCMessage
			h.prompt("3", "race me")
			h.awaitTurnStarted(&seen)
			h.cancel("4")
			h.awaitCancellation("4", &seen)

			result, failure := h.promptReply("3", &seen)
			if !app.retired() {
				t.Fatalf("the reply of the cancelled turn was written while its run was still live")
			}
			if failure != nil {
				t.Fatalf("the cancelled turn reported %q", failure.Message)
			}
			if result.StopReason != "end_turn" {
				t.Fatalf("stopReason=%q, want the reason the backend reported itself", result.StopReason)
			}
		})
	}
}

// cancelRaceBackendFailure is the message the failing shape below hands the bridge, so the test can tell
// the backend's own failure from any label the bridge might invent for it.
const cancelRaceBackendFailure = "backend error: upstream refused the prompt"

// TestCancelDispatchBackendErrorOutlivesTheCancelledCompletion drives the frame order a backend
// can produce for a failed turn — an error event followed by a cancelled completion.
// The cancellation may be taken by either arm of the select, but both
// hand the same two frames to the same teardown, so this shape is not arm-selective: what has to hold is
// that the error the backend reported survives the completion that follows it. A turn that failed must not
// be answered as a cancellation that succeeded.
func TestCancelDispatchBackendErrorOutlivesTheCancelledCompletion(t *testing.T) {
	errorFrame := &codex.TurnEvent{Type: codex.TurnEventTypeError, Message: cancelRaceBackendFailure}
	terminal := &codex.TurnEvent{Type: codex.TurnEventTypeCompleted, StopReason: "cancelled"}
	for i := range cancelDispatchErrorReplays {
		t.Run(fmt.Sprintf("iteration-%02d", i+1), func(t *testing.T) {
			app := newCancelRaceAppClient(errorFrame, terminal, cancelRaceRetireGap)
			h := startCancelRaceHarness(t, app)

			var seen []RPCMessage
			h.prompt("3", "fail me")
			h.awaitTurnStarted(&seen)
			h.cancel("4")
			h.awaitCancellation("4", &seen)

			reply := h.awaitReply("3", 5*time.Second, &seen)
			h.drain(cancelRaceDrain, &seen)
			if reply.Error == nil {
				t.Fatalf("a turn the backend errored was answered as a terminal state: %s", reply.Result)
			}
			if !app.retired() {
				t.Fatalf("the reply of the cancelled turn was written while its run was still live")
			}
			// The bridge's own label is fine; losing what the backend said is not.
			if !strings.Contains(fmt.Sprintf("%v", reply.Error.Data), cancelRaceBackendFailure) {
				t.Fatalf("the backend's failure message was dropped: %v", reply.Error.Data)
			}
			if strings.Contains(string(reply.Result), `"cancelled"`) {
				t.Fatalf("the reply of a failed turn claimed a cancellation: %s", reply.Result)
			}
			for _, msg := range seen {
				var update SessionUpdateParams
				if err := json.Unmarshal(msg.Params, &update); err != nil {
					continue
				}
				if update.Status == "turn_cancelled" {
					t.Fatalf("a turn the backend errored was announced as cancelled")
				}
			}
		})
	}
}
