package acp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"reflect"
	"testing"

	"github.com/beyond5959/acp-adapter/internal/bridge"
	"github.com/beyond5959/acp-adapter/internal/codex"
)

type configurationReadApp struct {
	*stdioMockAppClient
	modelLists int
}

func (a *configurationReadApp) ModelsList(ctx context.Context) ([]codex.ModelOption, error) {
	a.modelLists++
	return a.stdioMockAppClient.ModelsList(ctx)
}

func configurationReadServer() (*Server, *bytes.Buffer, *configurationReadApp) {
	out := &bytes.Buffer{}
	app := &configurationReadApp{stdioMockAppClient: &stdioMockAppClient{}}
	server := NewServer(NewStdioCodec(bytes.NewReader(nil), out), app, bridge.NewStore(),
		slog.New(slog.NewJSONHandler(io.Discard, nil)), ServerOptions{})
	return server, out, app
}

func configurationReadReply(t *testing.T, server *Server, out *bytes.Buffer, params any) RPCMessage {
	t.Helper()
	out.Reset()
	raw, err := json.Marshal(params)
	if err != nil {
		t.Fatal(err)
	}
	id := json.RawMessage(`"read"`)
	server.handleRequest(context.Background(), RPCMessage{ID: &id, Method: methodSessionConfigurationRead, Params: raw})
	var reply RPCMessage
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &reply); err != nil {
		t.Fatalf("decode read reply: %v: %s", err, out.Bytes())
	}
	return reply
}

func TestSessionConfigurationReadUsesOriginalSnapshotAndSetterReadback(t *testing.T) {
	server, out, app := configurationReadServer()
	sessionID := server.sessions.Create("original-thread")
	server.setSessionConfig(sessionID, runtimeOptions{Model: "gpt-5.1-codex"})
	options := server.buildSessionConfigOptions(context.Background(), server.getSessionConfig(sessionID))
	server.setSessionConfigOptions(sessionID, options)
	assertRead := func(expected []SessionConfig) {
		t.Helper()
		calls := app.modelLists
		before := server.getSessionConfig(sessionID)
		reply := configurationReadReply(t, server, out, map[string]any{"sessionId": sessionID})
		if reply.Error != nil {
			t.Fatalf("read failed: %+v", reply.Error)
		}
		var result struct {
			SessionID     string          `json:"sessionId"`
			ConfigOptions []SessionConfig `json:"configOptions"`
		}
		if err := json.Unmarshal(reply.Result, &result); err != nil {
			t.Fatal(err)
		}
		if result.SessionID != sessionID || !reflect.DeepEqual(result.ConfigOptions, expected) {
			t.Fatalf("observation differs from original snapshot: %+v", result)
		}
		if app.modelLists != calls || !reflect.DeepEqual(before, server.getSessionConfig(sessionID)) {
			t.Fatal("read enumerated models or changed original runtime config")
		}
	}
	assertRead(options)
	assertRead(options)
	out.Reset()
	params, _ := json.Marshal(map[string]any{"sessionId": sessionID, "configId": "model", "value": "gpt-5"})
	server.handleSessionSetConfigOption(context.Background(), json.RawMessage(`"set"`), params)
	updated := server.getSessionConfigOptions(sessionID)
	if configOptionCurrentValue(updated, configIDModel) != "gpt-5" || server.getSessionConfig(sessionID).Model != "gpt-5" {
		t.Fatal("original setter did not update original configuration")
	}
	assertRead(updated)
	assertRead(updated)
}

func TestSessionConfigurationReadRefusesInvalidUnknownAndUnavailable(t *testing.T) {
	server, out, app := configurationReadServer()
	unavailable := server.sessions.Create("no-config-thread")
	for _, params := range []any{map[string]any{}, map[string]any{"sessionId": " "},
		map[string]any{"sessionId": "missing"}, map[string]any{"sessionId": unavailable},
		map[string]any{"sessionId": 42}, "invalid"} {
		reply := configurationReadReply(t, server, out, params)
		if reply.Error == nil {
			t.Fatalf("invalid/unavailable read accepted: %+v", params)
		}
	}
	if app.modelLists != 0 || len(server.sessionConfigOptions) != 0 || len(server.sessionConfigs) != 0 {
		t.Fatal("refused read called backend or created configuration state")
	}
}

// Only the immediate Pi capability uses native observations. The original mock
// above intentionally does not implement this port, preserving Codex semantics.
type nativeConfigurationApp struct {
	*configurationReadApp
	observed codex.RunOptions
	failure  error
	setters  int
}

func (a *nativeConfigurationApp) SessionConfiguration(context.Context, string) (codex.RunOptions, error) {
	return a.observed, a.failure
}
func (a *nativeConfigurationApp) SetSessionConfigOption(_ context.Context, _ string, id, value string) (codex.RunOptions, error) {
	a.setters++
	if a.failure != nil {
		return codex.RunOptions{}, a.failure
	}
	if id == configIDModel {
		a.observed.Model = value
	} else {
		a.observed.Effort = value
	}
	return a.observed, nil
}
func TestNativeConfigurationReadProjectsExternalStateWithoutEnumeration(t *testing.T) {
	server, out, app := configurationReadServer()
	native := &nativeConfigurationApp{configurationReadApp: app, observed: codex.RunOptions{Model: "gpt-5", Effort: "low"}}
	server.app = native
	sessionID := server.sessions.Create("original-thread")
	// Seed a real prior native effort; absent metadata is intentionally not a
	// license to invent a menu before the first observation.
	server.setSessionConfig(sessionID, runtimeOptions{Model: "gpt-5.1-codex", ThoughtLevel: "low"})
	server.setSessionConfigOptions(sessionID, server.buildSessionConfigOptions(context.Background(), server.getSessionConfig(sessionID)))
	lists := app.modelLists
	reply := configurationReadReply(t, server, out, map[string]any{"sessionId": sessionID})
	if reply.Error != nil {
		t.Fatalf("native observation failed: %+v", reply.Error)
	}
	var result struct {
		ObservationSource string          `json:"observationSource"`
		ConfigOptions     []SessionConfig `json:"configOptions"`
	}
	if err := json.Unmarshal(reply.Result, &result); err != nil {
		t.Fatal(err)
	}
	if result.ObservationSource != "pi-native-get_state" || configOptionCurrentValue(result.ConfigOptions, configIDModel) != "gpt-5" || configOptionCurrentValue(result.ConfigOptions, configIDThoughtLevel) != "low" {
		t.Fatalf("cache masked native state: %+v", result)
	}
	if app.modelLists != lists || native.setters != 0 || server.getSessionConfig(sessionID).Model != "gpt-5" {
		t.Fatal("observation enumerated/set native or retained stale turn options")
	}
	native.observed.Effort = "high"
	reply = configurationReadReply(t, server, out, map[string]any{"sessionId": sessionID})
	if reply.Error != nil || configOptionCurrentValue(server.getSessionConfigOptions(sessionID), configIDThoughtLevel) != "high" {
		t.Fatal("external edit not observed")
	}
	before := server.getSessionConfigOptions(sessionID)
	native.failure = errors.New("native read unavailable")
	reply = configurationReadReply(t, server, out, map[string]any{"sessionId": sessionID})
	if reply.Error == nil || !reflect.DeepEqual(before, server.getSessionConfigOptions(sessionID)) {
		t.Fatal("failed observation replaced original state")
	}
}
func TestNativeConfigurationSetterDoesNotPublishUnconfirmedState(t *testing.T) {
	server, out, app := configurationReadServer()
	native := &nativeConfigurationApp{configurationReadApp: app, observed: codex.RunOptions{Model: "gpt-5.1-codex", Effort: "low"}, failure: errors.New("ACK without effect")}
	server.app = native
	sessionID := server.sessions.Create("original-thread")
	before := runtimeOptions{Model: "gpt-5.1-codex", ThoughtLevel: "low"}
	server.setSessionConfig(sessionID, before)
	server.setSessionConfigOptions(sessionID, server.buildSessionConfigOptions(context.Background(), before))
	snapshot := server.getSessionConfigOptions(sessionID)
	params, _ := json.Marshal(map[string]any{"sessionId": sessionID, "configId": "model", "value": "gpt-5"})
	out.Reset()
	server.handleSessionSetConfigOption(context.Background(), json.RawMessage(`"set"`), params)
	var reply RPCMessage
	if err := json.Unmarshal(bytes.TrimSpace(out.Bytes()), &reply); err != nil {
		t.Fatal(err)
	}
	if reply.Error == nil || native.setters != 1 || !reflect.DeepEqual(before, server.getSessionConfig(sessionID)) || !reflect.DeepEqual(snapshot, server.getSessionConfigOptions(sessionID)) {
		t.Fatal("unconfirmed setter published success/state or replayed")
	}
}

// A native model is observable even when the credential-dependent selectable
// catalog is empty. The actual session owns the observation, not that catalog.
type emptyCatalogNativeApp struct {
	*nativeConfigurationApp
	lists        int
	catalogError error
}

func (a *emptyCatalogNativeApp) ModelsList(context.Context) ([]codex.ModelOption, error) {
	a.lists++
	return nil, a.catalogError
}
func (a *emptyCatalogNativeApp) ThreadResume(context.Context, string, string, codex.RunOptions) (codex.ThreadResumeResult, error) {
	return codex.ThreadResumeResult{}, nil
}
func TestNativeNewAndLoadSeedObservedOptionsWithEmptyCatalog(t *testing.T) {
	_, out, app := configurationReadServer()
	native := &emptyCatalogNativeApp{nativeConfigurationApp: &nativeConfigurationApp{configurationReadApp: app, observed: codex.RunOptions{Model: "test/observed", Effort: "off"}}}
	// New/load require authentication; use the existing explicit test startup
	// auth option instead of weakening the production admission requirement.
	server := NewServer(NewStdioCodec(bytes.NewReader(nil), out), native, bridge.NewStore(),
		slog.New(slog.NewJSONHandler(io.Discard, nil)), ServerOptions{InitialAuthMode: "chatgpt_subscription"})
	raw, _ := json.Marshal(map[string]any{"cwd": t.TempDir(), "mcpServers": []any{}})
	server.handleSessionNew(context.Background(), json.RawMessage(`"new"`), raw)
	var reply RPCMessage
	if err := json.NewDecoder(bytes.NewReader(out.Bytes())).Decode(&reply); err != nil {
		t.Fatal(err)
	}
	if reply.Error != nil {
		t.Fatalf("new refused: %+v", reply.Error)
	}
	var created SessionNewResult
	if err := json.Unmarshal(reply.Result, &created); err != nil {
		t.Fatal(err)
	}
	assertOptions := func(options []SessionConfig) {
		t.Helper()
		if configOptionCurrentValue(options, configIDModel) != "test/observed" || configOptionCurrentValue(options, configIDThoughtLevel) != "off" {
			t.Fatalf("native options missing with empty catalog: %+v", options)
		}
		for _, option := range options {
			if option.ID == configIDThoughtLevel && (len(option.Options) != 1 || option.Options[0].Value != "off") {
				t.Fatalf("empty native metadata advertised unsupported reasoning menu: %+v", option)
			}
		}
	}
	assertOptions(created.ConfigOptions)
	lists := native.lists
	observed := configurationReadReply(t, server, out, map[string]any{"sessionId": created.SessionID})
	if observed.Error != nil || native.lists != lists {
		t.Fatal("observation enumerated or failed")
	}
	assertOptions(server.getSessionConfigOptions(created.SessionID))
	// Resume result deliberately has no defaults, so native observation must seed
	// the options before their construction on both new and load paths.
	out.Reset()
	raw, _ = json.Marshal(map[string]any{"sessionId": created.SessionID, "cwd": t.TempDir(), "mcpServers": []any{}})
	server.handleSessionLoad(context.Background(), json.RawMessage(`"load"`), raw)
	decoder := json.NewDecoder(bytes.NewReader(out.Bytes()))
	found := false
	for {
		var message RPCMessage
		if err := decoder.Decode(&message); err == io.EOF {
			break
		} else if err != nil {
			t.Fatal(err)
		}
		if message.ID == nil || string(*message.ID) != `"load"` {
			continue
		}
		found = true
		if message.Error != nil {
			t.Fatalf("load refused: %+v", message.Error)
		}
		var loaded SessionLoadResult
		if err := json.Unmarshal(message.Result, &loaded); err != nil {
			t.Fatal(err)
		}
		assertOptions(loaded.ConfigOptions)
	}
	if !found {
		t.Fatal("load response missing")
	}
	assertOptions(server.getSessionConfigOptions(created.SessionID))
	if native.setters != 0 {
		t.Fatal("new/load observation secretly set native configuration")
	}
}

func TestNativeNewAndLoadRefuseUnavailableConfigurationCapabilities(t *testing.T) {
	for _, method := range []string{"new", "load"} {
		t.Run(method, func(t *testing.T) {
			_, out, app := configurationReadServer()
			native := &emptyCatalogNativeApp{nativeConfigurationApp: &nativeConfigurationApp{configurationReadApp: app, observed: codex.RunOptions{Model: "test/observed", Effort: "off"}}, catalogError: errors.New("native capability metadata unavailable")}
			server := NewServer(NewStdioCodec(bytes.NewReader(nil), out), native, bridge.NewStore(), slog.New(slog.NewJSONHandler(io.Discard, nil)), ServerOptions{InitialAuthMode: "chatgpt_subscription"})
			params := map[string]any{"cwd": t.TempDir(), "mcpServers": []any{}}
			if method == "load" {
				params["sessionId"] = server.sessions.Create("thread-1")
			}
			raw, _ := json.Marshal(params)
			if method == "new" {
				server.handleSessionNew(context.Background(), json.RawMessage(`"request"`), raw)
			} else {
				server.handleSessionLoad(context.Background(), json.RawMessage(`"request"`), raw)
			}
			var reply RPCMessage
			if err := json.NewDecoder(bytes.NewReader(out.Bytes())).Decode(&reply); err != nil {
				t.Fatal(err)
			}
			if reply.Error == nil {
				t.Fatalf("native %s published success despite missing capabilities: %s", method, out.Bytes())
			}
			if native.lists != 1 || native.setters != 0 {
				t.Fatal("failed capability lookup retried or set native state")
			}
			if len(server.sessionConfigOptions) != 0 {
				t.Fatal("generic capability template published after native metadata failure")
			}
		})
	}
}

func TestNativeUnknownThinkingCapabilityDoesNotUseGenericTemplate(t *testing.T) {
	server, _, app := configurationReadServer()
	server.app = &emptyCatalogNativeApp{nativeConfigurationApp: &nativeConfigurationApp{configurationReadApp: app}}
	if options := server.buildSessionConfigOptions(context.Background(), runtimeOptions{Model: "test/observed"}); len(options) != 0 {
		t.Fatalf("unknown native effort advertised generic capability: %+v", options)
	}
}
