package pi

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/beyond5959/acp-adapter/internal/codex"
	"strings"
	"testing"
)

type configurationRPCWriter struct {
	reasoning             bool
	stateFailure          bool
	missingModel          bool
	emptyModels           bool
	modelsFailure         bool
	sess                  *rpcSession
	model                 string
	effort                string
	commands              []string
	noEffect              bool
	getterFailureAfterSet bool
	lostReceipt           bool
	busy                  bool
}

func (w *configurationRPCWriter) Close() error { return nil }
func (w *configurationRPCWriter) Write(raw []byte) (int, error) {
	var request map[string]any
	if err := json.Unmarshal(raw, &request); err != nil {
		return 0, err
	}
	kind := request["type"].(string)
	w.commands = append(w.commands, kind)
	var data any
	switch kind {
	case "get_state":
		if w.stateFailure {
			return 0, errors.New("native state observation unavailable")
		}
		if w.missingModel {
			data = rpcState{ThinkingLevel: w.effort}
			break
		}
		if w.getterFailureAfterSet && (w.model == "new" || w.effort == "high") {
			return 0, errors.New("get_state lost")
		}
		data = rpcState{Model: &rpcModel{Provider: "test", ID: w.model, Reasoning: w.reasoning}, ThinkingLevel: w.effort, IsStreaming: w.busy}
	case "get_available_models":
		if w.modelsFailure {
			return 0, errors.New("existing native catalog unavailable")
		}
		if w.emptyModels {
			data = map[string]any{"models": []rpcModel{}}
		} else {
			data = map[string]any{"models": []rpcModel{{Provider: "test", ID: "old"}, {Provider: "test", ID: "new"}}}
		}
	case "set_model":
		if !w.noEffect {
			w.model = request["modelId"].(string)
		}
	case "set_thinking_level":
		if !w.noEffect {
			w.effort = request["level"].(string)
		}
	default:
		return 0, errors.New("unexpected RPC command")
	}
	if w.lostReceipt && strings.HasPrefix(kind, "set_") {
		return 0, errors.New("setter receipt lost after effect")
	}
	payload, _ := json.Marshal(data)
	success := true
	w.sess.resolvePending(request["id"].(string), rpcEnvelope{Success: &success, Data: payload})
	return len(raw), nil
}
func configurationRPC() (*Client, *configurationRPCWriter) {
	client := NewClient(Config{})
	sess := &rpcSession{client: client, threadID: "existing", pending: map[string]chan rpcEnvelope{}, closeCh: make(chan struct{})}
	writer := &configurationRPCWriter{sess: sess, model: "old", effort: "off", reasoning: true}
	sess.stdin = writer
	client.registerSession("existing", sess)
	return client, writer
}
func setterCount(commands []string) int {
	n := 0
	for _, command := range commands {
		if strings.HasPrefix(command, "set_") {
			n++
		}
	}
	return n
}
func TestNativeConfigurationObservedImmediateAndExternalEdit(t *testing.T) {
	client, wire := configurationRPC()
	ctx := context.Background()
	before, err := client.SessionConfiguration(ctx, "existing")
	if err != nil || before.Model != "test/old" || before.Effort != "off" {
		t.Fatalf("native read: %+v %v", before, err)
	}
	after, err := client.SetSessionConfigOption(ctx, "existing", "model", "test/new")
	if err != nil || after.Model != "test/new" || setterCount(wire.commands) != 1 {
		t.Fatalf("native model effect: %+v %v %v", after, err, wire.commands)
	}
	after, err = client.SetSessionConfigOption(ctx, "existing", "thought_level", "high")
	if err != nil || after.Effort != "high" || setterCount(wire.commands) != 2 {
		t.Fatalf("native effort effect: %+v %v %v", after, err, wire.commands)
	}
	wire.model = "old"
	wire.effort = "low"
	external, err := client.SessionConfiguration(ctx, "existing")
	if err != nil || external.Model != before.Model || external.Effort != "low" || setterCount(wire.commands) != 2 {
		t.Fatalf("external edit not observed: %+v %v", external, err)
	}
}
func TestNativeConfigurationUnconfirmedEffectsNeverReplay(t *testing.T) {
	for _, scenario := range []string{"ack-noeffect", "getter-failure", "lost-receipt"} {
		t.Run(scenario, func(t *testing.T) {
			client, wire := configurationRPC()
			wire.noEffect = scenario == "ack-noeffect"
			wire.getterFailureAfterSet = scenario == "getter-failure"
			wire.lostReceipt = scenario == "lost-receipt"
			_, err := client.SetSessionConfigOption(context.Background(), "existing", "thought_level", "high")
			if err == nil || setterCount(wire.commands) != 1 {
				t.Fatalf("unconfirmed setter accepted/replayed: %v %v", err, wire.commands)
			}
			wire.getterFailureAfterSet = false
			observed, readErr := client.SessionConfiguration(context.Background(), "existing")
			expected := "high"
			if wire.noEffect {
				expected = "off"
			}
			if readErr != nil || observed.Effort != expected || setterCount(wire.commands) != 1 {
				t.Fatalf("query replayed/rolled back: %+v %v %v", observed, readErr, wire.commands)
			}
		})
	}
}
func TestNativeConfigurationRefusesMissingAndActiveSessions(t *testing.T) {
	client, wire := configurationRPC()
	ctx := context.Background()
	if _, err := client.SessionConfiguration(ctx, "missing"); err == nil {
		t.Fatal("missing read accepted")
	}
	if _, err := client.SetSessionConfigOption(ctx, "missing", "thought_level", "high"); err == nil {
		t.Fatal("missing setter accepted")
	}
	if len(wire.commands) != 0 || len(client.sessions) != 1 {
		t.Fatal("missing read/set spawned or touched session")
	}
	wire.sess.active = newActiveRun("turn", runKindPrompt, false)
	if _, err := client.SetSessionConfigOption(ctx, "existing", "thought_level", "high"); err == nil {
		t.Fatal("active setter accepted")
	}
	if len(wire.commands) != 0 {
		t.Fatal("active setter touched native state")
	}
	wire.sess.active = nil
	wire.busy = true
	if _, err := client.SetSessionConfigOption(ctx, "existing", "thought_level", "high"); err == nil || setterCount(wire.commands) != 0 {
		t.Fatal("native busy setter accepted")
	}
}

func TestStartupRunOptionsConfirmEffectAndDoNotRepeatSetters(t *testing.T) {
	client, wire := configurationRPC()
	options := codex.RunOptions{Model: "test/new", Effort: "high"}
	if err := client.applyRunOptions(context.Background(), wire.sess, options); err != nil {
		t.Fatal(err)
	}
	if wire.model != "new" || wire.effort != "high" || setterCount(wire.commands) != 2 {
		t.Fatalf("startup options not confirmed: %v", wire.commands)
	}
	if err := client.applyRunOptions(context.Background(), wire.sess, options); err != nil {
		t.Fatal(err)
	}
	if setterCount(wire.commands) != 2 {
		t.Fatalf("identical prompt options repeated setters: %v", wire.commands)
	}
	// Startup applies options before publishing/registering a ready thread. An ACK
	// without native effect must therefore fail this same startup path.
	client, wire = configurationRPC()
	wire.noEffect = true
	if err := client.applyRunOptions(context.Background(), wire.sess, options); err == nil || setterCount(wire.commands) != 1 {
		t.Fatalf("startup accepted ACK without effect/replayed: %v %v", err, wire.commands)
	}
}

func TestExistingSessionModelCatalogNeverSpawnsFallback(t *testing.T) {
	for _, failure := range []bool{false, true} {
		client, wire := configurationRPC()
		wire.reasoning = false
		client.cfg.PiBin = "/must-not-spawn-second-pi"
		wire.emptyModels = true
		wire.modelsFailure = failure
		models, err := client.ModelsList(context.Background())
		if failure {
			if err == nil || !strings.Contains(err.Error(), "existing native catalog unavailable") {
				t.Fatalf("catalog failure hidden by fallback spawn: %v", err)
			}
			if len(wire.commands) != 1 {
				t.Fatal("catalog error performed fallback observation")
			}
		} else {
			if err != nil || len(models) != 1 || models[0].ID != "test/old" || len(models[0].SupportedReasoningEfforts) != 1 || models[0].SupportedReasoningEfforts[0].Value != "off" {
				t.Fatalf("observed native capability missing: %v %+v", err, models)
			}
			if len(wire.commands) != 2 || wire.commands[1] != "get_state" {
				t.Fatal("empty catalog did not observe same native session")
			}
		}
		if wire.commands[0] != "get_available_models" || len(client.sessions) != 1 {
			t.Fatal("attached enumeration retried or changed session")
		}
	}
}

func TestEmptyCatalogUsesNativeCurrentModelReasoningCapabilities(t *testing.T) {
	for _, reasoning := range []bool{false, true} {
		client, wire := configurationRPC()
		client.cfg.PiBin = "/must-not-spawn-second-pi"
		wire.emptyModels = true
		wire.reasoning = reasoning
		models, err := client.ModelsList(context.Background())
		if err != nil || len(models) != 1 {
			t.Fatalf("native capabilities unavailable: %v %+v", err, models)
		}
		expected := []string{"off"}
		if reasoning {
			expected = []string{"off", "minimal", "low", "medium", "high"}
		}
		efforts := models[0].SupportedReasoningEfforts
		if len(efforts) != len(expected) {
			t.Fatalf("invented native capabilities: %+v", efforts)
		}
		for i, want := range expected {
			if efforts[i].Value != want {
				t.Fatalf("native effort[%d]=%s expected %s", i, efforts[i].Value, want)
			}
		}
		if len(client.modelsCache) != 0 {
			t.Fatal("observed current model cached as full selectable catalog")
		}
		// External native model edits must be observed at the next catalog request.
		wire.model = "external"
		wire.reasoning = !reasoning
		models, err = client.ModelsList(context.Background())
		if err != nil || len(models) != 1 || models[0].ID != "test/external" || len(wire.commands) != 4 || len(client.sessions) != 1 {
			t.Fatalf("stale observation or hidden process: %v %+v %v", err, models, wire.commands)
		}
	}
}

func TestEmptyCatalogRefusesFailedOrMissingNativeObservation(t *testing.T) {
	for _, missing := range []bool{false, true} {
		client, wire := configurationRPC()
		client.cfg.PiBin = "/must-not-spawn-second-pi"
		wire.emptyModels = true
		wire.stateFailure = !missing
		wire.missingModel = missing
		if models, err := client.ModelsList(context.Background()); err == nil || len(models) != 0 {
			t.Fatalf("unavailable native state advertised capabilities: %v %+v", err, models)
		}
		if len(wire.commands) != 2 || len(client.sessions) != 1 {
			t.Fatal("unavailable observation retried/spawned")
		}
	}
}

func TestNativeThinkingSetterRefusesUnsupportedCurrentModelBeforeWrite(t *testing.T) {
	client, wire := configurationRPC()
	// The prior observation/menu belongs to a reasoning model. An independent
	// native model change removes that capability before the requested write.
	if _, err := client.SessionConfiguration(context.Background(), "existing"); err != nil {
		t.Fatal(err)
	}
	wire.model = "external-nonreasoning"
	wire.reasoning = false
	wire.effort = "off"
	for _, value := range []string{"high", "minimal", "none", "xhigh"} {
		if _, err := client.SetSessionConfigOption(context.Background(), "existing", "thought_level", value); err == nil {
			t.Fatalf("unsupported native thinking %q accepted", value)
		}
	}
	if setterCount(wire.commands) != 0 || wire.effort != "off" || len(client.sessions) != 1 {
		t.Fatalf("unsupported native values wrote/replayed/changed session: %v", wire.commands)
	}
	for _, command := range wire.commands {
		if command != "get_state" {
			t.Fatalf("unsupported write used cached catalogue or side effect: %v", wire.commands)
		}
	}
}
